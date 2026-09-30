"""Canonical, local data-import adapters for the workbench."""

import csv
import json
import re
from io import StringIO
from pathlib import Path

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CsvImportRequest,
    CsvPreview,
    CsvPreviewRequest,
    GravityCsvImportRequest,
    ImportedGravityDataset,
    ImportedMagneticDataset,
    ImportedTDEMDataset,
    ImportedTDEMSounding,
    ImportedTopographyDataset,
    MagneticCsvImportRequest,
    TDEMCsvImportRequest,
    TopographyCsvImportRequest,
)
from ofag.core.units import canonicalize_quantity
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore


def _rows_of(request: CsvImportRequest) -> tuple[list[str], list[dict[str, str]]]:
    """Read a request's CSV, from wherever it came from."""
    if request.csv_text is not None:
        return _header_and_rows(csv.DictReader(StringIO(request.csv_text)))
    path = Path(request.source_path or "")
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    # utf-8-sig so a byte-order mark written by Excel does not become part of the first
    # column's name, which would make every mapping of it fail.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return _header_and_rows(csv.DictReader(stream))


def _header_and_rows(reader: "csv.DictReader[str]") -> tuple[list[str], list[dict[str, str]]]:
    if reader.fieldnames is None:
        raise ValueError("CSV must include a header row")
    return list(reader.fieldnames), list(reader)


