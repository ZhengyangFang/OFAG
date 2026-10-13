"""Import resistivity field data from acquisition-system formats."""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.schemas import CoordinateConvention, StrictModel
from ofag.core.units import canonicalize_quantity
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore

#: How the stored transfer resistance was obtained.
ResistanceProvenance = Literal["measured", "derived_from_apparent_resistivity"]

#: Conventional pseudodepth as a fraction of the electrode spread of a quadrupole.
PSEUDODEPTH_FRACTION = 0.19

#: The browser plots every point, so a very large survey is truncated rather than sent
#: whole.
MAX_PSEUDOSECTION_POINTS = 20_000

#: Instrument formats PyHydroGeophysX can parse.
SUPPORTED_INSTRUMENTS: tuple[str, ...] = (
    "Protocol DC",
    "Protocol IP",
    "Syscal",
    "ResInv",
    "PRIME/RESIMGR",
    "Sting",
    "ABEM-Lund",
    "Lippmann",
    "ARES",
    "BERT",
    "E4D",
    "DAS-1",
    "Electra",
    "Custom",
    "Merged",
)


#: Formats pyGIMLi reads natively.
PYGIMLI_NATIVE_INSTRUMENTS: frozenset[str] = frozenset({"BERT"})


@dataclass(frozen=True)
class _ParsedSurvey:
    """What either reader hands the rest of this service."""

    electrodes: np.ndarray
    quadrupoles: np.ndarray
    resistance_ohm: np.ndarray
    provenance: "ResistanceProvenance"
    reciprocal_error_median_percent: float | None
    #: Measurements the reader dropped before OFAG saw them.
    discarded_by_reader: int


class ERTFieldImportRequest(StrictModel):
    """One acquisition file, with everything the file itself does not state."""

    source_path: str
    instrument: str
    coordinate_convention: CoordinateConvention
    #: The unit the file's electrode coordinates are in.  Never inferred.
    coordinate_unit: str = "m"
    #: Fallback spacing for files that carry no electrode coordinates.
    electrode_spacing: float | None = None
    electrode_file: str | None = None


@dataclass(frozen=True)
class ImportedERTDataset:
    """Canonical SI outputs written for an ERT run to consume."""

    dataset_id: UUID
    source_filename: str
    instrument: str
    electrode_count: int
    observation_count: int
    electrodes_path: str
    quadrupoles_path: str
    observations_path: str
    bounds_m: tuple[float, float, float, float, float, float]
    resistance_min_ohm: float
    resistance_max_ohm: float
    resistance_provenance: ResistanceProvenance
    remote_electrode_count: int
    reciprocal_error_median_percent: float | None
    #: Measurements the reader dropped before OFAG saw them, which for a vendor parser
    #: applying its own reciprocal filter can be most of the survey: 240 of 264 on one
    #: public file, with nothing else saying so.
    discarded_by_reader: int
    #: Which reader was used. pyGIMLi for its own unified format, because it is also the
    #: engine that will invert; the vendor for instrument formats pyGIMLi cannot read.
    reader: str
    geometry_is_assumed: bool
    #: A bounded pseudosection for pre-inversion QC, in plotting order.
    pseudosection_easting_m: tuple[float, ...]
    pseudosection_depth_m: tuple[float, ...]
    pseudosection_apparent_resistivity_ohm_m: tuple[float, ...]
    pseudosection_truncated: bool


