"""Turn a directory of EDIs into per-site soundings a layered inversion can fit."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import Field, model_validator

from ofag.core.crs import reproject
from ofag.core.schemas import CoordinateConvention, StrictModel
from ofag.formats.edi import (
    SCALAR_IMPEDANCES,
    apparent_resistivity_ohm_m,
    impedance_phase_degrees,
    impedance_uncertainty_ohm,
    one_dimensionality,
    phase_tensor_invariants,
    read_edi,
    scalar_impedance,
    scalar_uncertainty_ohm,
)
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore

__all__ = ["MtImportRequest", "MtSounding", "ImportedMtSoundings", "MtImportService"]

#: The coordinates an EDI states its position in.
EDI_GEOGRAPHIC_CRS = "EPSG:4326"

#: The columns a magnetotelluric observation file carries.
COLUMNS = ("frequency_hz", "impedance_real_ohm", "impedance_imag_ohm", "uncertainty_ohm")


@dataclass(frozen=True)
class MtSounding:
    """One site, ready to be inverted on its own."""

    sounding_id: str
    easting_m: float
    northing_m: float
    elevation_m: float
    frequencies_hz: np.ndarray
    impedance_ohm: np.ndarray
    uncertainty_ohm: np.ndarray
    apparent_resistivity_ohm_m: np.ndarray
    phase_degrees: np.ndarray
    #: `|Zxy + Zyx| / |Zxy - Zyx|`, reported and no longer screened on: it is multiplied
    #: by the site's galvanic distortion, so it describes the near surface rather than
    #: the structure (F016, F022).
    one_dimensionality: np.ndarray
    #: The phase tensor's skew angle, per frequency.
    skew_degrees: np.ndarray
    #: The phase tensor's ellipticity, per frequency. Zero for a layered earth.
    ellipticity: np.ndarray
    #: Regional strike from the phase tensor, modulo 90 degrees.
    strike_degrees: np.ndarray
    observations_path: str


@dataclass(frozen=True)
class ImportedMtSoundings:
    dataset_id: UUID
    soundings: tuple[MtSounding, ...]
    files_read: int
    refused_as_three_dimensional: tuple[str, ...]
    directory: str
    #: Which scalar the tensor was reduced to.
    impedance_component: str

    def catalog_payload(self) -> dict[str, object]:
        """Small, JSON-compatible description for a project workspace."""
        return {
            "dataset_id": str(self.dataset_id),
            "directory": self.directory,
            "files_read": self.files_read,
            "impedance_component": self.impedance_component,
            "refused_as_three_dimensional": list(self.refused_as_three_dimensional),
            "soundings": [
                {
                    "site_id": site.sounding_id,
                    "observations_path": site.observations_path,
                    "easting_m": site.easting_m,
                    "northing_m": site.northing_m,
                    "elevation_m": site.elevation_m,
                }
                for site in self.soundings
            ],
        }


class MtImportRequest(StrictModel):
    """Where the EDIs are, and the judgements they cannot make for themselves."""

    source_directory: str = Field(min_length=1)
    coordinate_convention: CoordinateConvention
    #: Files whose name contains any of these are skipped.
    exclude_name_fragments: tuple[str, ...] = ("_bvv",)
    #: Use the distant magnetometer as the reference.
    remote_reference: bool = True
    #: Which scalar the tensor is reduced to, of `edi.SCALAR_IMPEDANCES`.
    impedance_component: str = "xy"
    #: How much phase-tensor skew a site may have before it is refused, in degrees, as
    #: the median over its frequencies.
    maximum_phase_tensor_skew_degrees: float = Field(default=3.0, gt=0.0, le=45.0)
    #: A floor on the impedance uncertainty, as a fraction of each frequency's own
    #: value.
    minimum_relative_uncertainty: float = Field(default=0.02, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def the_directory_holds_edis(self) -> "MtImportRequest":
        if self.impedance_component not in SCALAR_IMPEDANCES:
            raise ValueError(
                f"impedance_component must be one of {SCALAR_IMPEDANCES}, "
                f"not {self.impedance_component!r}"
            )
        directory = Path(self.source_directory)
        if not directory.is_dir():
            raise ValueError(f"{self.source_directory} is not a directory")
        if not any(directory.glob("*.edi")):
            raise ValueError(f"{self.source_directory} holds no .edi files")
        return self


@dataclass(frozen=True)
class MtImportService:
    import_root: Path = DEFAULT_IMPORT_ROOT

    def import_edi_directory(self, request: MtImportRequest) -> ImportedMtSoundings:
        store = ImportStore(root=self.import_root)
        dataset_id, directory = store.new_dataset()
        files = [
            path
            for path in sorted(Path(request.source_directory).glob("*.edi"))
            if not any(fragment in path.name for fragment in request.exclude_name_fragments)
        ]
        soundings: list[MtSounding] = []
        refused: list[str] = []
        for path in files:
            station = read_edi(path)
            tensor = station.impedance(remote=request.remote_reference)
            departure = one_dimensionality(tensor)
            invariants = phase_tensor_invariants(tensor)
            skew = float(np.median(np.abs(invariants.skew_degrees)))
            if skew > request.maximum_phase_tensor_skew_degrees:
                refused.append(station.name)
                continue
            impedance = scalar_impedance(tensor, request.impedance_component)
            measured = impedance_uncertainty_ohm(station, tensor)
            uncertainty = np.maximum(
                scalar_uncertainty_ohm(measured, request.impedance_component),
                request.minimum_relative_uncertainty * np.abs(impedance),
            )
            easting, northing = reproject(
                np.asarray([station.longitude_deg]),
                np.asarray([station.latitude_deg]),
                source_crs=EDI_GEOGRAPHIC_CRS,
                target_crs=request.coordinate_convention.crs,
            )
            identifier = "".join(
                character if character.isalnum() else "-" for character in station.name
            ).strip("-")
            observations = directory / f"{identifier}.csv"
            _write(observations, station.frequencies_hz, impedance, uncertainty)
            soundings.append(
                MtSounding(
                    sounding_id=identifier,
                    easting_m=float(easting[0]),
                    northing_m=float(northing[0]),
                    elevation_m=station.elevation_m,
                    frequencies_hz=station.frequencies_hz,
                    impedance_ohm=impedance,
                    uncertainty_ohm=uncertainty,
                    apparent_resistivity_ohm_m=apparent_resistivity_ohm_m(
                        impedance, station.frequencies_hz
                    ),
                    phase_degrees=impedance_phase_degrees(impedance),
                    one_dimensionality=departure,
                    skew_degrees=invariants.skew_degrees,
                    ellipticity=invariants.ellipticity,
                    strike_degrees=invariants.strike_degrees,
                    observations_path=observations.as_posix(),
                )
            )
        identifiers = [sounding.sounding_id for sounding in soundings]
        clashing = sorted({name for name in identifiers if identifiers.count(name) > 1})
        if clashing:
            raise ValueError("two sites would be written to the same file: " + ", ".join(clashing))
        return ImportedMtSoundings(
            dataset_id=dataset_id,
            soundings=tuple(soundings),
            files_read=len(files),
            refused_as_three_dimensional=tuple(refused),
            directory=directory.as_posix(),
            impedance_component=request.impedance_component,
        )


def _write(
    path: Path, frequencies: np.ndarray, impedance: np.ndarray, uncertainty: np.ndarray
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ascending frequency, because a reader that assumes an order will assume this one
    # and an EDI writes its highest first.
    order = np.argsort(frequencies)
    lines = [",".join(COLUMNS)]
    lines += [
        f"{frequencies[index]:.9e},{impedance[index].real:.9e},"
        f"{impedance[index].imag:.9e},{uncertainty[index]:.9e}"
        for index in order
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