class DataImportService:
    def __init__(self, import_root: Path | None = None) -> None:
        self._store = ImportStore(import_root or DEFAULT_IMPORT_ROOT)

    @property
    def import_root(self) -> Path:
        """Where this service writes, which is the project's own directory."""
        return self._store.root

    def preview_csv(self, request: CsvPreviewRequest) -> CsvPreview:
        """The header and some rows of a file only the service can open."""
        path = Path(request.source_path)
        if not path.is_file():
            raise ValueError(f"{path} does not exist")
        rows: list[dict[str, str]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ValueError("CSV must include a header row")
            columns = tuple(reader.fieldnames)
            total = 0
            for row in reader:
                total += 1
                if len(rows) < request.max_rows:
                    rows.append({key: value or "" for key, value in row.items() if key is not None})
        return CsvPreview(
            columns=columns,
            rows=tuple(rows),
            total_rows=total,
            truncated=total > len(rows),
        )

    def import_gravity_csv(self, request: GravityCsvImportRequest) -> ImportedGravityDataset:
        fieldnames, rows = _rows_of(request)
        required = {request.x_column, request.y_column, request.z_column, request.gravity_column}
        if request.uncertainty_column is not None:
            required.add(request.uncertainty_column)
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(f"CSV is missing mapped columns: {', '.join(missing)}")
        if not rows:
            raise ValueError("CSV contains no observation rows")
        try:
            x = np.asarray([float(row[request.x_column]) for row in rows], dtype=float)
            y = np.asarray([float(row[request.y_column]) for row in rows], dtype=float)
            z = np.asarray([float(row[request.z_column]) for row in rows], dtype=float)
            gravity = np.asarray([float(row[request.gravity_column]) for row in rows], dtype=float)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "mapped coordinate and gravity columns must contain numeric values"
            ) from error
        if not all(np.isfinite(values).all() for values in (x, y, z, gravity)):
            raise ValueError("mapped coordinate and gravity columns must contain finite values")
        x_m = np.asarray(
            canonicalize_quantity(x, request.coordinate_unit, QuantityType.LENGTH), dtype=float
        )
        y_m = np.asarray(
            canonicalize_quantity(y, request.coordinate_unit, QuantityType.LENGTH), dtype=float
        )
        z_m = np.asarray(
            canonicalize_quantity(z, request.coordinate_unit, QuantityType.LENGTH), dtype=float
        )
        gravity_mgal = np.asarray(
            canonicalize_quantity(gravity, request.gravity_unit, QuantityType.GRAVITY_ACCELERATION),
            dtype=float,
        )
        if request.uncertainty_column is None:
            recommended_uncertainty = float(
                max(np.max(np.abs(gravity_mgal)) * request.default_uncertainty_percent / 100, 1e-6)
            )
        else:
            try:
                uncertainty = np.asarray(
                    [float(row[request.uncertainty_column]) for row in rows], dtype=float
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("uncertainty column must contain numeric values") from error
            if not np.isfinite(uncertainty).all() or np.any(uncertainty <= 0):
                raise ValueError("uncertainty values must be finite and greater than zero")
            converted = canonicalize_quantity(
                uncertainty,
                request.uncertainty_unit or "",
                QuantityType.GRAVITY_ACCELERATION,
            )
            recommended_uncertainty = float(np.median(np.asarray(converted, dtype=float)))
        dataset_id, destination = self._store.new_dataset()
        observations_path = destination / "observations_mgal.csv"
        np.savetxt(
            observations_path,
            np.c_[x_m, y_m, z_m, gravity_mgal],
            delimiter=",",
            header="x_m,y_m,z_m,gravity_mgal",
            comments="",
            fmt="%.12e",
        )
        return ImportedGravityDataset(
            dataset_id=dataset_id,
            source_filename=Path(request.filename).name,
            canonical_observations_path=observations_path.as_posix(),
            coordinate_convention=request.coordinate_convention,
            row_count=len(rows),
            bounds_m=(
                float(np.min(x_m)),
                float(np.max(x_m)),
                float(np.min(y_m)),
                float(np.max(y_m)),
                float(np.min(z_m)),
                float(np.max(z_m)),
            ),
            gravity_min_mgal=float(np.min(gravity_mgal)),
            gravity_max_mgal=float(np.max(gravity_mgal)),
            recommended_uncertainty_mgal=recommended_uncertainty,
        )

    def import_tdem_csv(self, request: TDEMCsvImportRequest) -> ImportedTDEMDataset:
        """Canonicalize a single or long-table batch B-field TDEM import."""
        fieldnames, rows = _rows_of(request)
        required = {request.time_column, request.response_column}
        if request.uncertainty_column is not None:
            required.add(request.uncertainty_column)
        if request.import_mode == "batch":
            assert request.sounding_id_column is not None
            assert request.x_column is not None
            assert request.y_column is not None
            assert request.z_column is not None
            required.update(
                {
                    request.sounding_id_column,
                    request.x_column,
                    request.y_column,
                    request.z_column,
                }
            )
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(f"CSV is missing mapped columns: {', '.join(missing)}")
        if not rows:
            raise ValueError("CSV contains no TDEM channels")
        try:
            times = np.asarray([float(row[request.time_column]) for row in rows], dtype=float)
            response = np.asarray(
                [float(row[request.response_column]) for row in rows], dtype=float
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "mapped time and response columns must contain numeric values"
            ) from error
        if not np.isfinite(times).all() or not np.isfinite(response).all() or np.any(times <= 0):
            raise ValueError("TDEM times must be finite and positive; responses must be finite")
        time_s = np.asarray(
            canonicalize_quantity(times, request.time_unit, QuantityType.TIME), dtype=float
        )
        response_t = np.asarray(
            canonicalize_quantity(
                response, request.response_unit, QuantityType.MAGNETIC_FLUX_DENSITY
            ),
            dtype=float,
        )
        if request.uncertainty_column is None:
            uncertainty_t: np.ndarray | None = None
        else:
            try:
                uncertainty = np.asarray(
                    [float(row[request.uncertainty_column]) for row in rows], dtype=float
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("uncertainty column must contain numeric values") from error
            if not np.isfinite(uncertainty).all() or np.any(uncertainty <= 0):
                raise ValueError("uncertainty values must be finite and greater than zero")
            uncertainty_t = np.asarray(
                canonicalize_quantity(
                    uncertainty,
                    request.uncertainty_unit or "",
                    QuantityType.MAGNETIC_FLUX_DENSITY,
                ),
                dtype=float,
            )
        dataset_id, destination = self._store.new_dataset()
        if request.import_mode == "single":
            order = np.argsort(time_s)
            time_s, response_t = time_s[order], response_t[order]
            if np.any(np.diff(time_s) <= 0):
                raise ValueError("TDEM channel times must be unique after unit conversion")
            recommended_uncertainty = self._tdem_uncertainty(
                response_t,
                uncertainty_t[order] if uncertainty_t is not None else None,
                request.default_uncertainty_percent,
            )
            observations_path = destination / "observations_t.csv"
            self._write_tdem_channels(observations_path, time_s, response_t)
            soundings: tuple[ImportedTDEMSounding, ...] = (
                ImportedTDEMSounding(
                    sounding_id="sounding-1",
                    canonical_observations_path=observations_path.as_posix(),
                    location_m=(0.0, 0.0, 0.0),
                    channel_count=len(time_s),
                    times_s=tuple(float(item) for item in time_s),
                    recommended_uncertainty_t=recommended_uncertainty,
                ),
            )
            batch_manifest_path = None
            canonical_observations_path = observations_path.as_posix()
        else:
            assert request.sounding_id_column is not None
            assert request.x_column is not None
            assert request.y_column is not None
            assert request.z_column is not None
            assert request.coordinate_unit is not None
            sounding_ids = [row[request.sounding_id_column].strip() for row in rows]
            if not all(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value) for value in sounding_ids
            ):
                raise ValueError(
                    "sounding IDs must use letters, numbers, dot, underscore or hyphen"
                )
            try:
                coordinates = tuple(
                    np.asarray([float(row[column]) for row in rows], dtype=float)
                    for column in (request.x_column, request.y_column, request.z_column)
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "batch sounding coordinates must contain numeric values"
                ) from error
            if not all(np.isfinite(values).all() for values in coordinates):
                raise ValueError("batch sounding coordinates must be finite")
            x_m, y_m, z_m = (
                np.asarray(
                    canonicalize_quantity(values, request.coordinate_unit, QuantityType.LENGTH),
                    dtype=float,
                )
                for values in coordinates
            )
            grouped: dict[str, list[int]] = {}
            for index, sounding_id in enumerate(sounding_ids):
                grouped.setdefault(sounding_id, []).append(index)
            soundings_dir = destination / "soundings"
            soundings_dir.mkdir(parents=True, exist_ok=True)
            imported_soundings: list[ImportedTDEMSounding] = []
            for sounding_id, indices_list in grouped.items():
                indices = np.asarray(indices_list, dtype=int)
                location = np.asarray([x_m[indices[0]], y_m[indices[0]], z_m[indices[0]]])
                if not all(
                    np.allclose(values[indices], location[axis])
                    for axis, values in enumerate((x_m, y_m, z_m))
                ):
                    raise ValueError(
                        f"all rows for sounding '{sounding_id}' must have one receiver location"
                    )
                order = indices[np.argsort(time_s[indices])]
                sounding_times = time_s[order]
                sounding_response = response_t[order]
                if np.any(np.diff(sounding_times) <= 0):
                    raise ValueError(
                        f"TDEM channel times must be unique for sounding '{sounding_id}'"
                    )
                sounding_uncertainty = uncertainty_t[order] if uncertainty_t is not None else None
                path = soundings_dir / f"{sounding_id}.csv"
                self._write_tdem_channels(path, sounding_times, sounding_response)
                imported_soundings.append(
                    ImportedTDEMSounding(
                        sounding_id=sounding_id,
                        canonical_observations_path=path.as_posix(),
                        location_m=(
                            float(location[0]),
                            float(location[1]),
                            float(location[2]),
                        ),
                        channel_count=len(sounding_times),
                        times_s=tuple(float(item) for item in sounding_times),
                        recommended_uncertainty_t=self._tdem_uncertainty(
                            sounding_response,
                            sounding_uncertainty,
                            request.default_uncertainty_percent,
                        ),
                    )
                )
            soundings = tuple(imported_soundings)
            manifest_path = destination / "batch_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "soundings": [
                            {
                                "sounding_id": sounding.sounding_id,
                                "observations_path": sounding.canonical_observations_path,
                                "location_m": sounding.location_m,
                            }
                            for sounding in soundings
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            batch_manifest_path = manifest_path.as_posix()
            canonical_observations_path = batch_manifest_path
            recommended_uncertainty = float(
                np.median([sounding.recommended_uncertainty_t for sounding in soundings])
            )
        return ImportedTDEMDataset(
            dataset_id=dataset_id,
            source_filename=Path(request.filename).name,
            canonical_observations_path=canonical_observations_path,
            coordinate_convention=request.coordinate_convention,
            row_count=len(rows),
            times_s=tuple(float(item) for item in np.unique(time_s)),
            time_min_s=float(np.min(time_s)),
            time_max_s=float(np.max(time_s)),
            response_min_t=float(np.min(response_t)),
            response_max_t=float(np.max(response_t)),
            recommended_uncertainty_t=recommended_uncertainty,
            import_mode=request.import_mode,
            sounding_count=len(soundings),
            soundings=soundings,
            batch_manifest_path=batch_manifest_path,
        )

    @staticmethod
    def _tdem_uncertainty(
        response_t: np.ndarray, uncertainty_t: np.ndarray | None, percent: float
    ) -> float:
        if uncertainty_t is not None:
            return float(np.median(uncertainty_t))
        return float(max(np.max(np.abs(response_t)) * percent / 100, 1e-18))

    @staticmethod
    def _write_tdem_channels(path: Path, time_s: np.ndarray, response_t: np.ndarray) -> None:
        np.savetxt(
            path,
            np.c_[time_s, response_t],
            delimiter=",",
            header="time_s,magnetic_flux_density_t",
            comments="",
            fmt="%.12e",
        )

    def import_topography_csv(
        self, request: TopographyCsvImportRequest
    ) -> ImportedTopographyDataset:
        fieldnames, rows = _rows_of(request)
        required = {request.x_column, request.y_column, request.z_column}
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(f"CSV is missing mapped columns: {', '.join(missing)}")
        if not rows:
            raise ValueError("CSV contains no topography rows")
        try:
            coordinates = tuple(
                np.asarray([float(row[column]) for row in rows], dtype=float)
                for column in (request.x_column, request.y_column, request.z_column)
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("mapped topography columns must contain numeric values") from error
        if not all(np.isfinite(values).all() for values in coordinates):
            raise ValueError("mapped topography columns must contain finite values")
        x_m, y_m, z_m = (
            np.asarray(
                canonicalize_quantity(values, request.coordinate_unit, QuantityType.LENGTH),
                dtype=float,
            )
            for values in coordinates
        )
        dataset_id, destination = self._store.new_dataset()
        topography_path = destination / "topography_m.csv"
        np.savetxt(
            topography_path,
            np.c_[x_m, y_m, z_m],
            delimiter=",",
            header="x_m,y_m,z_m",
            comments="",
            fmt="%.12e",
        )
        return ImportedTopographyDataset(
            dataset_id=dataset_id,
            source_filename=Path(request.filename).name,
            canonical_topography_path=topography_path.as_posix(),
            coordinate_convention=request.coordinate_convention,
            row_count=len(rows),
            bounds_m=(
                float(np.min(x_m)),
                float(np.max(x_m)),
                float(np.min(y_m)),
                float(np.max(y_m)),
                float(np.min(z_m)),
                float(np.max(z_m)),
            ),
        )

    def import_magnetic_csv(self, request: MagneticCsvImportRequest) -> ImportedMagneticDataset:
        fieldnames, rows = _rows_of(request)
        required = {request.x_column, request.y_column, request.z_column, request.tmi_column}
        if request.uncertainty_column is not None:
            required.add(request.uncertainty_column)
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(f"CSV is missing mapped columns: {', '.join(missing)}")
        if not rows:
            raise ValueError("CSV contains no observation rows")
        try:
            x, y, z, tmi = (
                np.asarray([float(row[column]) for row in rows], dtype=float)
                for column in (
                    request.x_column,
                    request.y_column,
                    request.z_column,
                    request.tmi_column,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "mapped coordinate and TMI columns must contain numeric values"
            ) from error
        if not all(np.isfinite(values).all() for values in (x, y, z, tmi)):
            raise ValueError("mapped coordinate and TMI columns must contain finite values")
        x_m, y_m, z_m = (
            np.asarray(
                canonicalize_quantity(values, request.coordinate_unit, QuantityType.LENGTH),
                dtype=float,
            )
            for values in (x, y, z)
        )
        tmi_nt = np.asarray(
            canonicalize_quantity(tmi, request.tmi_unit, QuantityType.MAGNETIC_ANOMALY), dtype=float
        )
        if request.uncertainty_column is None:
            recommended_uncertainty = float(
                max(np.max(np.abs(tmi_nt)) * request.default_uncertainty_percent / 100, 1e-6)
            )
        else:
            try:
                uncertainty = np.asarray(
                    [float(row[request.uncertainty_column]) for row in rows], dtype=float
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("uncertainty column must contain numeric values") from error
            if not np.isfinite(uncertainty).all() or np.any(uncertainty <= 0):
                raise ValueError("uncertainty values must be finite and greater than zero")
            recommended_uncertainty = float(
                np.median(
                    np.asarray(
                        canonicalize_quantity(
                            uncertainty,
                            request.uncertainty_unit or "",
                            QuantityType.MAGNETIC_ANOMALY,
                        ),
                        dtype=float,
                    )
                )
            )
        dataset_id, destination = self._store.new_dataset()
        observations_path = destination / "observations_tmi_nt.csv"
        np.savetxt(
            observations_path,
            np.c_[x_m, y_m, z_m, tmi_nt],
            delimiter=",",
            header="x_m,y_m,z_m,tmi_nt",
            comments="",
            fmt="%.12e",
        )
        return ImportedMagneticDataset(
            dataset_id=dataset_id,
            source_filename=Path(request.filename).name,
            canonical_observations_path=observations_path.as_posix(),
            coordinate_convention=request.coordinate_convention,
            row_count=len(rows),
            bounds_m=(
                float(np.min(x_m)),
                float(np.max(x_m)),
                float(np.min(y_m)),
                float(np.max(y_m)),
                float(np.min(z_m)),
                float(np.max(z_m)),
            ),
            tmi_min_nt=float(np.min(tmi_nt)),
            tmi_max_nt=float(np.max(tmi_nt)),
            recommended_uncertainty_nt=recommended_uncertainty,
        )