class ERTFieldImportService:
    """Turn an acquisition file into OFAG's electrode table and quadrupoles."""

    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def dependency_available(self) -> bool:
        return find_spec("PyHydroGeophysX") is not None

    def import_field_file(self, request: ERTFieldImportRequest) -> ImportedERTDataset:
        if request.instrument not in SUPPORTED_INSTRUMENTS:
            known = ", ".join(SUPPORTED_INSTRUMENTS)
            raise ValueError(f"unknown instrument {request.instrument!r}; supported: {known}")
        source = Path(request.source_path)
        if not source.is_file():
            raise ValueError(f"ERT source file does not exist: {request.source_path}")

        if request.instrument in PYGIMLI_NATIVE_INSTRUMENTS:
            survey = self._read_with_pygimli(request, source)
            reader = "pygimli"
        else:
            survey = self._read_with_vendor(request, source)
            reader = "PyHydroGeophysX"
        electrodes_m = survey.electrodes
        quadrupoles = survey.quadrupoles
        resistance_ohm = survey.resistance_ohm
        provenance = survey.provenance
        reciprocal_median = survey.reciprocal_error_median_percent
        pseudosection = self._pseudosection(electrodes_m, quadrupoles, resistance_ohm)

        dataset_id, destination = self._store.new_dataset()
        electrodes_path = destination / "electrodes_m.npy"
        quadrupoles_path = destination / "quadrupoles.npy"
        observations_path = destination / "observations_ohm.csv"
        np.save(electrodes_path, electrodes_m)
        np.save(quadrupoles_path, quadrupoles)
        observations_path.write_text(
            "resistance_ohm\n" + "\n".join(f"{value:.10e}" for value in resistance_ohm) + "\n",
            encoding="utf-8",
        )

        return ImportedERTDataset(
            dataset_id=dataset_id,
            source_filename=source.name,
            instrument=request.instrument,
            electrode_count=len(electrodes_m),
            observation_count=len(quadrupoles),
            electrodes_path=electrodes_path.as_posix(),
            quadrupoles_path=quadrupoles_path.as_posix(),
            observations_path=observations_path.as_posix(),
            bounds_m=(
                float(electrodes_m[:, 0].min()),
                float(electrodes_m[:, 0].max()),
                float(electrodes_m[:, 1].min()),
                float(electrodes_m[:, 1].max()),
                float(electrodes_m[:, 2].min()),
                float(electrodes_m[:, 2].max()),
            ),
            resistance_min_ohm=float(resistance_ohm.min()),
            resistance_max_ohm=float(resistance_ohm.max()),
            resistance_provenance=provenance,
            remote_electrode_count=int((quadrupoles < 0).any(axis=1).sum()),
            reciprocal_error_median_percent=reciprocal_median,
            discarded_by_reader=survey.discarded_by_reader,
            reader=reader,
            geometry_is_assumed=request.electrode_spacing is not None
            and request.electrode_file is None,
            pseudosection_easting_m=pseudosection["easting"],
            pseudosection_depth_m=pseudosection["depth"],
            pseudosection_apparent_resistivity_ohm_m=pseudosection["apparent_resistivity"],
            pseudosection_truncated=bool(pseudosection["truncated"]),
        )

    @staticmethod
    def _pseudosection(
        electrodes_m: np.ndarray, quadrupoles: np.ndarray, resistance_ohm: np.ndarray
    ) -> dict[str, Any]:
        """Place each measurement at its conventional pseudosection position."""
        easting = electrodes_m[:, 0]
        centres: list[float] = []
        depths: list[float] = []
        for row in quadrupoles:
            used = easting[[index for index in row if index >= 0]]
            centres.append(float(used.mean()))
            depths.append(-float(used.max() - used.min()) * PSEUDODEPTH_FRACTION)
        factors = _geometric_factors(electrodes_m, quadrupoles)
        apparent = resistance_ohm * factors
        keep = min(len(centres), MAX_PSEUDOSECTION_POINTS)
        return {
            "easting": tuple(centres[:keep]),
            "depth": tuple(depths[:keep]),
            "apparent_resistivity": tuple(float(value) for value in apparent[:keep]),
            "truncated": len(centres) > keep,
        }

    @staticmethod
    def _read_with_pygimli(request: ERTFieldImportRequest, source: Path) -> _ParsedSurvey:
        """Read a unified-format file with the engine that will invert it."""
        import pygimli as pg  # type: ignore[import-untyped]
        from pygimli.physics import ert  # type: ignore[import-untyped]

        container = ert.load(str(source), verbose=False)
        electrodes = np.column_stack(
            [np.asarray(pg.x(container)), np.asarray(pg.y(container)), np.asarray(pg.z(container))]
        )
        quadrupoles = np.column_stack(
            [np.asarray(container[token], dtype=np.int64) for token in ("a", "b", "m", "n")]
        )
        if container.haveData("r"):
            resistance = np.asarray(container["r"], dtype=float)
            provenance: ResistanceProvenance = "measured"
        elif container.haveData("rhoa"):
            factors = _geometric_factors(electrodes, quadrupoles)
            resistance = np.asarray(container["rhoa"], dtype=float) / factors
            provenance = "derived_from_apparent_resistivity"
        else:
            raise ValueError(
                f"{source.name} carries neither a transfer resistance nor an apparent "
                "resistivity, so there is nothing to invert"
            )
        converted = np.asarray(
            canonicalize_quantity(electrodes, request.coordinate_unit, QuantityType.LENGTH),
            dtype=float,
        ).reshape(electrodes.shape)
        return _ParsedSurvey(
            electrodes=converted,
            quadrupoles=quadrupoles,
            resistance_ohm=resistance,
            provenance=provenance,
            reciprocal_error_median_percent=None,
            discarded_by_reader=0,
        )

    def _read_with_vendor(self, request: ERTFieldImportRequest, source: Path) -> _ParsedSurvey:
        """Read an instrument format pyGIMLi does not know."""
        standard = self._parse(request, source)
        electrodes = _without_duplicated_elevation(self._electrode_table(standard, request))
        quadrupoles = self._quadrupoles(standard, electrodes)
        resistance, provenance = self._transfer_resistance(standard, electrodes, quadrupoles)
        return _ParsedSurvey(
            electrodes=electrodes,
            quadrupoles=quadrupoles,
            resistance_ohm=resistance,
            provenance=provenance,
            reciprocal_error_median_percent=self._reciprocal_error_median(standard),
            discarded_by_reader=0,
        )

    @staticmethod
    def _parse(request: ERTFieldImportRequest, source: Path) -> Any:
        from PyHydroGeophysX.data_processing.ert_data_agent import (  # type: ignore[import-untyped]
            load_ert_resipy,
        )

        project_dir = source.parent / f".{source.stem}_parser"
        try:
            return load_ert_resipy(
                str(project_dir),
                str(source),
                instrument=request.instrument,
                spacing=request.electrode_spacing,
                electrode_file=request.electrode_file,
                crs=request.coordinate_convention.crs,
            )
        except Exception as error:  # the parsers raise a wide range of types
            raise ValueError(
                f"{request.instrument} parser could not read {source.name}: {error}"
            ) from error

    @staticmethod
    def _electrode_table(standard: Any, request: ERTFieldImportRequest) -> np.ndarray:
        """Electrode coordinates in canonical metres, ordered by their file id."""
        electrodes = sorted(standard.electrodes, key=lambda item: item.id)
        if not electrodes:
            raise ValueError("the file declares no electrodes")
        if [item.id for item in electrodes] != list(range(1, len(electrodes) + 1)):
            raise ValueError("electrode ids must be a contiguous 1-based sequence")
        raw = np.asarray([[item.x, item.y, item.z] for item in electrodes], dtype=float)
        if not np.isfinite(raw).all():
            raise ValueError("electrode coordinates must be finite")
        converted = canonicalize_quantity(raw, request.coordinate_unit, QuantityType.LENGTH)
        return np.asarray(converted, dtype=float).reshape(raw.shape)

    @staticmethod
    def _quadrupoles(standard: Any, electrodes_m: np.ndarray) -> np.ndarray:
        """Convert 1-based file numbering to OFAG's 0-based indices."""
        raw = np.asarray(
            [
                [item.quad.A, item.quad.B, item.quad.M, item.quad.N]
                for item in standard.observations
            ],
            dtype=np.int64,
        )
        if raw.size == 0:
            raise ValueError("the file declares no measurements")
        # A remote electrode is absent rather than numbered, and stays absent.
        remote = raw <= 0
        zero_based = raw - 1
        zero_based[remote] = -1
        highest = int(zero_based.max())
        if highest >= len(electrodes_m):
            raise ValueError(
                f"a quadrupole references electrode {highest + 1} but the file "
                f"declares {len(electrodes_m)} electrodes"
            )
        return zero_based

    @staticmethod
    def _transfer_resistance(
        standard: Any, electrodes_m: np.ndarray, quadrupoles: np.ndarray
    ) -> tuple[np.ndarray, ResistanceProvenance]:
        """Recover the resistance OFAG stores, and say how it was obtained."""
        voltage = np.asarray(
            [np.nan if item.dV is None else item.dV for item in standard.observations], dtype=float
        )
        current = np.asarray(
            [np.nan if item.I is None else item.I for item in standard.observations], dtype=float
        )
        if np.isfinite(voltage).all() and np.isfinite(current).all() and np.all(current != 0):
            return voltage / current, "measured"

        apparent = np.asarray(
            [np.nan if item.app_res is None else item.app_res for item in standard.observations],
            dtype=float,
        )
        if not np.isfinite(apparent).all():
            raise ValueError(
                "the file carries neither voltage and current nor apparent resistivity, "
                "so a transfer resistance cannot be recovered"
            )
        factors = _geometric_factors(electrodes_m, quadrupoles)
        return apparent / factors, "derived_from_apparent_resistivity"

    @staticmethod
    def _reciprocal_error_median(standard: Any) -> float | None:
        """Reciprocal pairs are the honest error estimate when the file has them."""
        from PyHydroGeophysX.data_processing.ert_data_agent import calculate_reciprocal_errors

        try:
            table = calculate_reciprocal_errors(standard)
        except Exception:  # noqa: BLE001 - an absent pairing is not an import failure
            return None
        for column in ("reciprocal_error_percent", "reciprocal_error", "rel_err_percent"):
            if column in table:
                values = np.asarray(table[column], dtype=float)
                finite = values[np.isfinite(values)]
                return float(np.median(finite)) if finite.size else None
        return None


def _without_duplicated_elevation(electrodes_m: np.ndarray) -> np.ndarray:
    """Undo a two-column profile read as three."""
    if len(electrodes_m) < 2:
        return electrodes_m
    northing, elevation = electrodes_m[:, 1], electrodes_m[:, 2]
    if not np.array_equal(northing, elevation) or np.ptp(elevation) == 0.0:
        return electrodes_m
    corrected = electrodes_m.copy()
    corrected[:, 1] = 0.0
    return corrected


def _geometric_factors(electrodes_m: np.ndarray, quadrupoles: np.ndarray) -> np.ndarray:
    """Compute K from the electrode geometry with the engine that will invert."""
    from pygimli.physics import ert

    from ofag.engines.pygimli.geometry import geometric_factors

    planar = bool(np.ptp(electrodes_m[:, 1]) == 0.0)
    sensors = np.column_stack([electrodes_m[:, 0], electrodes_m[:, 2]]) if planar else electrodes_m
    scheme = ert.createData(elecs=sensors, schemeName="dd")
    scheme.resize(len(quadrupoles))
    for position, token in enumerate("abmn"):
        scheme[token] = quadrupoles[:, position]
    factors = geometric_factors(ert, scheme, electrodes_m)
    if not np.isfinite(factors).all() or np.any(factors == 0):
        raise ValueError(
            "the electrode geometry gives a degenerate geometric factor for at least "
            "one quadrupole, so apparent resistivity cannot be converted"
        )
    return factors
