"""Case 1: the Utah FORGE site, Milford, Utah."""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DataChannelSpec,
    DatasetSpec,
    ProjectCreateRequest,
    QuantitySpec,
    RunSpec,
    TreeMeshSpec,
)
from ofag.services.project_service import ProjectService

if TYPE_CHECKING:
    from ofag.core.cell_model import CellModel
    from ofag.services.interpretation_service import LayeredSection

CASE = Path("data/case1_Utah FORGE")
GRAVITY = CASE / "gravity"
DEM = CASE / "dem/forge_3dep_30m.tif"
RESULT_ROOT = Path("Result")
PROJECT_NAME = "Utah FORGE"

#: UTM zone 12N on NAD83, which every FORGE release states.
CRS = "EPSG:26912"

#: Witter's model volume, read from his report: 8.25 km east-west by 5.25 km
#: north-south, elevation -1200 to +2490 m. The published density model's own
#: extent agrees with it.
VOLUME = (331_900.0, 340_150.0, 4_259_925.0, 4_265_150.0)

#: The elevation range of that volume, from the same report. Needed as well
#: as the plan extent wherever a share of the model is quoted: the mesh is
#: padded far beyond it, and the padding cells are up to 5,398 m on a side.
ELEVATION_RANGE_M = (-1_200.0, 2_490.0)

#: His octree: 50 m in plan, 30 m thick at the surface, coarsening downward.
#: These padding levels give 271,048 cells against the "fewer than 300,000" he
#: reports and the 268,773 in the model he released.
MESH_CELL_M = (50.0, 50.0, 30.0)
SURFACE_PADDING_CELLS = (0, 0, 4, 6)
RECEIVER_PADDING_CELLS = (2, 4)

#: The density the delivered Complete Bouguer Anomaly is reduced at. Stated in
#: the survey's own metadata file: "A 2.67 g/cm^3 reduction density was used for
#: the Bouguer correction."
DELIVERED_REDUCTION_DENSITY = 2.67

#: The density the modelling is done at, and the background every density in
#: this script is a contrast against.
#:
#: Not 2.67. Witter reduced the same measurements again before inverting them:
#: Nettleton and Parasnis both need relief and the basin has none, so he ran
#: forward and inverse tests from 2.50 to 2.67 and concluded that "a terrain
#: correction density of 2.55 g/cm3 is a good approximation of the average
#: density of the model volume", used "for all subsequent 3D gravity modelling".
#:
#: This is not bookkeeping. A density model is a set of contrasts against the
#: reduction density, so the same recovered model means 2.42 against one
#: background and 2.54 against the other. Reducing at 2.67 and then reading the
#: result against Witter's absolute densities would compare two different
#: quantities and call the 0.12 difference a result.
REDUCTION_DENSITY = 2.55

#: Witter's starting model: basin fill over granitoid basement, split by the
#: top-of-granite surface, as absolute densities. Converted to contrasts where
#: they are used, because that is what OFAG's gravity plugin inverts for.
BASIN_FILL_DENSITY = 2.42
BASEMENT_DENSITY = 2.65

#: What the bounds mean, as absolute densities rather than as contrasts: dry
#: unconsolidated alluvium at the bottom, and above the 2.86 of the densest
#: cell in Witter's released model with room to spare. Written this way because
#: a bound is a statement about rocks, and a contrast bound silently changes
#: which rocks it admits when the reduction density changes.
LOWEST_PLAUSIBLE_DENSITY = 2.07
HIGHEST_PLAUSIBLE_DENSITY = 3.02

#: The gravimeter sensor sits about 20 cm above the ground, which his report
#: states and his station file confirms: every one of the 323 observation
#: elevations is NAVD88 plus 0.200 m, with 3 mm of scatter over the survey.
SENSOR_HEIGHT_M = 0.2


def _project() -> tuple[ProjectService, object]:
    projects = ProjectService(root=RESULT_ROOT)
    for record in projects.list():
        if record.name == PROJECT_NAME:
            return projects, record
    return projects, projects.create(
        ProjectCreateRequest(
            name=PROJECT_NAME,
            coordinate_convention=CoordinateConvention(crs=CRS),
            elevation_reference="NAVD88",
            enabled_methods=("gravity",),
        )
    )


def _state_path(folder: object) -> Path:
    return Path(folder.root) / "case_state.json"  # type: ignore[attr-defined]


def _load_state(folder: object) -> dict:
    path = _state_path(folder)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save_state(folder: object, **values: object) -> dict:
    state = _load_state(folder)
    state.update(values)
    _state_path(folder).write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return state


# -- prepare ---------------------------------------------------------------


def prepare() -> None:
    """Import the stations Witter used, the terrain, and the granite surface."""
    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    print(f"project   {folder.root}")

    stations = _witters_stations()
    print(
        f"gravity   {len(stations)} stations, CBGA at {DELIVERED_REDUCTION_DENSITY} "
        f"{stations['gCBGA'].min():.2f} to {stations['gCBGA'].max():.2f} mGal, elevation "
        f"{stations['NAVD88'].min():.0f} to {stations['NAVD88'].max():.0f} m"
    )
    imported = _import_gravity(folder, stations)
    print(
        f"          re-reduced to {REDUCTION_DENSITY}, shifting the anomaly by "
        f"{imported['re_reduction_rms_mgal']:.3f} mGal RMS about its own level"
    )
    print(
        f"          regional level {imported['regional_removed_mgal']:.2f} mGal removed "
        f"({REGIONAL_REMOVED}); a local model cannot produce it"
    )

    terrain = _terrain(folder)
    print(f"terrain   {terrain['count']:,} points at {terrain['spacing_m']:.0f} m")

    granite = _granite_surface(folder)
    print(
        f"granite   {granite['count']:,} points on the original seismic surface, elevation "
        f"{granite['min_z']:.0f} to {granite['max_z']:.0f} m; the modified one kept to "
        f"compare, {granite['rejected']} of its points rejected as impossible"
    )

    _save_state(
        folder,
        project_id=str(record.project_id),  # type: ignore[attr-defined]
        observations_path=imported["path"],
        observation_count=len(stations),
        regional_removed_mgal=imported["regional_removed_mgal"],
        topography_path=terrain["path"],
        granite_path=granite["path"],
        granite_modified_path=granite["modified_path"],
    )


def _witters_stations() -> object:
    """The 323 stations of the published inversion, with their observations."""
    import pandas as pd
    from scipy.spatial import cKDTree

    misfit = pd.read_csv(GRAVITY / "published_misfit.csv")
    observations = pd.read_csv(GRAVITY / "stations_2c.txt", sep="\t")
    distance, index = cKDTree(np.c_[observations.Easting, observations.Northing]).query(
        np.c_[misfit.X_UTMNAD83z12_m, misfit.Y_UTMNAD83z12_m]
    )
    if distance.max() > 1.0 or len(set(index)) != len(misfit):
        raise SystemExit(
            f"the published stations do not match the observations: "
            f"{len(set(index))} distinct of {len(misfit)}, worst {distance.max():.1f} m"
        )
    return observations.iloc[index].reset_index(drop=True)


#: Removed from the observations before inverting, and reported.
#:
#: A complete Bouguer anomaly of -203 mGal is not a local anomaly: it carries
#: the crustal and isostatic field of half a continent, and an 8 by 5 by 3 km
#: model cannot produce it. Fed the data as published, the inversion ran to
#: "SUCCEEDED" with a residual of 111 mGal, predicting -94 where the data says
#: -203.
#:
#: Witter's report states that "no regional gravity trend was removed from the
#: data prior to 3D geophysical modelling". His model nonetheless explains only
#: the variation: read as a contrast against the reduction density and summed
#: as slabs, it produces -21 to +6 mGal, a range of 27.0 against the data's
#: 24.45. The level is absorbed somewhere his report does not say.
#:
#: So the mean is removed here, explicitly, and its value recorded. Only the
#: mean and not a plane, because his model accounts for essentially all of the
#: variation and removing more would be removing signal he kept.
REGIONAL_REMOVED = "mean"

#: The random part of the error budget: 0.03 mGal, which the Utah Geological
#: Survey states for the data it delivered and Witter quotes.
#:
#: This replaces a bottom-up estimate of 0.015 that was built here first, from
#: the two terms the file exposes -- `errg` at 0.001 mGal, the meter's
#: repeatability after processing, and station elevations good to 0.05 m
#: contributing 0.3086 x 0.05 = 0.015 through the free-air gradient. That
#: number is a lower bound and not an error budget. It counts the terms whose
#: size happens to be written down and silently sets every other term to zero:
#: horizontal position, drift and tare, the near-field terrain correction, and
#: whatever the reduction did between the meter and the delivered column.
#:
#: The 0.03 is worth more than the 0.015 because it is a measurement of the
#: product rather than a sum over the parts of it that were easy to find.
#: Halving an uncertainty doubles the weight on every datum, and at 145,062
#: cells against 323 observations the inversion answers by going to its bounds:
#: at 0.015 both models here saturated both bounds and correlated with the
#: published one at 0.23. The check that this is the right number and not a
#: convenient one is external -- Witter's published misfit is 0.0298 mGal RMS,
#: which is chi-squared 0.99 against 0.03 and 3.9 against 0.015. He stopped
#: where a 0.03 uncertainty says to stop.
#:
#: A third term in the budget is deliberately left out. Witter tested
#: terrain-correction densities from 2.50 to 2.67, a six per cent uncertainty
#: which over a median terrain correction of 1.8 mGal and a median Bouguer
#: correction of 7.1 mGal comes to 0.46 mGal. That is not random: it is
#: proportional to terrain, so it biases the field in a way correlated with
#: topography rather than scattering it. Putting it in the per-station
#: uncertainty would loosen every datum equally to account for an error that
#: is not equal and not independent. It bounds what can be believed about
#: terrain-shaped structure; it does not belong in chi-squared.
DATA_UNCERTAINTY_MGAL = 0.03


def _import_gravity(folder: object, stations: object) -> dict:
    """Canonical observations, with an uncertainty that is not the file's zero."""
    from ofag.core.schemas import GravityCsvImportRequest
    from ofag.services.data_import import DataImportService

    if float(stations["errg"].min()) <= 0.0:  # type: ignore[index]
        raise SystemExit(
            "a station reports an uncertainty of zero, which is an absence of a "
            "measurement and not a measurement of zero; it would be given infinite weight"
        )
    columns = ["Easting", "Northing", "sensor_z", "gCBGA", "errg"]
    delivered = stations["gCBGA"]  # type: ignore[index]
    modelling = _reduced_to_modelling_density(stations)
    shift = (modelling - modelling.mean()) - (delivered - delivered.mean())  # type: ignore[attr-defined]
    stations = stations.assign(  # type: ignore[attr-defined]
        gCBGA=modelling,
        sensor_z=stations["NAVD88"] + SENSOR_HEIGHT_M,  # type: ignore[index]
    )
    level = float(stations["gCBGA"].mean())
    stations = stations.assign(gCBGA=stations["gCBGA"] - level)
    text = (
        ",".join(columns)
        + "\n"
        + "\n".join(
            ",".join(f"{row[name]}" for name in columns)
            for _, row in stations.iterrows()  # type: ignore[attr-defined]
        )
    )
    imported = DataImportService(import_root=Path(folder.imports_root)).import_gravity_csv(  # type: ignore[attr-defined]
        GravityCsvImportRequest(
            filename="FORGE_2C_witter323.csv",
            csv_text=text,
            x_column="Easting",
            y_column="Northing",
            z_column="sensor_z",
            gravity_column="gCBGA",
            uncertainty_column="errg",
            coordinate_unit="m",
            gravity_unit="mGal",
            uncertainty_unit="mGal",
            coordinate_convention=CoordinateConvention(crs=CRS),
        )
    )
    return {
        "path": imported.canonical_observations_path,
        "rows": imported.row_count,
        "regional_removed_mgal": level,
        "re_reduction_rms_mgal": float(shift.std()),
    }


def _reduced_to_modelling_density(stations: object) -> object:
    """The delivered 2.67 anomaly, re-reduced to the 2.55 the modelling uses."""
    slab_coefficient = 0.04193  # mGal per metre per g/cm^3
    elevation = stations["NAVD88"]  # type: ignore[index]
    terrain = stations["iztc"] + stations["oztc"]  # type: ignore[index]
    difference = DELIVERED_REDUCTION_DENSITY - REDUCTION_DENSITY
    return (
        stations["gCBGA"]  # type: ignore[index]
        + slab_coefficient * difference * elevation
        - terrain * (difference / DELIVERED_REDUCTION_DENSITY)
    )


def _terrain(folder: object) -> dict:
    """The land surface for the mesh, sampled from the DEM at the cell size."""
    from ofag.formats.raster import sample_elevation

    spacing = MESH_CELL_M[0]
    east = np.arange(VOLUME[0] - 1_500, VOLUME[1] + 1_500 + spacing, spacing)
    north = np.arange(VOLUME[2] - 1_500, VOLUME[3] + 1_500 + spacing, spacing)
    grid_east, grid_north = np.meshgrid(east, north)
    elevation = sample_elevation(
        DEM, grid_east.ravel(), grid_north.ravel(), crs=CRS, elevation_unit="m"
    )
    path = Path(folder.imports_root) / "terrain_50m.csv"  # type: ignore[attr-defined]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(
        path,
        np.c_[grid_east.ravel(), grid_north.ravel(), elevation],
        delimiter=",",
        header="x_m,y_m,z_m",
        comments="",
        fmt="%.3f",
    )
    return {"path": path.as_posix(), "count": int(elevation.size), "spacing_m": spacing}


#: The seismic top of granite: the FORGE earth-model surface Witter fixed in
#: his model 1, before he changed it to suit his gravity. The delivery ships it
#: only inside its Geoscience Analyst workspace, so it is read out of that file
#: once (`_original_surface`) and kept beside it as a CSV.
ORIGINAL_SURFACE = GRAVITY / "granite_surface_original.csv"
WORKSPACE = GRAVITY / "workspace.geoh5"


def _granite_surface(folder: object) -> dict:
    """The seismic top of granite, and Witter's gravity-modified version of it."""
    import pandas as pd

    imports = Path(folder.imports_root)  # type: ignore[attr-defined]
    original = pd.read_csv(_original_surface())
    frame = pd.read_csv(GRAVITY / "granite_surface_TEST.csv")
    east = frame["X_UTMNAD83z12_m"]
    north = frame["Y_UTMNAD83z12_m"]
    # Zone 12N spans 166,000 to 834,000 m of easting by construction.
    plausible = east.between(166_000, 834_000) & north.between(0, 10_000_000)
    modified = frame[plausible]
    paths = {}
    for name, kept in (("top_of_granite.csv", original), ("top_of_granite_modified.csv", modified)):
        paths[name] = imports / name
        np.savetxt(
            paths[name],
            np.c_[
                kept["X_UTMNAD83z12_m"].to_numpy(),
                kept["Y_UTMNAD83z12_m"].to_numpy(),
                kept["Z_Elevation_m"].to_numpy(),
            ],
            delimiter=",",
            header="x_m,y_m,z_m",
            comments="",
            fmt="%.3f",
        )
    return {
        "path": paths["top_of_granite.csv"].as_posix(),
        "modified_path": paths["top_of_granite_modified.csv"].as_posix(),
        "count": int(len(original)),
        "rejected": int((~plausible).sum()),
        "min_z": float(original["Z_Elevation_m"].min()),
        "max_z": float(original["Z_Elevation_m"].max()),
    }


def _original_surface() -> Path:
    """The original top-of-granite surface, read once out of the workspace."""
    if ORIGINAL_SURFACE.exists():
        return ORIGINAL_SURFACE
    try:
        import h5py
    except ImportError as error:
        raise SystemExit(
            f"{ORIGINAL_SURFACE} is missing; extract it once with "
            "`uv run --with h5py python scripts/case1_forge.py prepare`"
        ) from error
    with h5py.File(WORKSPACE, "r") as workspace:
        found = []
        workspace.visititems(
            lambda _, item: (
                found.append(item)
                if item.attrs.get("Name") == "Original Top of Granite Surface"
                else None
            )
        )
        if len(found) != 1:
            raise SystemExit(f"expected one original surface in {WORKSPACE}, found {len(found)}")
        vertices = found[0]["Vertices"][()]
    np.savetxt(
        ORIGINAL_SURFACE,
        np.c_[vertices["x"], vertices["y"], vertices["z"]],
        delimiter=",",
        header="X_UTMNAD83z12_m,Y_UTMNAD83z12_m,Z_Elevation_m",
        comments="",
        fmt="%.3f",
    )
    return ORIGINAL_SURFACE


# -- invert ----------------------------------------------------------------


def invert() -> None:
    """Witter's inversion, on Witter's stations, through OFAG."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if "observations_path" not in state:
        raise SystemExit("run `prepare` first")

    reference = _reference_model(folder, state)
    print(
        f"reference {reference['cells']:,} mesh cells, {reference['basin']:,} basin fill and "
        f"{reference['basement']:,} basement"
    )

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    spec = _run_spec(record, state, reference["path"], label="smooth, two-layer reference")
    report = runs.validate(spec)
    if not report.valid:
        for issue in report.issues:
            print(f"  {issue.field}: {issue.message}")
        raise SystemExit("the run specification is not valid")

    runs.create(spec)
    runs.start(spec.run_id)
    _save_state(folder, run_id=str(spec.run_id), reference_path=reference["path"])
    print(f"started   {spec.run_id}", flush=True)
    _wait(runs, spec.run_id)


def _mesh_for(state: dict) -> tuple[object, np.ndarray]:
    """The mesh the plugin will build, built here so a reference can be made."""
    from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin

    observations = np.loadtxt(state["observations_path"], delimiter=",", skiprows=1)
    receivers = observations[:, :3]
    topography = np.loadtxt(state["topography_path"], delimiter=",", skiprows=1)
    spec = _run_spec_skeleton(state)
    mesh = SimPEGGravity3DPlugin._build_mesh(spec, receivers, topography)
    return mesh, topography


def _reference_model(folder: object, state: dict) -> dict:
    """Basin fill over basement, as contrasts against the reduction density."""
    from scipy.spatial import cKDTree

    mesh, _ = _mesh_for(state)
    centres = np.asarray(mesh.cell_centers, dtype=float)  # type: ignore[attr-defined]
    granite = np.loadtxt(state["granite_path"], delimiter=",", skiprows=1)
    top = granite[cKDTree(granite[:, :2]).query(centres[:, :2])[1], 2]
    below = centres[:, 2] <= top
    contrast = np.where(
        below, BASEMENT_DENSITY - REDUCTION_DENSITY, BASIN_FILL_DENSITY - REDUCTION_DENSITY
    )
    path = Path(folder.imports_root) / "reference_density_contrast.npy"  # type: ignore[attr-defined]
    np.save(path, contrast)
    return {
        "path": path.as_posix(),
        "cells": int(centres.shape[0]),
        "basin": int((~below).sum()),
        "basement": int(below.sum()),
    }


def _mesh_spec() -> TreeMeshSpec:
    cell = QuantitySpec(value=list(MESH_CELL_M), quantity_type=QuantityType.LENGTH, unit="m")
    horizontal = QuantitySpec(value=[3_000.0, 3_000.0], quantity_type=QuantityType.LENGTH, unit="m")
    vertical = QuantitySpec(value=[3_000.0, 2_000.0], quantity_type=QuantityType.LENGTH, unit="m")
    return TreeMeshSpec(
        cell_size=cell,
        padding_distance=(horizontal, horizontal, vertical),
        depth_core=QuantitySpec(value=3_000.0, quantity_type=QuantityType.LENGTH, unit="m"),
        surface_padding_cells=SURFACE_PADDING_CELLS,
        receiver_padding_cells=RECEIVER_PADDING_CELLS,
        diagonal_balance=False,
    )


def _dataset() -> DatasetSpec:
    return DatasetSpec(
        name="Utah FORGE Phase 2C gravity, Witter's 323 stations",
        coordinate_convention=CoordinateConvention(crs=CRS),
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="mGal",
    )


def _run_spec_skeleton(state: dict) -> RunSpec:
    """Enough of a spec to build the mesh from, before the reference exists."""
    return RunSpec(
        schema_version="1.1",
        plugin_id="simpeg.pf.gravity3d",
        plugin_version="0.1.0",
        engine="simpeg",
        dataset=_dataset(),
        mesh=_mesh_spec(),
        parameters={
            "observations_path": state["observations_path"],
            "topography_path": state["topography_path"],
            "data_uncertainty": QuantitySpec(
                value=DATA_UNCERTAINTY_MGAL,
                quantity_type=QuantityType.GRAVITY_ACCELERATION,
                unit="mGal",
            ),
        },
    )


def _run_spec(
    record: object,
    state: dict,
    reference_path: str,
    petrophysical: bool = False,
    overrides: dict | None = None,
    label: str | None = None,
) -> RunSpec:
    dataset = _dataset()
    return RunSpec(
        schema_version="1.1",
        label=label,
        plugin_id="simpeg.pf.gravity3d",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        dataset=dataset,
        datasets=(
            DataChannelSpec(
                channel_id="gravity",
                dataset=dataset,
                observations_path=state["observations_path"],
                data_uncertainty=QuantitySpec(
                    value=DATA_UNCERTAINTY_MGAL,
                    quantity_type=QuantityType.GRAVITY_ACCELERATION,
                    unit="mGal",
                ),
            ),
        ),
        mesh=_mesh_spec(),
        physics=_physics(reference_path, petrophysical, overrides),
        parameters={
            "observations_path": state["observations_path"],
            "topography_path": state["topography_path"],
            "data_uncertainty": QuantitySpec(
                value=DATA_UNCERTAINTY_MGAL,
                quantity_type=QuantityType.GRAVITY_ACCELERATION,
                unit="mGal",
            ),
        },
    )


def _physics(
    reference_path: str, petrophysical: bool = False, overrides: dict | None = None
) -> dict:
    """Witter's controls, and where OFAG's defaults had to be departed from."""
    array = {
        "path": reference_path,
        "quantity_type": "density_contrast",
        "unit": "g/cm^3",
    }
    physics: dict = {
        **({"regularization": _petrophysical_regularization()} if petrophysical else {}),
        "model": {
            "initial_density_contrast": {
                "value": BASIN_FILL_DENSITY - REDUCTION_DENSITY,
                "quantity_type": "density_contrast",
                "unit": "g/cm^3",
            },
            "initial_model": array,
            "reference_model": array,
            "lower_bound": {
                "value": LOWEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY,
                "quantity_type": "density_contrast",
                "unit": "g/cm^3",
            },
            "upper_bound": {
                "value": HIGHEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY,
                "quantity_type": "density_contrast",
                "unit": "g/cm^3",
            },
        },
        "optimizer": {
            # Allow extra iterations for petrophysical clustering.
            "max_iterations": PGI_MAX_ITERATIONS if petrophysical else 20,
            "cg_max_iterations": 20,
        },
        "directives": {"target_chi_factor": 1.0},
    }
    # Shallow-merged, one section at a time, so a caller changing the directives does
    # not silently drop the model block it did not mention.
    for section, values in (overrides or {}).items():
        merged = dict(physics.get(section, {}))
        merged.update(values)
        physics[section] = merged
    return physics


# -- invert, petrophysically guided ----------------------------------------

#: The rocks this basin is made of, each with the measurement behind it.
#:
#: Witter inverted for a two-layer model, 2.42 over 2.65, and said in the same
#: paragraph why that is not the ground: the basin fill is not uniform, and the
#: basement is two rocks rather than one. His own words -- "we are aware that
#: the assumption of a uniform density of 2.42 g/cm3 in the basin fill is a
#: gross simplification". A smooth inversion cannot use that knowledge. A
#: petrophysically guided one can, and this is the whole reason to run it: the
#: four classes below are what his report and one well already establish, put
#: to the inversion instead of averaged away first.
#:
#: Stated as absolute densities and converted to contrasts against
#: REDUCTION_DENSITY where they are used.
PETROPHYSICAL_CLASSES = (
    # Cuttings from well 58-32 give basin fill falling from ~2.4 g/cm^3 at 660 m to ~2.0
    # at surface (Gwynn et al. 2018, quoted in Witter's report).
    ("shallow basin fill", 2.20, 0.06, "well 58-32 cuttings, 0-660 m"),
    # The neutron density log over 660-960 m, the interval immediately above basement.
    ("deep basin fill", 2.42, 0.05, "well 58-32 neutron density log, 660-960 m"),
    # 2.592 is the median of well 16A(78)-32's DPHI curve read back to a bulk density --
    # and it is not an independent measurement, though it was written down here as one
    # at first.
    (
        "granitic basement",
        2.592,
        0.03,
        "well 16A(78)-32 DPHI at its own 2.65 sandstone matrix -- not independent",
    ),
    # The other basement rock.
    ("dioritic basement", 2.80, 0.05, "well 58-32 neutron density log, dioritic intervals"),
)

#: How hard the classes pull, against the smoothness that is the rest of the
#: regularization.
#:
#: Not 1.0, which is SimPEG's default and is nearly nothing here. Left at None,
#: the smoothness weights are scaled by the square of the cell size, so on a
#: 50 m mesh they are some three orders of magnitude above a unit alpha_pgi and
#: the petrophysics is decoration: at 1.0 the recovered model clustered no
#: better than the smooth one -- half its cells more than a standard deviation
#: from every class it was given, which is what the smooth run does too.
#:
#: Chosen by the sweep in `sweep_pgi`, on the two things that can be measured
#: without reference to the published model: whether the inversion still fits,
#: and how much of it the declared rocks account for.
ALPHA_PGI = 1.0

PGI_MAX_ITERATIONS = 80

#: The smoothness weights that alpha_pgi is weighed against.
#:
#: SimPEG scales these by the square of the cell size when they are left unset,
#: which is the right default for a smooth inversion and the wrong one here: on
#: a 50 m mesh it puts the smoothness three orders of magnitude above a unit
#: alpha_pgi, and the classes never get a vote. SimPEG's own PGI examples set
#: them to one explicitly, against alpha_pgi of one, and that is what this does.
PGI_SMOOTHNESS_ALPHA: float | None = 1.0

#: Left unstated, so every class is equally likely before the data speaks.
#:
#: Proportions could be read off Witter's released model -- 63 per cent of it
#: sits at two values -- but that would be starting from his answer and then
#: reporting agreement with it.


def invert_pgi() -> None:
    """The same data and mesh, told what the rocks are."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if "observations_path" not in state:
        raise SystemExit("run `prepare` first")

    reference = state.get("reference_path") or _reference_model(folder, state)["path"]
    print(f"classes   {len(PETROPHYSICAL_CLASSES)}, as contrasts against {REDUCTION_DENSITY}")
    for name, density, spread, source in PETROPHYSICAL_CLASSES:
        print(f"  {name:20s} {density - REDUCTION_DENSITY:+.3f} +/- {spread:.3f}   {source}")

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    spec = _run_spec(
        record,
        state,
        reference,
        petrophysical=True,
        label=f"PGI, {len(PETROPHYSICAL_CLASSES)} classes, alpha_pgi {ALPHA_PGI:g}",
    )
    report_ = runs.validate(spec)
    if not report_.valid:
        for issue in report_.issues:
            print(f"  {issue.field}: {issue.message}")
        raise SystemExit("the run specification is not valid")

    runs.create(spec)
    runs.start(spec.run_id)
    _save_state(folder, pgi_run_id=str(spec.run_id), reference_path=reference)
    print(f"started   {spec.run_id}", flush=True)
    _wait(runs, spec.run_id)


def sweep_pgi() -> None:
    """Run the petrophysical inversion at several weights and report both costs."""
    global ALPHA_PGI, PGI_SMOOTHNESS_ALPHA
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if "observations_path" not in state:
        raise SystemExit("run `prepare` first")
    reference = state.get("reference_path") or _reference_model(folder, state)["path"]
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]

    original = (ALPHA_PGI, PGI_SMOOTHNESS_ALPHA)
    trials = [(weight, 1.0) for weight in (0.1, 1.0, 10.0, 100.0)]
    # The same ladder against SimPEG's cell-size-scaled smoothness, to show what the
    # default costs rather than only asserting it.
    trials += [(weight, None) for weight in (1.0, 100.0, 10_000.0)]
    print(
        f"{'alpha_pgi':>10}  {'smoothness':>10}  {'chi^2':>7}  "
        f"{'in a class':>10}  {'spread':>7}  {'at bound':>8}"
    )
    try:
        for weight, smoothness in trials:
            ALPHA_PGI, PGI_SMOOTHNESS_ALPHA = weight, smoothness
            label = "cell^2" if smoothness is None else f"{smoothness:g}"
            spec = _run_spec(
                record,
                state,
                reference,
                petrophysical=True,
                label=f"PGI sweep, alpha_pgi {weight:g}, smoothness {label}",
            )
            runs.create(spec)
            runs.start(spec.run_id)
            _wait(runs, spec.run_id, quiet=True)
            summary, model = _recovered(runs, str(spec.run_id))
            if model is None:
                print(f"{weight:10g}  {label:>10}  failed: {summary}")
                continue
            print(
                f"{weight:10g}  {label:>10}  "
                f"{summary.get('chi_squared', float('nan')):7.3f}  "
                f"{_explained_by_classes(model):9.1%}  {model.std():7.3f}  "
                f"{_at_bound(model).mean():7.1%}"
            )
    finally:
        ALPHA_PGI, PGI_SMOOTHNESS_ALPHA = original


def _explained_by_classes(model: np.ndarray) -> float:
    """The share of cells within one standard deviation of some declared class."""
    density = model + REDUCTION_DENSITY
    inside = np.zeros(density.size, dtype=bool)
    for _, value, spread, _ in PETROPHYSICAL_CLASSES:
        inside |= np.abs(density - value) <= spread
    return float(inside.mean())


def _nearest_class(density: np.ndarray) -> np.ndarray:
    """Which declared class each cell sits nearest, in units of that class's spread."""
    means = np.array([value for _, value, _, _ in PETROPHYSICAL_CLASSES])
    spreads = np.array([spread for _, _, spread, _ in PETROPHYSICAL_CLASSES])
    return np.asarray(
        np.argmin(np.abs(density[:, None] - means[None, :]) / spreads[None, :], axis=1)
    )


def _core_model(state: dict, values: np.ndarray) -> "CellModel":
    """The recovered model inside Witter's volume, with each cell's size beside it."""
    from discretize.utils import active_from_xyz

    from ofag.core.cell_model import CellModel

    mesh, topography = _mesh_for(state)
    active = np.asarray(active_from_xyz(mesh, topography), dtype=bool)
    whole = CellModel.on_active_cells(
        values,
        np.asarray(mesh.cell_centers, dtype=float),  # type: ignore[attr-defined]
        np.asarray(mesh.cell_volumes, dtype=float),  # type: ignore[attr-defined]
        active,
    )
    east, north, elevation = whole.centres[:, 0], whole.centres[:, 1], whole.centres[:, 2]
    inside = (
        (east >= VOLUME[0])
        & (east <= VOLUME[1])
        & (north >= VOLUME[2])
        & (north <= VOLUME[3])
        & (elevation >= ELEVATION_RANGE_M[0])
        & (elevation <= ELEVATION_RANGE_M[1])
    )
    return CellModel(whole.values[inside], whole.centres[inside], whole.volumes[inside])


def _report_classes(state: dict, values: np.ndarray) -> None:
    """How much of the modelled ground each declared rock class holds."""
    core = _core_model(state, values)
    assigned = _nearest_class(core.values + REDUCTION_DENSITY)
    uniform = 1.0 / len(PETROPHYSICAL_CLASSES)
    print(
        f"          {len(core.values):,} cells inside the model volume, "
        f"{core.cell_sizes.min():.0f}-{core.cell_sizes.max():.0f} m"
    )
    for index, (name, value, _, _) in enumerate(PETROPHYSICAL_CLASSES):
        share = core.volume_share(assigned == index)
        print(f"          {name:20s} {value:.3f}  prior {uniform:4.0%} -> {share:6.1%} by volume")


def _at_bound(model: np.ndarray) -> np.ndarray:
    at = np.isclose(model, LOWEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY, atol=1e-6)
    return at | np.isclose(model, HIGHEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY, atol=1e-6)


def _petrophysical_regularization() -> dict:
    return {
        "kind": "petrophysical",
        "alpha_pgi": ALPHA_PGI,
        "alpha_x": PGI_SMOOTHNESS_ALPHA,
        "alpha_y": PGI_SMOOTHNESS_ALPHA,
        "alpha_z": PGI_SMOOTHNESS_ALPHA,
        "petrophysical_classes": [
            {
                "name": name,
                "value": {
                    "value": density - REDUCTION_DENSITY,
                    "quantity_type": "density_contrast",
                    "unit": "g/cm^3",
                },
                "standard_deviation": {
                    "value": spread,
                    "quantity_type": "density_contrast",
                    "unit": "g/cm^3",
                },
                "source": source,
            }
            for name, density, spread, source in PETROPHYSICAL_CLASSES
        ],
    }


def _wait(runs: object, run_id: object, quiet: bool = False) -> None:
    """Attached, because the executor's children are daemons."""
    import time

    seen = 0
    started = time.monotonic()
    while True:
        record = runs.get(run_id)  # type: ignore[attr-defined]
        events = runs.events(run_id)  # type: ignore[attr-defined]
        if not quiet:
            for event in events[seen:]:
                detail = (
                    "  " + "  ".join(f"{k}={v:.5g}" for k, v in event.misfits.items())
                    if event.misfits
                    else ""
                )
                print(
                    f"  [{time.monotonic() - started:6.0f}s] {event.event_type}"
                    f" {event.iteration if event.iteration is not None else ''}"
                    f" {event.message}{detail}",
                    flush=True,
                )
        seen = len(events)
        if record.state.value in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"):
            if not quiet:
                print(f"finished  {record.state.value}  {record.error or ''}", flush=True)
            return
        time.sleep(10.0)


# -- report ----------------------------------------------------------------


#: What the case delivers, and which stored run is the deliverable.
#:
#: The magnetotellurics is the layered batch and not the 2D profile. The 2D
#: plugin works and its profile fits -- chi-squared 0.32 at the median -- and
#: it still does not agree with anything.
#:
#: This was recorded as static shift for a while and that was wrong on its
#: face: TE is the charge-insensitive mode, which is precisely why it was
#: chosen over TM (see MT2D_MODE). Static shift is TM's problem, and saying it
#: twice about two different modes is how a diagnosis becomes a label.
#:
#: Measured at the same twelve sites, sampled at eight depths each:
#:
#:     1D batch vs published 3D    +0.730
#:     2D TE    vs published 3D    -0.029
#:     2D TE    vs 1D batch        +0.103
#:     spread in log10 ohm.m -- 2D 0.44, 1D 0.83, published 1.20
#:
#: So the data carries the structure and the 2D does not recover it. It comes
#: back with a third of the published model's variation, and the flatness is
#: not the regularizer's: the run drove beta to 1.6e-3, effectively off, and
#: the model stayed smooth. That is TE doing what TE does -- it senses
#: conductance and is nearly blind to a resistive basement under conductive
#: fill, which is exactly the target here.
#:
#: The profile is therefore caught between its two modes. TM carries the
#: structure and is corrupted by static shift; TE is clean and cannot see the
#: structure. The layered batch agrees with the published model at +0.75 over
#: 67 sites, so that is what the case uses.
DELIVERABLES = (
    ("gravity, smooth", "run_id", "chi_squared"),
    ("gravity, petrophysical", "pgi_run_id", "chi_squared"),
    ("ground TEM, 1D batch", "tem_run_id", "chi_squared_median"),
    ("magnetotellurics, 1D batch", "mt_run_id", "chi_squared_median"),
)

#: Built, verified, and deliberately not part of the result. Named here so the
#: distinction is in the report rather than only in the commit message.
NOT_USED = (
    (
        "magnetotellurics, 2D profile",
        "mt2d_run_id",
        "fits at 0.32 and recovers a third of the published model's variation; "
        "TE cannot see a resistive basement, and TM is the mode static shift ruined",
    ),
)


def report() -> None:
    """Every method this case delivers, and whether it is finished."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]

    print(f"{'deliverable':30s} {'state':10s} {'misfit':>9s}  run")
    complete = True
    for label, key, metric in DELIVERABLES:
        run_id = state.get(key)
        if not run_id:
            print(f"{label:30s} {'MISSING':10s} {'-':>9s}  run the stage that makes it")
            complete = False
            continue
        records = {str(item.spec.run_id): item for item in runs.list_runs()}
        item = records.get(str(run_id))
        if item is None:
            print(f"{label:30s} {'LOST':10s} {'-':>9s}  {run_id}")
            complete = False
            continue
        result = runs.result(item.spec.run_id)
        value = result.summary.get(metric) if result else None
        shown = f"{value:9.3f}" if isinstance(value, int | float) else f"{'-':>9s}"
        print(f"{label:30s} {str(item.state):10s} {shown}  {run_id}")
        complete = complete and str(item.state) == "SUCCEEDED" and value is not None

    for label, key, why in NOT_USED:
        run_id = state.get(key)
        print(f"{label:30s} {'not used':10s} {'-':>9s}  {why}")
        if run_id:
            print(f"{'':30s} {'':10s} {'':>9s}  {run_id}")

    doi = state.get("doi_run_ids") or {}
    stored = [str(item) for group in doi.values() for item in group]
    if stored:
        print(
            f"{'depth of investigation (F011)':30s} {'kept':10s} {'-':>9s}  "
            f"{len(stored)} runs: two references, weighted and unweighted"
        )

    # Not a run: built from the four above rather than inverted, which is the whole
    # point of it.
    built = state.get("geological_model_path")
    print(
        f"{'geological model':30s} "
        + (
            f"{'built':10s} {'-':>9s}  4 units, each from the one method that resolves its depth"
            if built
            else f"{'MISSING':10s} {'-':>9s}  run build_model"
        )
    )
    if not built:
        complete = False

    records = {str(item.spec.run_id): item for item in runs.list_runs()}
    named = {str(state.get(key)) for _, key, _ in DELIVERABLES}
    named |= {str(state.get(key)) for _, key, _ in NOT_USED} | set(stored)
    extra = sorted(set(records) - named)
    print()
    if extra:
        print(f"{len(extra)} stored runs this report does not name:")
        for run_id in extra:
            print(f"  {run_id}  {records[run_id].spec.label or records[run_id].spec.plugin_id}")
        print("  (`ofag delete <run-id>` removes one)")
    else:
        print("every stored run is named above")
    print()
    print("case 1 is complete" if complete else "case 1 is NOT complete")


def compare() -> None:
    """Both recovered models against Witter's, on his cells."""
    import pandas as pd
    from discretize.utils import active_from_xyz
    from scipy.spatial import cKDTree

    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    mesh, topography = _mesh_for(state)
    centres = np.asarray(mesh.cell_centers, dtype=float)  # type: ignore[attr-defined]
    # The recovered array holds the cells below topography and nothing else, so it has
    # to be put back on the whole mesh before anything can be looked up in it.
    active_cells = np.asarray(active_from_xyz(mesh, topography), dtype=bool)

    published = pd.read_csv(GRAVITY / "published_model.csv")
    theirs = published["Density_gcm3"].to_numpy()
    their_centres = published[["X_UTMNAD83z12_m", "Y_UTMNAD83z12_m", "Z_Elevation_m"]].to_numpy()
    nearest = cKDTree(centres).query(their_centres)[1]

    print(f"published {theirs.size:,} cells, {theirs.min():.3f} to {theirs.max():.3f} g/cm^3")
    print(
        f"          {len(np.unique(theirs))} distinct values, "
        f"{_share_at_modes(theirs):.0%} of cells at two of them"
    )
    print()
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    for label, key in (("smooth", "run_id"), ("PGI", "pgi_run_id")):
        run_id = state.get(key)
        if run_id is None:
            print(f"{label:9s} not run yet")
            continue
        summary, model = _recovered(runs, run_id)
        if model is None:
            print(f"{label:9s} no model: {summary}")
            continue
        on_mesh = np.full(centres.shape[0], np.nan)
        on_mesh[active_cells] = model
        ours = on_mesh[nearest] + REDUCTION_DENSITY
        overlap = np.isfinite(ours)
        mine, theirs_here = ours[overlap], theirs[overlap]
        difference = mine - theirs_here
        # A model resting on its bounds is not a recovered density, it is the solver
        # saying it was asked for more than the data can give.
        at_bound = np.isclose(model, LOWEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY, atol=1e-6)
        at_bound |= np.isclose(model, HIGHEST_PLAUSIBLE_DENSITY - REDUCTION_DENSITY, atol=1e-6)
        print(
            f"{label:9s} {mine.min():.3f} to {mine.max():.3f} g/cm^3 over "
            f"{overlap.sum():,} of their cells, "
            f"{len(np.unique(np.round(mine, 3)))} distinct to a thousandth, "
            f"{at_bound.mean():.1%} of cells at a bound"
        )
        print(
            f"          against published: median {np.median(difference):+.3f}, "
            f"RMS {np.sqrt(np.mean(difference**2)):.3f} g/cm^3, "
            f"correlation {np.corrcoef(mine, theirs_here)[0, 1]:+.3f}"
        )
        for name, value in summary.items():
            if name in ("chi_squared", "residual_rms_mgal", "iterations"):
                print(f"          {name}: {value}")
        if key == "pgi_run_id":
            _report_classes(state, model)
        print()


def _share_at_modes(values: np.ndarray, modes: int = 2) -> float:
    counts = np.unique(np.round(values, 3), return_counts=True)[1]
    return float(np.sort(counts)[-modes:].sum() / values.size)


def _recovered(runs: object, run_id: str) -> tuple[dict, np.ndarray | None]:
    """The model a finished run produced, read back through its artifacts."""
    from uuid import UUID

    identifier = UUID(run_id)
    result = runs.result(identifier)  # type: ignore[attr-defined]
    if result is None:
        return {"state": "no result"}, None
    # `relative_path` is relative to the artifact root and already names the run, so
    # joining it to the run directory would name the run twice.
    root = Path(runs.artifact_root)  # type: ignore[attr-defined]
    for artifact in result.artifacts:
        if artifact.artifact_type == "recovered_model":
            path = root / artifact.relative_path
            return dict(result.summary), np.load(path, allow_pickle=False)
    return dict(result.summary), None


# -- transient electromagnetics --------------------------------------------

TEM = CASE / "tem"

#: The layers every sounding is solved on, and why these.
#:
#: Thirty layers thickening downward from 3 m. A TEM decay carries information
#: over about three decades of time and resolves nothing like thirty
#: independent layers; the fine discretization is there so the smoothness
#: regularization, not the layer edges, decides where the model changes. The
#: base is set past the depth the latest gate can see, so the deepest layer is
#: a boundary condition rather than a result.
TEM_LAYERS = 30
TEM_FIRST_LAYER_M = 3.0
TEM_LAST_LAYER_M = 400.0

#: The resistivities a halfspace is searched over, to start each sounding from
#: its own best one rather than from a single guess for the survey.
#:
#: Not a refinement. Started at a flat 100 ohm.m the batch came back with a
#: median recovered resistivity of exactly 100 -- the model had not moved --
#: and a best residual of 45 per cent, while a one-parameter halfspace found
#: by brute force reached 11.7. A thirty-layer model contains every halfspace,
#: so it cannot honestly do worse than one; the optimizer was failing, and it
#: was failing because it began too far away with a misfit of 1e8.
TEM_HALFSPACE_SEARCH_OHM_M = (1.0, 3_000.0, 30)
TEM_BOUNDS_OHM_M = (1.0, 10_000.0)

#: A floor under the measured uncertainty, as a fraction of each gate's value.
#:
#: The repeats measure how well the instrument reproduces itself -- 0.17 per
#: cent of the value -- and that is a real measurement of the wrong quantity
#: (F018). What the residual has to be divided by is how closely a layered model
#: of this ground can be expected to describe it, which the repeats say nothing
#: about and which is larger by two orders of magnitude. Fitting to 0.17 per
#: cent drove the misfit to 1e8 and broke the line search.
#:
#: Five per cent is declared, not derived. It is the figure ground TEM practice
#: uses for a system whose geometry, gate timing and turn-off are known but not
#: perfectly, and the point of declaring it is that it does not move: the
#: version before this one floored each sounding at the residual its own best
#: halfspace left, which is 11.7 per cent at the median and looks measured. It
#: is not. A tolerance taken from how badly a model fits will always be met,
#: and it was: chi-squared came back at 0.44 with every sounding stopping after
#: one iteration, still sitting on the halfspace it started from. F012 again.
TEM_UNCERTAINTY_FLOOR = 0.05

#: Which of the four configurations each site is inverted from.
#:
#: The low-moment 240 Hz sweeps on the large 1400 m2 coil: the moment that
#: resolves the near surface, on the receiver with the signal to see it. The
#: other three are imported and kept, and inverting the pair jointly is the
#: obvious next step -- this takes one so that what is compared between sites
#: is one instrument rather than four.
TEM_CONFIGURATION = "40x40m-1400m2-240Hz"


def import_tem() -> None:
    """Stack the 68 soundings, and report what the instrument threw away."""
    from ofag.services.tem_import import TemImportRequest, TemImportService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    imported = TemImportService(
        import_root=Path(folder.imports_root)  # type: ignore[attr-defined]
    ).import_usf_directory(
        TemImportRequest(
            source_directory=str(TEM),
            coordinate_convention=CoordinateConvention(crs=CRS),
        )
    )
    rejected = imported.gates_rejected_by_instrument / max(1, imported.gates_read)
    sites = {curve.sounding_id for curve in imported.curves}
    print(f"tem       {imported.sweeps_read:,} sweeps at {len(sites)} sites")
    print(
        f"          {imported.sweeps_rejected_as_noise:,} recorded with the transmitter off, "
        f"{rejected:.0%} of gates rejected by the instrument"
    )
    print(
        f"          {imported.gates_dropped_for_too_few_repeats:,} gates dropped for too few "
        f"repeats, {imported.gates_dropped_as_too_early:,} as inside the turn-off; "
        f"{len(imported.curves)} curves stacked"
    )
    chosen = [c for c in imported.curves if c.configuration_id == TEM_CONFIGURATION]
    relative = np.concatenate([np.abs(c.uncertainty / c.values) for c in chosen])
    print(
        f"          {TEM_CONFIGURATION}: {len(chosen)} soundings, measured uncertainty "
        f"median {np.median(relative):.2%} of the value"
    )
    _save_state(
        folder,
        tem_dataset_id=str(imported.dataset_id),
        tem_curves=[
            {
                "sounding_id": c.sounding_id,
                "observations_path": c.observations_path,
                "easting_m": c.easting_m,
                "northing_m": c.northing_m,
                "elevation_m": c.elevation_m,
                "loop_radius_m": c.loop_radius_m,
                "ramp_time_s": c.ramp_time_s,
                "times_s": c.times_s.tolist(),
                "uncertainty": c.uncertainty.tolist(),
            }
            for c in chosen
        ],
    )


def _observed(curve: dict) -> np.ndarray:
    """The stacked decay a curve points at, read back from its own file."""
    table = np.genfromtxt(curve["observations_path"], delimiter=",", names=True)
    return np.asarray(table["magnetic_flux_density_time_derivative_t_s"], dtype=float)


def _tem_waveform(tdem: object, curve: dict) -> object:
    """The transmitter turn-off the file declares, as SimPEG wants it."""
    import numpy as np

    ramp = float(curve["ramp_time_s"])
    if ramp <= 0.0:
        return tdem.sources.StepOffWaveform()  # type: ignore[attr-defined]
    return tdem.sources.PiecewiseLinearWaveform(  # type: ignore[attr-defined]
        np.array([-ramp, 0.0]), np.array([1.0, 0.0])
    )


def _tem_waveform_spec(curve: dict) -> dict:
    """The same turn-off as `_tem_waveform`, written for a run spec."""
    ramp = float(curve["ramp_time_s"])
    if ramp <= 0.0:
        return {"waveform": "step_off"}
    return {
        "waveform": "piecewise_linear",
        "waveform_times": {"value": [-ramp, 0.0], "quantity_type": "time", "unit": "s"},
        "waveform_current_fractions": [1.0, 0.0],
    }


def _best_halfspace(curve: dict, thicknesses: list[float]) -> tuple[float, float]:
    """The halfspace that fits this sounding best, and the residual it leaves."""
    import numpy as np
    from simpeg import maps
    from simpeg.electromagnetics import time_domain as tdem

    table = np.genfromtxt(curve["observations_path"], delimiter=",", names=True)
    times = np.asarray(table["time_s"], dtype=float)
    observed = np.asarray(table["magnetic_flux_density_time_derivative_t_s"], dtype=float)
    receiver = tdem.receivers.PointMagneticFluxTimeDerivative(
        np.array([[0.0, 0.0, 0.0]]), times, orientation="z"
    )
    source = tdem.sources.CircularLoop(
        [receiver],
        location=np.array([0.0, 0.0, 0.0]),
        radius=curve["loop_radius_m"],
        current=1.0,
        waveform=_tem_waveform(tdem, curve),
    )
    layers = np.asarray(thicknesses, dtype=float)
    simulation = tdem.Simulation1DLayered(
        survey=tdem.Survey([source]),
        thicknesses=layers,
        sigmaMap=maps.IdentityMap(nP=layers.size + 1),
    )
    low, high, steps = TEM_HALFSPACE_SEARCH_OHM_M
    best = (float(low), float("inf"))
    for resistivity in np.logspace(np.log10(low), np.log10(high), int(steps)):
        predicted = simulation.dpred(np.full(layers.size + 1, 1.0 / resistivity))
        residual = float(np.median(np.abs(predicted - observed) / np.abs(observed)))
        if residual < best[1]:
            best = (float(resistivity), residual)
    return best


def invert_tem() -> None:
    """One 1D conductivity model per sounding, all in one batch run."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    curves = state.get("tem_curves")
    if not curves:
        raise SystemExit("run `import_tem` first")

    # The plugin asks for a manifest of what the batch contains, as the record of which
    # soundings a stitched section was built from.
    manifest = Path(folder.imports_root) / "tem_batch_manifest.json"  # type: ignore[attr-defined]
    manifest.write_text(
        json.dumps(
            {
                "configuration": TEM_CONFIGURATION,
                "soundings": [
                    {
                        "sounding_id": curve["sounding_id"],
                        "observations_path": curve["observations_path"],
                        "easting_m": curve["easting_m"],
                        "northing_m": curve["northing_m"],
                        "elevation_m": curve["elevation_m"],
                    }
                    for curve in curves
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Each sounding's own best halfspace, which is where the batch starts.
    layers = _tem_layers()
    residuals = []
    for curve in curves:
        resistivity, residual = _best_halfspace(curve, layers)
        curve["halfspace_ohm_m"] = resistivity
        curve["halfspace_residual"] = residual
        residuals.append(residual)
        curve["uncertainty"] = [
            max(abs(value), TEM_UNCERTAINTY_FLOOR * abs(reference))
            for value, reference in zip(curve["uncertainty"], _observed(curve), strict=True)
        ]
    start_ohm_m = float(np.median([curve["halfspace_ohm_m"] for curve in curves]))
    print(
        f"halfspace best fit {start_ohm_m:.0f} ohm.m at the median, leaving "
        f"{np.median(residuals):.1%} residual"
    )
    print(
        f"uncertainty floored at {TEM_UNCERTAINTY_FLOOR:.0%} of each value, "
        f"over a measured repeatability of 0.17%"
    )

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    spec = _tem_run_spec(record, curves, manifest, start_ohm_m)
    report_ = runs.validate(spec)
    if not report_.valid:
        for issue in report_.issues:
            print(f"  {issue.field}: {issue.message}")
        raise SystemExit("the TEM run specification is not valid")
    runs.create(spec)
    runs.start(spec.run_id)
    _save_state(folder, tem_run_id=str(spec.run_id))
    print(f"started   {spec.run_id}  ({len(curves)} soundings)", flush=True)
    _wait(runs, spec.run_id)


def _tem_layers() -> list[float]:
    """Thicknesses growing geometrically, which is how a TEM decay resolves."""
    ratio = (TEM_LAST_LAYER_M / TEM_FIRST_LAYER_M) ** (1.0 / (TEM_LAYERS - 1))
    return [TEM_FIRST_LAYER_M * ratio**index for index in range(TEM_LAYERS)]


def _tem_run_spec(
    record: object, curves: list[dict], manifest: Path, start_ohm_m: float
) -> RunSpec:
    def length(value: object) -> dict:
        return {"value": value, "quantity_type": "length", "unit": "m"}

    def conductivity(ohm_m: float) -> dict:
        return {"value": 1.0 / ohm_m, "quantity_type": "conductivity", "unit": "S/m"}

    soundings = []
    for curve in curves:
        soundings.append(
            {
                "sounding_id": curve["sounding_id"],
                "observations_path": curve["observations_path"],
                # Where the sounding stands.
                "station_location": length(
                    [curve["easting_m"], curve["northing_m"], curve["elevation_m"]]
                ),
                "data_uncertainty": {
                    # The scatter of the repeats at that site, gate by gate.
                    "value": [abs(u) for u in curve["uncertainty"]],
                    "quantity_type": "magnetic_flux_density_time_derivative",
                    "unit": "T/s",
                },
                "system": {
                    "times": {
                        "value": curve["times_s"],
                        "quantity_type": "time",
                        "unit": "s",
                    },
                    # The loop lies on the ground and the receiver sits at its centre,
                    # which is what a fixed-loop sounding is.
                    "source_location": length([0.0, 0.0, 0.0]),
                    "receiver_location": length([0.0, 0.0, 0.0]),
                    "source_radius": length(curve["loop_radius_m"]),
                    # Use one amp for current-normalized data.
                    "source_current": {
                        "value": 1.0,
                        "quantity_type": "electric_current",
                        "unit": "A",
                    },
                    "receiver_quantity": "magnetic_flux_density_time_derivative",
                    **_tem_waveform_spec(curve),
                },
            }
        )
    return RunSpec(
        schema_version="1.1",
        plugin_id="simpeg.aem.batch_tdem1d",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        dataset=DatasetSpec(
            name="Utah FORGE ground TEM",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
            units="T/s",
        ),
        label=f"TEM batch, {len(curves)} soundings, {TEM_CONFIGURATION}",
        parameters={"batch_manifest_path": str(manifest)},
        physics={
            "earth": {"layer_thicknesses": length(_tem_layers())},
            "regularization": {"alpha_s": 0.01, "alpha_z": 1.0},
            "model": {
                "initial_conductivity": conductivity(start_ohm_m),
                "lower_bound": conductivity(TEM_BOUNDS_OHM_M[1]),
                "upper_bound": conductivity(TEM_BOUNDS_OHM_M[0]),
            },
            # Forty, not fifteen.
            "optimizer": {"max_iterations": 40},
            # Cool every third iteration rather than every one.
            "beta": {"cooling_rate": 3},
            "directives": {"target_chi_factor": 1.0},
            "soundings": soundings,
        },
    )


# -- magnetotellurics -------------------------------------------------------

MT = CASE / "mt" / "edi"

#: Layers for the magnetotelluric inversion, and why they differ from the TEM's.
#:
#: The two methods see different depths. A TEM decay out to 7 ms over a basin
#: of a few tens of ohm-metres is a few hundred metres of ground; these
#: soundings reach 0.0008 Hz, which is kilometres. So the layers start coarser
#: and go far deeper, and the deepest is a halfspace holding the boundary
#: rather than a result.
MT_LAYERS = 35
MT_FIRST_LAYER_M = 20.0
MT_LAST_LAYER_M = 5_000.0

#: The apparent resistivity of the survey, taken as the starting model: 8.7
#: ohm.m is the median over its 122 sites. Roosevelt Hot Springs is a producing
#: geothermal field and the ground under it is genuinely conductive, so a
#: hundred ohm-metres -- the obvious guess anywhere else -- would start the
#: inversion an order of magnitude out.
MT_START_OHM_M = 9.0
MT_BOUNDS_OHM_M = (0.3, 10_000.0)

#: How much phase-tensor skew a site may have before it is refused, in degrees
#: (F014, F022). Three is the convention. The quantity is the only one a tensor
#: offers that galvanic distortion cannot alter, which is why the screen moved
#: onto it from |Zxy + Zyx| / |Zxy - Zyx|.
MT_MAX_SKEW_DEGREES = 3.0

#: A floor under the measured impedance uncertainty.
#:
#: The uncertainty is measured from the spectra, not declared: 14.2 per cent
#: of the impedance at the median across the survey. This case first declared
#: a flat 5 per cent, the inversion fit to twenty, and chi-squared came out at
#: 17 -- which is the point at which one is tempted to widen the declaration
#: until the number behaves.
MT_MINIMUM_UNCERTAINTY = 0.02

#: Which scalar the impedance tensor is reduced to before it is inverted.
#:
#: The first version of this averaged the two off-diagonals, on the reasoning
#: that they are two estimates of one quantity. Fitted site by site with the
#: regularization switched off -- so that the number is the best a layered
#: model can do rather than the best this inversion found -- the four
#: candidates come out as chi-squared 3.2 for xy, 8.0 for the determinant,
#: 10.1 for yx and 11.0 for their average, at the median over six sites.
#: The average is the worst of the four, because averaging two polarisations
#: that structure has pulled apart makes a curve neither of them is (F015).
MT_IMPEDANCE_COMPONENT = "xy"


def import_mt() -> None:
    """Read the 122 sites, and refuse the ones a layered model cannot describe."""
    import numpy as np

    from ofag.services.mt_import import MtImportRequest, MtImportService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    imported = MtImportService(
        import_root=Path(folder.imports_root)  # type: ignore[attr-defined]
    ).import_edi_directory(
        MtImportRequest(
            source_directory=str(MT),
            coordinate_convention=CoordinateConvention(crs=CRS),
            maximum_phase_tensor_skew_degrees=MT_MAX_SKEW_DEGREES,
            minimum_relative_uncertainty=MT_MINIMUM_UNCERTAINTY,
            impedance_component=MT_IMPEDANCE_COMPONENT,
        )
    )
    rho = np.array([np.median(s.apparent_resistivity_ohm_m) for s in imported.soundings])
    print(f"mt        {imported.files_read} EDIs read, {len(imported.soundings)} sites kept")
    print(f"          tensor reduced to its {imported.impedance_component} impedance")
    print(
        f"          {len(imported.refused_as_three_dimensional)} refused as three "
        f"dimensional (phase-tensor skew above {MT_MAX_SKEW_DEGREES:.0f} deg)"
    )
    skew = np.array([float(np.median(np.abs(s.skew_degrees))) for s in imported.soundings])
    ellipticity = np.array([float(np.median(s.ellipticity)) for s in imported.soundings])
    print(
        f"          skew median {np.median(skew):.1f} deg, ellipticity median "
        f"{np.median(ellipticity):.2f} -- zero would be layered"
    )
    print(
        f"          apparent resistivity median {np.median(rho):.1f} ohm.m "
        f"(5-95%: {np.percentile(rho, 5):.1f} - {np.percentile(rho, 95):.1f})"
    )
    inside = [
        s
        for s in imported.soundings
        if VOLUME[0] <= s.easting_m <= VOLUME[1] and VOLUME[2] <= s.northing_m <= VOLUME[3]
    ]
    print(f"          {len(inside)} of them inside the gravity model volume")
    relative = np.array(
        [float(np.median(s.uncertainty_ohm / np.abs(s.impedance_ohm))) for s in imported.soundings]
    )
    print(
        f"          measured uncertainty median {np.median(relative):.1%} of the impedance "
        f"(5-95%: {np.percentile(relative, 5):.1%} - {np.percentile(relative, 95):.1%})"
    )
    _save_state(
        folder,
        mt_dataset_id=str(imported.dataset_id),
        mt_sites=[
            {
                "site_id": s.sounding_id,
                "observations_path": s.observations_path,
                "easting_m": s.easting_m,
                "northing_m": s.northing_m,
                "elevation_m": s.elevation_m,
            }
            for s in imported.soundings
        ],
    )


def invert_mt() -> None:
    """One layered conductivity model per site."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    sites = state.get("mt_sites")
    if not sites:
        raise SystemExit("run `import_mt` first")

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    spec = _mt_run_spec(record, sites)
    report_ = runs.validate(spec)
    if not report_.valid:
        for issue in report_.issues:
            print(f"  {issue.field}: {issue.message}")
        raise SystemExit("the magnetotelluric run specification is not valid")
    runs.create(spec)
    runs.start(spec.run_id)
    _save_state(folder, mt_run_id=str(spec.run_id))
    print(f"started   {spec.run_id}  ({len(sites)} sites)", flush=True)
    _wait(runs, spec.run_id)


#: The published Phase 3 inversion, as a cell-centre list of resistivities.
#:
#: A 3D inversion of the same 122 sites, by the contractor who recorded them.
#: It is the only thing available that can say whether a layered model of this
#: survey means anything, and it is a model rather than data -- so it settles
#: nothing on its own, and a disagreement is two models disagreeing.
MT_PUBLISHED_MODEL = CASE / "mt" / "FRG200614_mdl17_cellcenter.dat"

#: How near a published cell has to be to count as the same ground.
MT_MATCH_RADIUS_M = 250.0


def compare_mt() -> None:
    """The layered models against the published three-dimensional one."""
    from scipy.spatial import cKDTree

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    run_id = state.get("mt_run_id")
    if not run_id:
        raise SystemExit("run `invert_mt` first")
    run_dir = Path(folder.runs_root) / str(run_id)  # type: ignore[attr-defined]
    section = np.load(run_dir / "stitched_conductivity_section.npz")
    summary = np.genfromtxt(
        run_dir / "site_summary.csv", delimiter=",", names=True, dtype=None, encoding="utf-8"
    )
    if not MT_PUBLISHED_MODEL.exists():
        raise SystemExit(f"{MT_PUBLISHED_MODEL} is missing")

    published = np.loadtxt(MT_PUBLISHED_MODEL, skiprows=3)
    northing, easting, elevation, resistivity = published.T
    keep = resistivity > 0
    tree = cKDTree(np.column_stack([easting[keep], northing[keep], elevation[keep]]))
    published_rho = resistivity[keep]

    # Both models sampled at the same points: the layer centres of each site, turned
    # into elevations so that topography does not shift one against the other.
    tops = section["layer_top_depth_m"]
    centres = np.r_[(tops[:-1] + tops[1:]) / 2.0, tops[-1] + (tops[-1] - tops[-2]) / 2.0]
    ours = 1.0 / section["conductivity_s_m"]
    rows = []
    for index in range(ours.shape[0]):
        depths = centres[centres <= MT_LAST_LAYER_M]
        points = np.column_stack(
            [
                np.full(depths.size, section["easting_m"][index]),
                np.full(depths.size, section["northing_m"][index]),
                section["elevation_m"][index] - depths,
            ]
        )
        distance, nearest = tree.query(points)
        inside = distance <= MT_MATCH_RADIUS_M
        if inside.sum() < 5:
            continue
        rows.append(
            (
                float(summary["chi_squared"][index]),
                np.log10(ours[index, : depths.size][inside]),
                np.log10(published_rho[nearest][inside]),
            )
        )
    if not rows:
        raise SystemExit("no site has published cells within the match radius")

    chi = np.array([row[0] for row in rows])
    mine = np.concatenate([row[1] for row in rows])
    theirs = np.concatenate([row[2] for row in rows])
    print(
        f"compare   {len(rows)} sites, {mine.size} sampled depths within {MT_MATCH_RADIUS_M:.0f} m"
    )
    print(f"          correlation in log resistivity {np.corrcoef(mine, theirs)[0, 1]:+.3f}")
    print(
        f"          median ours {10 ** np.median(mine):.1f} ohm.m against "
        f"theirs {10 ** np.median(theirs):.1f}"
    )
    print(f"          RMS difference {np.sqrt(np.mean((mine - theirs) ** 2)):.2f} decades")
    fitted = chi <= MT_ACCEPTABLE_CHI
    print(
        f"          {int(fitted.sum())} of {chi.size} sites fit to chi-squared "
        f"{MT_ACCEPTABLE_CHI:.0f} or better"
    )
    if fitted.any():
        subset = [rows[index] for index in np.flatnonzero(fitted)]
        a = np.concatenate([row[1] for row in subset])
        b = np.concatenate([row[2] for row in subset])
        print(f"          those alone correlate {np.corrcoef(a, b)[0, 1]:+.3f}")


#: What counts as a site a layered model described, rather than one it merely
#: returned a profile for. Five is loose and is deliberately loose: nothing is
#: gained by choosing a number that makes the count nicer.
MT_ACCEPTABLE_CHI = 5.0


# -- the two-dimensional inversion ------------------------------------------

#: How far a site may sit off the profile and still be on it, in metres.
#:
#: A 2D inversion puts every site on one line, and a site 2 km off it is being
#: told it sits somewhere it does not. The corridor is the whole judgement in
#: this stage: it trades sites against honesty, and the sites at the ends of
#: the line are the ones to distrust first.
MT2D_CORRIDOR_M = 2_000.0

#: Which mode is inverted, measured rather than chosen.
#:
#: TM was the default here first, on the usual argument that its currents cross
#: the structure so it is less disturbed by conductors off the line. On this
#: profile it does not invert at all: chi-squared stops at 422 against 410 for
#: the best uniform halfspace, which is a model with 5,580 free cells failing
#: to beat one parameter.
#:
#: The reason is static shift and the evidence is specific. Each site's TM
#: curve fits a *layered* model to a median chi-squared of 0.01 -- but five of
#: the twelve reach it only with a surface layer pinned at the 10,000 ohm.m
#: bound, which is a fitting device absorbing a site's own offset rather than
#: ground. A single section cannot give twelve sites twelve different offsets,
#: and TM is the mode those offsets live in. Forward modelling a section built
#: by interpolating those twelve layered models gives chi-squared 650, worse
#: than the halfspace, which says the same thing from the other side.
#:
#: TE is the charge-insensitive mode and it converges: chi-squared 0.32 at the
#: median with ten of twelve sites inside two.
MT2D_MODE = "te"

#: How many frequencies per decade the 2D inversion is given.
#:
#: The instrument recorded eleven per decade, 61 over 5.4 decades, and a 2D
#: inversion does not resolve anything at that spacing -- adjacent frequencies
#: see almost the same ground, so they add solves without adding constraint.
#: One forward model of the full band takes 62 seconds against 16 for a quarter
#: of it, and a Gauss-Newton iteration is many forwards; at 61 the run does not
#: finish, which is not a defensible reason to decimate but is how it came up.
#: The defensible reason is that four per decade is what 2D practice uses.
MT2D_FREQUENCIES_PER_DECADE = 4.0

MT2D_CELL_M = 200.0
MT2D_CORE_DEPTH_M = 6_000.0
MT2D_CORE_MARGIN_M = 3_000.0
MT2D_MAX_ITERATIONS = 20


def invert_mt2d() -> None:
    """One conductivity section along a profile across the regional strike."""
    from ofag.formats.edi import (
        impedance_uncertainty_ohm,
        phase_tensor_invariants,
        read_edi,
        rotate,
        scalar_impedance,
        scalar_uncertainty_ohm,
    )
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    sites = state.get("mt_sites")
    if not sites:
        raise SystemExit("run `import_mt` first")

    # The strike the phase tensor reports, averaged the right way: it is modulo 90, so
    # the whole circle is four strikes and the angle is quadrupled to average and
    # quartered to read back.
    stations = {site["site_id"]: read_edi(_edi_for(site["site_id"])) for site in sites}
    tensors = {name: station.impedance(remote=True) for name, station in stations.items()}
    strikes = np.array(
        [
            float(np.median(phase_tensor_invariants(tensors[site["site_id"]]).strike_degrees))
            for site in sites
        ]
    )
    quadrupled = np.exp(1j * np.radians(strikes * 4.0))
    strike = float(np.degrees(np.angle(np.mean(quadrupled))) / 4.0 % 90.0)
    concentration = float(np.abs(np.mean(quadrupled)))
    print(f"strike    {strike:.0f} deg from the phase tensor, concentration {concentration:.2f}")

    easting = np.array([site["easting_m"] for site in sites])
    northing = np.array([site["northing_m"] for site in sites])
    centre = np.array([easting.mean(), northing.mean()])
    across = np.radians(strike + 90.0)
    direction = np.array([np.sin(across), np.cos(across)])
    normal = np.array([-direction[1], direction[0]])
    offset = (easting - centre[0]) * normal[0] + (northing - centre[1]) * normal[1]
    distance = (easting - centre[0]) * direction[0] + (northing - centre[1]) * direction[1]
    on_line = np.abs(offset) <= MT2D_CORRIDOR_M
    span = float(distance[on_line].max() - distance[on_line].min()) if on_line.any() else 0.0
    print(
        f"profile   bearing {np.degrees(across) % 360:.0f} deg, "
        f"{int(on_line.sum())} of {len(sites)} sites within {MT2D_CORRIDOR_M:.0f} m, "
        f"spanning {span / 1e3:.1f} km"
    )
    if int(on_line.sum()) < 5:
        raise SystemExit("too few sites on the profile to invert")

    directory = Path(folder.imports_root) / "mt2d"  # type: ignore[attr-defined]
    directory.mkdir(parents=True, exist_ok=True)
    component = "yx" if MT2D_MODE == "tm" else "xy"
    chosen = []
    for index in np.flatnonzero(on_line):
        site = sites[int(index)]
        station = stations[site["site_id"]]
        tensor = tensors[site["site_id"]]
        turned = rotate(tensor, strike)
        # A rotation mixes the tensor elements, so it mixes their errors too.
        error = impedance_uncertainty_ohm(station, tensor)
        angle = np.radians(strike)
        squared = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]]) ** 2
        mixed = np.sqrt(squared @ error**2 @ squared.T)
        impedance = scalar_impedance(turned, component)
        uncertainty = np.maximum(
            np.abs(scalar_uncertainty_ohm(np.abs(mixed), component)),
            MT_MINIMUM_UNCERTAINTY * np.abs(impedance),
        )
        order = _decimated(station.frequencies_hz, MT2D_FREQUENCIES_PER_DECADE)
        lines = ["frequency_hz,impedance_real_ohm,impedance_imag_ohm,uncertainty_ohm"]
        lines += [
            f"{station.frequencies_hz[i]:.9e},{impedance[i].real:.9e},"
            f"{impedance[i].imag:.9e},{uncertainty[i]:.9e}"
            for i in order
        ]
        path = directory / f"{site['site_id']}.csv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        chosen.append(
            {
                "site_id": site["site_id"],
                "observations_path": path.as_posix(),
                "distance_m": float(distance[index]),
                "mode": MT2D_MODE,
            }
        )

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    spec = _mt2d_run_spec(record, chosen)
    report_ = runs.validate(spec)
    if not report_.valid:
        for issue in report_.issues:
            print(f"  {issue.field}: {issue.message}")
        raise SystemExit("the 2D magnetotelluric run specification is not valid")
    runs.create(spec)
    runs.start(spec.run_id)
    _save_state(folder, mt2d_run_id=str(spec.run_id), mt2d_strike_degrees=strike)
    print(f"started   {spec.run_id}  ({len(chosen)} sites, {MT2D_MODE.upper()})", flush=True)
    _wait(runs, spec.run_id)


def _decimated(frequencies: np.ndarray, per_decade: float) -> np.ndarray:
    """Ascending indices of a log-spaced subset, at most `per_decade` per decade."""
    ascending = np.argsort(frequencies)
    values = np.asarray(frequencies)[ascending]
    decades = float(np.log10(values[-1] / values[0]))
    count = max(2, int(np.ceil(decades * per_decade)) + 1)
    targets = np.geomspace(values[0], values[-1], count)
    chosen = np.unique([int(np.argmin(np.abs(values - target))) for target in targets])
    return np.asarray(ascending[chosen])


def _edi_for(site_id: str) -> Path:
    """The EDI a site identifier came from."""
    candidate = MT / f"{site_id}.edi"
    if candidate.exists():
        return candidate
    raise SystemExit(f"no EDI found for {site_id} in {MT}")


def _mt2d_run_spec(record: object, sites: list[dict]) -> RunSpec:
    def length(value: float) -> dict:
        return {"value": value, "quantity_type": "length", "unit": "m"}

    def conductivity(ohm_m: float) -> dict:
        return {"value": 1.0 / ohm_m, "quantity_type": "conductivity", "unit": "S/m"}

    return RunSpec(
        schema_version="1.1",
        plugin_id="simpeg.nsem.mt2d",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        dataset=DatasetSpec(
            name="Utah FORGE Phase 3 magnetotellurics, one profile",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.MAGNETOTELLURIC_IMPEDANCE,
            units="ohm",
        ),
        label=f"MT 2D, {len(sites)} sites, {MT2D_MODE.upper()}",
        physics={
            "mesh": {
                "core_cell": length(MT2D_CELL_M),
                "core_depth": length(MT2D_CORE_DEPTH_M),
                "core_margin": length(MT2D_CORE_MARGIN_M),
                "padding_skin_depths": 4.0,
                "padding_resistivity": conductivity(1_000.0),
            },
            "model": {
                "initial_conductivity": conductivity(MT_START_OHM_M),
                "lower_bound": conductivity(MT_BOUNDS_OHM_M[1]),
                "upper_bound": conductivity(MT_BOUNDS_OHM_M[0]),
            },
            "regularization": {"alpha_s": 1e-4, "alpha_y": 1.0, "alpha_z": 1.0},
            "optimizer": {"max_iterations": MT2D_MAX_ITERATIONS, "cg_max_iterations": 10},
            # Cool every iteration, from the estimator's own starting beta.
            "beta": {"beta0_ratio": 1.0, "cooling_rate": 1},
            "directives": {"target_chi_factor": 1.0},
            "sites": sites,
        },
    )


def _mt_layers() -> list[float]:
    ratio = (MT_LAST_LAYER_M / MT_FIRST_LAYER_M) ** (1.0 / (MT_LAYERS - 1))
    return [MT_FIRST_LAYER_M * ratio**index for index in range(MT_LAYERS)]


def _mt_run_spec(record: object, sites: list[dict]) -> RunSpec:
    def conductivity(ohm_m: float) -> dict:
        return {"value": 1.0 / ohm_m, "quantity_type": "conductivity", "unit": "S/m"}

    return RunSpec(
        schema_version="1.1",
        plugin_id="simpeg.nsem.mt1d_batch",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        dataset=DatasetSpec(
            name="Utah FORGE Phase 3 magnetotellurics",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.MAGNETOTELLURIC_IMPEDANCE,
            units="ohm",
        ),
        label=f"MT 1D batch, {len(sites)} sites",
        physics={
            "earth": {
                "layer_thicknesses": {
                    "value": _mt_layers(),
                    "quantity_type": "length",
                    "unit": "m",
                }
            },
            "model": {
                "initial_conductivity": conductivity(MT_START_OHM_M),
                "lower_bound": conductivity(MT_BOUNDS_OHM_M[1]),
                "upper_bound": conductivity(MT_BOUNDS_OHM_M[0]),
            },
            "regularization": {"alpha_s": 0.01, "alpha_z": 1.0},
            "optimizer": {"max_iterations": 15},
            "directives": {"target_chi_factor": 1.0},
            "sites": sites,
        },
    )


# -- depth of investigation ------------------------------------------------

#: The two reference models the depth-of-investigation test inverts against,
#: as contrasts against REDUCTION_DENSITY: basin fill and granitoid basement.
#:
#: Constants rather than the two-layer reference the other runs use, and that
#: is the point. A depth of investigation is meant to be a property of the
#: data, the mesh and the regularization; running it against a reference built
#: from the published granite surface would fold that surface's own authority
#: into the answer and report the prior as resolution.
DOI_REFERENCES = (BASIN_FILL_DENSITY - REDUCTION_DENSITY, BASEMENT_DENSITY - REDUCTION_DENSITY)

#: Oldenburg and Li put the cutoff between 0.1 and 0.2. The looser one is used
#: here and stated rather than tuned.
DOI_CUTOFF = 0.2

DEPTH_BANDS_M = ((0, 100), (100, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000))


def doi() -> None:
    """How deep the data decides, after Oldenburg and Li (1999)."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if "observations_path" not in state:
        raise SystemExit("run `prepare` first")

    gap = abs(DOI_REFERENCES[1] - DOI_REFERENCES[0])
    print(f"references {DOI_REFERENCES[0]:+.3f} and {DOI_REFERENCES[1]:+.3f} g/cm^3, gap {gap:.3f}")
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    depth = _depth_below_surface(state)
    columns: dict[str, np.ndarray] = {}
    saved: dict[str, list[str]] = {}

    # The test is run twice over, once with the sensitivity weighting the other
    # inversions use and once without it.
    for label, overrides in (
        ("weighted", None),
        ("unweighted", {"directives": {"sensitivity_weighting": {"enabled": False}}}),
    ):
        recovered = []
        run_ids = []
        for index, value in enumerate(DOI_REFERENCES):
            path = _constant_reference(folder, state, value, f"doi_reference_{index}.npy")
            spec = _run_spec(
                record,
                state,
                path,
                overrides=overrides,
                label=f"DOI {label}, reference {value:+.3f}",
            )
            runs.create(spec)
            runs.start(spec.run_id)
            _wait(runs, spec.run_id, quiet=True)
            summary, model = _recovered(runs, str(spec.run_id))
            if model is None:
                raise SystemExit(f"the depth-of-investigation run failed: {summary}")
            print(
                f"  {label:10s} reference {value:+.3f}  "
                f"chi-squared {summary.get('chi_squared', float('nan')):.3f}",
                flush=True,
            )
            recovered.append(model)
            run_ids.append(str(spec.run_id))
        columns[label] = np.abs(recovered[0] - recovered[1]) / gap
        saved[label] = run_ids

    path = Path(folder.imports_root) / "doi_index.npy"  # type: ignore[attr-defined]
    np.save(path, np.c_[columns["weighted"], columns["unweighted"]])
    _save_state(folder, doi_run_ids=saved, doi_index_path=path.as_posix())

    print()
    print(
        f"{'depth below surface':>22}  {'cells':>8}  "
        f"{'R weighted':>11}  {'R unweighted':>13}  {'median cell':>12}"
    )
    _, cell_volume = _cell_sizes(state)
    for lower, upper in DEPTH_BANDS_M:
        inside = (depth >= lower) & (depth < upper)
        if not inside.any():
            continue
        print(
            f"{f'{lower}-{upper} m':>22}  {int(inside.sum()):8d}  "
            f"{np.median(columns['weighted'][inside]):11.3f}  "
            f"{np.median(columns['unweighted'][inside]):13.3f}  "
            f"{np.median(cell_volume[inside]) ** (1 / 3):9.0f} m"
        )
    print()
    for label, values in columns.items():
        share = float((values < DOI_CUTOFF).mean())
        print(
            f"{label:11s} median R {np.median(values):.3f}, {share:.0%} of cells below {DOI_CUTOFF}"
        )


def _cell_sizes(state: dict) -> tuple[np.ndarray, np.ndarray]:
    """Active cell centres and volumes, so depth can be read against cell size."""
    from discretize.utils import active_from_xyz

    mesh, topography = _mesh_for(state)
    active_cells = np.asarray(active_from_xyz(mesh, topography), dtype=bool)
    centres = np.asarray(mesh.cell_centers, dtype=float)[active_cells]  # type: ignore[attr-defined]
    volumes = np.asarray(mesh.cell_volumes, dtype=float)[active_cells]  # type: ignore[attr-defined]
    return centres, volumes


def _constant_reference(folder: object, state: dict, value: float, name: str) -> str:
    """A uniform starting and reference model, on the mesh the plugin will build."""
    mesh, _ = _mesh_for(state)
    path = Path(folder.imports_root) / name  # type: ignore[attr-defined]
    np.save(path, np.full(int(mesh.nC), value))  # type: ignore[attr-defined]
    return path.as_posix()


def _depth_below_surface(state: dict) -> np.ndarray:
    """Depth of each active cell centre beneath the terrain directly above it."""
    from discretize.utils import active_from_xyz
    from scipy.spatial import cKDTree

    mesh, topography = _mesh_for(state)
    centres = np.asarray(mesh.cell_centers, dtype=float)  # type: ignore[attr-defined]
    active_cells = np.asarray(active_from_xyz(mesh, topography), dtype=bool)
    surface = topography[cKDTree(topography[:, :2]).query(centres[active_cells, :2])[1], 2]
    return np.asarray(surface - centres[active_cells, 2], dtype=float)


# Set case-specific geological model inputs.

#: How far outside the model volume a station still informs it.
#:
#: The volume is 8.25 by 5.25 km and the surveys reach 50 km beyond it. Data
#: further out than this is not deleted -- the 82-site comparison against the
#: published 3D inversion needs all of it -- but it does not enter the model.
MODEL_BUFFER_M = 2_000.0

#: The conductivity every TEM sounding started from, which `resolved_band`
#: measures the recovered layers against. Read from the run rather than
#: retyped, in `_tem_resolved_band`.
TEM_RESOLVED_THRESHOLD = 0.1

#: The shallowest the magnetotellurics can resolve.
#:
#: Every EDI in this survey stops at the same top frequency, 230.5 Hz. The skin
#: depth there is 105 m in 10 ohm.m ground and 222 m in 45, which is the range
#: the near surface spans here.
#:
#: Put beside the TEM's measured floor this is the case's central negative
#: result: **the two electrical methods have no depth band in which both
#: resolve.** They were tested for agreement anyway and disagree -- the
#: steepest step is at 80 m in the TEM and 339 m in the magnetotellurics,
#: correlating -0.62 across 20 pairs within 1,500 m -- and the disagreement
#: grows with depth, from -0.47 decades at 60 m to -1.32 at 180, exactly as one
#: method runs out of data while the other starts to have some. A per-site
#: constant does not absorb it, so it is not static shift: the within-site
#: scatter with depth is 0.41 decades against 0.19 between sites, which is the
#: wrong way round.
#:
#: So they are not averaged and neither is used to check the other. Each unit
#: is assigned by the one method that resolves its depth.
MT_RESOLVED_FROM_M = 105.0

#: How sharp a step has to be to be picked, as d(log10 rho)/d(log10 depth).
#: 0.3 admits a factor of about two across a layer boundary.
SHALLOW_MIN_SLOPE = 0.3

#: Above this the magnetotelluric section is not a conductor worth drawing.
#: The median profile bottoms at 2.3 ohm.m near 280 m against 10 to 12 below
#: 700 m, so 5 separates the conductive zone from the ground around it.
MT_CONDUCTOR_OHM_M = 5.0

#: How far a cell may be from the nearest magnetotelluric site before the
#: conductor rule declines to judge it. The sites sit about 2 km apart.
#:
#: The shallow surface had such a guard too, at 1,500 m, and it was wrong
#: (F027) -- so this one was put through the same leave-one-out rather than
#: argued for. Asked whether a held-out site's cells are in the conductor, the
#: nearest other site is right 84.0 per cent of the time, against 80.7 for the
#: median of all the others and 65.5 for guessing the commoner label. Here
#: nearest neighbour really is the best of the three, because this is a body
#: picked cell by cell from a resistivity threshold and not a surface with a
#: trend to fall back on.
#:
#: It costs something and the service reports the cost: 11 per cent of the
#: volume lies beyond it, and those cells are not tested rather than found
#: negative. `beyond_reach_share` is that number.
MT_REACH_M = 2_000.0


def _section(runs_root: Path, state: dict, key: str) -> "LayeredSection":
    """One stitched batch as the interpretation service wants it."""
    from ofag.services.interpretation_service import LayeredSection

    stitched = np.load(runs_root / str(state[key]) / "stitched_conductivity_section.npz")
    if "easting_m" in stitched.files:
        east, north = stitched["easting_m"], stitched["northing_m"]
    else:
        located = np.asarray(stitched["receiver_locations_m"], dtype=float)
        if not np.any(located[:, :2]):
            raise ValueError(
                f"the stitched section for {key} places every sounding at the origin. It was "
                "written before the batch carried a station_location; re-run the stage."
            )
        east, north = located[:, 0], located[:, 1]
    return LayeredSection(
        easting_m=east,
        northing_m=north,
        values=1.0 / stitched["conductivity_s_m"],
        layer_top_depth_m=stitched["layer_top_depth_m"],
    )


def _within_buffer(section: "LayeredSection") -> np.ndarray:
    east, north = section.easting_m, section.northing_m
    return (
        (east >= VOLUME[0] - MODEL_BUFFER_M)
        & (east <= VOLUME[1] + MODEL_BUFFER_M)
        & (north >= VOLUME[2] - MODEL_BUFFER_M)
        & (north <= VOLUME[3] + MODEL_BUFFER_M)
    )


def _tem_starting_conductivity(runs_root: Path, state: dict) -> float:
    """What the TEM soundings were told to start from, read from the run."""
    import yaml

    spec = yaml.safe_load(
        (runs_root / str(state["tem_run_id"]) / "run_spec.yaml").read_text(encoding="utf-8")
    )

    def find(node: object, key: str) -> object | None:
        if isinstance(node, dict):
            for name, value in node.items():
                if name == key:
                    return value
                found = find(value, key)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find(value, key)
                if found is not None:
                    return found
        return None

    initial = find(spec, "initial_conductivity")
    value = find(initial, "value") if isinstance(initial, dict) else None
    return float(np.atleast_1d(np.asarray(value, dtype=float))[0])


def build_model() -> None:
    """The geological model: four units, each from the one method that resolves it."""
    from ofag.core.schemas import UnitRule, UnitRuleKind
    from ofag.services.interpretation_service import InterpretationService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    runs_root = Path(folder.runs_root)  # type: ignore[attr-defined]
    service = InterpretationService()

    directory = runs_root / str(state["run_id"])
    geometry = np.load(directory / "mesh_geometry.npz")
    centres = geometry["cell_centers_m"]
    volume = np.prod(geometry["cell_widths_m"], axis=1)
    active = geometry["active_cells"].astype(bool)
    recovered = np.full(centres.shape[0], np.nan)
    recovered[active] = np.load(directory / "recovered_density_g_cc.npy")

    # VOLUME is the horizontal extent and ELEVATION_RANGE_M the vertical one.
    inside = (
        active
        & (centres[:, 0] >= VOLUME[0])
        & (centres[:, 0] <= VOLUME[1])
        & (centres[:, 1] >= VOLUME[2])
        & (centres[:, 1] <= VOLUME[3])
        & (centres[:, 2] >= ELEVATION_RANGE_M[0])
        & (centres[:, 2] <= ELEVATION_RANGE_M[1])
    )

    topography = np.loadtxt(state["topography_path"], delimiter=",", skiprows=1)
    ground, _ = _nearest(topography[:, :2], topography[:, 2], centres[:, :2], np.inf)
    depth = ground - centres[:, 2]
    granite = np.loadtxt(state["granite_path"], delimiter=",", skiprows=1)
    basement_top, _ = _nearest(granite[:, :2], granite[:, 2], centres[:, :2], np.inf)

    # How deep the TEM actually carries information, measured against the model it
    # started from.
    tem = _section(runs_root, state, "tem_run_id")
    band = service.resolved_band(
        tem,
        np.asarray(1.0 / _tem_starting_conductivity(runs_root, state)),
        threshold=TEM_RESOLVED_THRESHOLD,
    )
    picks = service.pick_contact(
        tem,
        (20.0, band.deepest_m),
        minimum_slope=SHALLOW_MIN_SLOPE,
        within=_within_buffer(tem),
    )
    shallow = service.fit_surface("shallow conductor base", picks, targets_m=centres[inside])

    mt = _section(runs_root, state, "mt_run_id")
    keep = _within_buffer(mt)
    from ofag.services.interpretation_service import LayeredSection

    mt_nearby = LayeredSection(
        easting_m=mt.easting_m[keep],
        northing_m=mt.northing_m[keep],
        values=mt.values[keep],
        layer_top_depth_m=mt.layer_top_depth_m,
    )

    # Order is precedence, and it is a statement about which evidence is harder.
    rules = (
        UnitRule(
            name="granitoid basement",
            source="seismic top of granite, tested by gravity",
            kind=UnitRuleKind.BELOW_SURFACE,
            surface="basement",
        ),
        UnitRule(
            name="shallow conductor",
            source="TEM",
            kind=UnitRuleKind.ABOVE_SURFACE,
            surface="shallow",
        ),
        UnitRule(
            name="intermediate conductor",
            source="MT",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="mt",
            threshold=MT_CONDUCTOR_OHM_M,
            below_threshold=True,
            resolved_from_depth_m=MT_RESOLVED_FROM_M,
            reach_m=MT_REACH_M,
        ),
        # Named for what decides it.
        UnitRule(
            name="basin fill",
            source="above the seismic surface, no conductor",
            kind=UnitRuleKind.REMAINDER,
        ),
    )
    shallow_base = shallow.predict(centres[:, :2])
    model = service.assign_units(
        rules,
        cell_centres_m=centres[inside],
        cell_volume_m3=volume[inside],
        depth_below_ground_m=depth[inside],
        surfaces={"basement": basement_top[inside], "shallow": shallow_base[inside]},
        sections={"mt": mt_nearby},
    )

    unit = np.full(centres.shape[0], -1, dtype=np.int16)
    unit[inside] = model.unit
    support = np.full(centres.shape[0], np.nan)
    support[inside] = model.support_distance_m
    # The surface's own score travels with the model, so a figure drawn from this file
    # quotes what the fit actually reported rather than a number typed beside it (F025).
    report = model.report.model_copy(update={"surfaces": (shallow.report,)})

    density = recovered + REDUCTION_DENSITY
    verdict = _gravity_verdict(runs_root, state, centres, inside, basement_top)
    dense_body = (
        inside
        & (unit == 0)
        & (verdict["code"] == VERDICT_MORE_MASS)
        & (density >= DIORITE_FROM_G_CC)
    )

    path = Path(folder.imports_root) / "geological_model.npz"  # type: ignore[attr-defined]
    np.savez_compressed(
        path,
        unit=unit,
        unit_names=np.array([rule.name for rule in rules]),
        unit_sources=np.array([rule.source for rule in rules]),
        support_distance_m=support,
        shallow_base_depth_m=shallow_base,
        basement_top_elevation_m=basement_top,
        pick_locations_m=picks.locations_m,
        pick_depth_m=picks.depth_m,
        density_g_cc=density,
        gravity_shift_m=verdict["shift_m"],
        gravity_verdict=verdict["code"],
        gravity_verdict_names=np.array(VERDICT_NAMES),
        # The verdict as it was counted, one row per 50 m column, so a map is drawn from
        # the columns rather than rebuilt from the cells.
        gravity_column_xy_m=verdict["columns"]["xy"],
        gravity_column_shift_m=verdict["columns"]["shift_m"],
        gravity_column_verdict=verdict["columns"]["code"],
        dense_basement=dense_body,
        report=json.dumps(report.model_dump(mode="json")),
    )
    _save_state(folder, geological_model_path=path.as_posix())

    print(f"build     {int(inside.sum()):,} cells in the model volume")
    print(
        f"          TEM resolves to {band.deepest_m:.0f} m, measured against its own starting "
        f"model; below that a layer has not moved"
    )
    print(
        f"          shallow base picked at {picks.depth_m.size} of {picks.attempted} soundings "
        f"in range, median {np.median(picks.depth_m):.0f} m "
        f"(p25 {np.percentile(picks.depth_m, 25):.0f}, p75 {np.percentile(picks.depth_m, 75):.0f})"
    )
    print()
    print(f"          {'unit':24s} {'share':>7s} {'cells':>9s}  resolved by")
    for item in model.report.units:
        print(
            f"          {item.name:24s} {100 * item.volume_share:6.1f}% "
            f"{item.cell_count:9,d}  {item.source}"
        )
    if model.report.undecided_cells:
        print(f"          {model.report.undecided_cells:,} cells no rule claimed")
    print()

    fit = shallow.report
    ranked = sorted(fit.candidates.items(), key=lambda pair: pair[1])
    print(
        f"          the shallow surface was fitted by {fit.estimator!r}, chosen by "
        f"leave-one-out: {', '.join(f'{name} {value:.1f} m' for name, value in ranked)}"
    )
    print(
        f"          it predicts a pick it has not seen to {fit.held_out_error:.1f} m against "
        f"{fit.pick_spread:.1f} m for the picks' own spread, and no modelled cell is further "
        f"than {fit.furthest_from_a_pick_m:.0f} m from one"
    )
    for item in model.report.units:
        if item.beyond_reach_share:
            print(
                f"          {item.name!r} declined to judge "
                f"{100 * item.beyond_reach_share:.1f}% of the volume, further than its reach "
                f"from any site. Those cells are untested, not negative"
            )

    # Where the TEM and the seismic contradict each other, rather than quietly letting
    # one win.
    disputed = inside & (unit == 0) & (depth <= shallow_base)
    if disputed.any():
        print(
            f"          the TEM conductor reaches below the seismic basement in "
            f"{int(disputed.sum()):,} cells "
            f"({100 * float(volume[disputed].sum()) / float(volume[inside].sum()):.2f}% by "
            f"volume). Left as basement and recorded: either the surface is wrong there or the "
            f"conductor is weathered granitoid"
        )

    # What the density model adds to the units: the density of each, measured rather
    # than assumed, where the data resolved it.
    print()
    # Two runs that both rest on the same bound agree exactly and score zero, which is
    # the solver saturating twice rather than the data deciding.
    doi_runs = [
        np.load(runs_root / run_id / "recovered_density_g_cc.npy")
        for run_id in state["doi_run_ids"]["weighted"]
    ]
    resolved = np.zeros(centres.shape[0], dtype=bool)
    resolved[active] = (
        (np.load(state["doi_index_path"])[:, 0] < DOI_CUTOFF)
        & ~_at_bound(doi_runs[0])
        & ~_at_bound(doi_runs[1])
    )
    print(f"          {'unit':24s} {'density, all cells':>22s}   {'where resolved':>20s}")
    for index, rule in enumerate(rules):
        mask = inside & (unit == index)
        here = mask & resolved
        measured = (
            f"{np.median(density[here]):.3f} ({100 * volume[here].sum() / volume[mask].sum():.0f}%)"
            if here.any()
            else "none resolved"
        )
        print(
            f"          {rule.name:24s} median {np.median(density[mask]):.3f} "
            f"IQR {np.percentile(density[mask], 25):.2f}-{np.percentile(density[mask], 75):.2f}"
            f"   {measured:>20s}"
        )

    # Witter's question, asked of our density model: does the gravity support the
    # surface the seismic fixed?
    print()
    print(
        f"          the gravity's verdict on the seismic surface, per 50 m column, as the "
        f"shift of the surface that would carry the column's excess mass "
        f"(|shift| <= {SUPPORTED_SHIFT_M:.0f} m is support)"
    )
    columns = verdict["columns"]
    print(
        f"          every column shares a shift of {verdict['common_shift_m']:+.0f} m within "
        f"{VERDICT_BAND_M:.0f} m of the surface, taken out: the unit densities, not the surface"
    )
    for code, name in enumerate(VERDICT_NAMES):
        share = float((columns["code"] == code).mean())
        print(f"          {name:44s} {100 * share:5.1f}% of columns")
    for label, agree, correlation in verdict["controls"]:
        print(
            f"          against the {label} inversion, which saw no surface: map correlation "
            f"{correlation:+.2f}, {100 * agree:.0f}% of flagged columns flagged the same way"
        )
    for zone in verdict["zones"]:
        print(
            f"          Witter raised the surface over {zone['area_km2']:.2f} km2 at "
            f"E{zone['east_m']:.0f} N{zone['north_m']:.0f}: our shift there "
            f"{zone['shift_m']:+.0f} m, p = {zone['p']:.3f} against the same zone moved at random"
        )
    print(
        f"          he lowered it over {verdict['lowered_km2']:.1f} km2 in the south-west; our "
        f"median shift there is {verdict['lowered_shift_m']:+.0f} m"
    )
    print(
        f"          {int(dense_body.sum()):,} basement cells "
        f"({float(volume[dense_body].sum()) / 1e9:.3f} km3) at {DIORITE_FROM_G_CC} g/cm^3 or "
        f"more under columns that want more mass: the dioritic bodies he proposed"
    )
    print()
    print(f"          written to {path.as_posix()}")


#: What a column's verdict can be. Stored as codes beside the model so a
#: figure reads the same classes the report counted.
VERDICT_NAMES = (
    "supports the seismic surface",
    "more mass: shallower basement or dense rock",
    "less mass: deeper basement or lighter fill",
    "not tested: no station within reach",
)
VERDICT_SUPPORTS, VERDICT_MORE_MASS, VERDICT_LESS_MASS, VERDICT_UNTESTED = range(4)

#: Twice the +/- 50 m Miller et al. (2019, MP-169-H) give for their pick of the
#: granite on crossline 105, through well 58-32. That is the best-imaged place
#: in the survey, so away from it the seismic is less certain than this and a
#: flagged column is a question for the seismic rather than a refutation.
#: This is wrong if the pick uncertainty is published away from the well: the
#: threshold should then follow it column by column instead of being one number.
SUPPORTED_SHIFT_M = 100.0

#: How far either side of the seismic surface a column's excess mass is
#: counted. Witter moved the surface by "several tens to a few hundreds of
#: meters" where he raised it, so the band is chosen to hold a shift of that
#: size rather than the whole column. Wider, it gathers mass the surface does
#: not explain, and the supported share falls from 81 per cent at 150 m to 26
#: at 1,000 (docs/case1_forge.md).
#: This is wrong if the inversion's vertical resolution at the surface is
#: measured: the band should then be that.
VERDICT_BAND_M = 300.0

#: A column further than this from every station is not tested. The median
#: spacing of the 323 stations is 339 m; Witter's south-east corner, where he
#: called his own anomaly an artefact of having one station, is the case.
STATION_REACH_M = 500.0

#: The low edge of the dioritic class, 2.80 +/- 0.05 (PETROPHYSICAL_CLASSES).
DIORITE_FROM_G_CC = 2.75


def _gravity_verdict(
    runs_root: Path, state: dict, centres: np.ndarray, inside: np.ndarray, top: np.ndarray
) -> dict:
    """Where the recovered density agrees with the seismic two-layer model, per column."""
    from scipy import ndimage
    from scipy.spatial import cKDTree

    directory = runs_root / str(state["run_id"])
    geometry = np.load(directory / "mesh_geometry.npz")
    active = geometry["active_cells"].astype(bool)
    widths = geometry["cell_widths_m"]
    reference = np.load(state["reference_path"])
    gap = BASEMENT_DENSITY - BASIN_FILL_DENSITY

    # Columns are the 50 m cells of the finest level.
    cell = MESH_CELL_M[0]
    left = centres[:, :2] - widths[:, :2] / 2
    origin = left[inside].min(axis=0)
    first = np.rint((left - origin) / cell).astype(np.int64)
    span = np.maximum(np.rint(widths[:, :2] / cell).astype(np.int64), 1)
    shape = tuple((first + span)[inside].max(axis=0))
    owners = np.flatnonzero(inside)
    count = span[owners, 0] * span[owners, 1]
    owner = np.repeat(owners, count)
    step = np.arange(owner.size) - np.repeat(np.cumsum(count) - count, count)
    column_i = first[owner, 0] + step % span[owner, 0]
    column_j = first[owner, 1] + step // span[owner, 0]
    flat = column_i * shape[1] + column_j
    covered = np.bincount(flat, minlength=shape[0] * shape[1]) > 0
    keys = np.argwhere(covered.reshape(shape))
    position = np.full(shape[0] * shape[1], -1)
    position[np.flatnonzero(covered)] = np.arange(len(keys))
    xy = origin + (keys + 0.5) * cell

    near_surface = np.abs(centres[:, 2] - top) <= VERDICT_BAND_M

    def excess(values_on_active: np.ndarray) -> np.ndarray:
        values = np.full(centres.shape[0], np.nan)
        values[active] = values_on_active
        mass = (values - reference)[owner] * widths[owner, 2] * near_surface[owner]
        return np.bincount(flat, weights=mass, minlength=shape[0] * shape[1])[covered]

    stations = np.loadtxt(state["observations_path"], delimiter=",", skiprows=1)[:, :2]
    tested = cKDTree(stations).query(xy)[0] <= STATION_REACH_M
    shift = excess(np.load(directory / "recovered_density_g_cc.npy")) / gap
    common = float(np.median(shift[tested]))
    shift -= common
    code = np.full(len(keys), VERDICT_SUPPORTS, dtype=np.int8)
    code[shift > SUPPORTED_SHIFT_M] = VERDICT_MORE_MASS
    code[shift < -SUPPORTED_SHIFT_M] = VERDICT_LESS_MASS
    code[~tested] = VERDICT_UNTESTED
    flagged = (code == VERDICT_MORE_MASS) | (code == VERDICT_LESS_MASS)

    controls = []
    for label in ("weighted", "unweighted"):
        a, b = (
            np.load(runs_root / run_id / "recovered_density_g_cc.npy")
            for run_id in state["doi_run_ids"][label]
        )
        other = excess((a + b) / 2)
        # A constant reference has no layering, so its excess over the two-layer model
        # carries an offset the whole map shares.
        other -= np.median(other[tested])
        controls.append(
            (
                f"{label} constant-reference",
                float((np.sign(other[flagged]) == np.sign(shift[flagged])).mean()),
                float(np.corrcoef(shift[tested], other[tested])[0, 1]),
            )
        )

    # Witter's model 2 surface minus the original: where he moved it.
    original = np.loadtxt(state["granite_path"], delimiter=",", skiprows=1)
    modified = np.loadtxt(state["granite_modified_path"], delimiter=",", skiprows=1)
    moved = (
        modified[cKDTree(modified[:, :2]).query(xy)[1], 2]
        - original[cKDTree(original[:, :2]).query(xy)[1], 2]
    )
    grid_index = keys
    on_grid = np.full(shape, np.nan)
    on_grid[grid_index[:, 0], grid_index[:, 1]] = shift
    labels, count = ndimage.label(_on_grid(grid_index, shape, moved > WITTER_MOVED_M))
    rng = np.random.default_rng(0)
    zones = []
    for label in range(1, count + 1):
        cells = np.argwhere(labels == label)
        if len(cells) < 10:
            continue
        observed = float(np.nanmean(on_grid[cells[:, 0], cells[:, 1]]))
        null = []
        while len(null) < 2_000:
            offset = rng.integers(-cells.min(axis=0), np.array(shape) - cells.max(axis=0))
            values = on_grid[cells[:, 0] + offset[0], cells[:, 1] + offset[1]]
            if np.isfinite(values).mean() > 0.9:
                null.append(np.nanmean(values))
        centre = origin + (cells.mean(axis=0) + 0.5) * cell
        zones.append(
            {
                "east_m": float(centre[0]),
                "north_m": float(centre[1]),
                "area_km2": len(cells) * cell**2 / 1e6,
                "shift_m": observed,
                "p": float((np.asarray(null) >= observed).mean()),
            }
        )
    lowered = moved < -WITTER_MOVED_M

    # A cell carries the verdict of the column under its centre.
    under = np.clip(
        np.floor((centres[:, :2] - origin) / cell).astype(np.int64), 0, np.array(shape) - 1
    )
    index = position[under[inside, 0] * shape[1] + under[inside, 1]]
    shift_per_cell = np.full(centres.shape[0], np.nan)
    shift_per_cell[inside] = shift[index]
    code_per_cell = np.full(centres.shape[0], -1, dtype=np.int8)
    code_per_cell[inside] = code[index]
    return {
        "shift_m": shift_per_cell,
        "code": code_per_cell,
        "columns": {"xy": xy, "shift_m": shift, "code": code},
        "common_shift_m": common,
        "controls": controls,
        "zones": [zone for zone in zones if zone["east_m"] > WITTER_EAST_OF_M],
        "lowered_km2": float(lowered.sum() * cell**2 / 1e6),
        "lowered_shift_m": float(np.median(shift[lowered])),
    }


#: A change of more than this between Witter's two surfaces is one he made,
#: rather than the regridding between them, which moves the surface by tens
#: of metres everywhere.
WITTER_MOVED_M = 50.0

#: His four raised areas "all lie east of the FORGE site" (report, p. 13). The
#: one raised patch west of it is the rim of his south-western lowering.
WITTER_EAST_OF_M = 335_000.0


def _on_grid(grid_index: np.ndarray, shape: tuple, values: np.ndarray) -> np.ndarray:
    grid = np.zeros(shape, dtype=bool)
    grid[grid_index[:, 0], grid_index[:, 1]] = values
    return grid


def _nearest(points: np.ndarray, values: np.ndarray, targets: np.ndarray, reach: float):
    """Nearest-neighbour lookup that refuses to answer beyond `reach`."""
    from scipy.spatial import cKDTree

    distance, index = cKDTree(points).query(targets)
    return values[index], distance <= reach


STAGES = {
    "prepare": prepare,
    "invert": invert,
    "invert_pgi": invert_pgi,
    "import_tem": import_tem,
    "invert_tem": invert_tem,
    "import_mt": import_mt,
    "invert_mt": invert_mt,
    "compare_mt": compare_mt,
    "invert_mt2d": invert_mt2d,
    "sweep_pgi": sweep_pgi,
    "doi": doi,
    "build_model": build_model,
    "compare": compare,
    "report": report,
}

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage not in STAGES:
        raise SystemExit(f"usage: {Path(__file__).name} [{'|'.join(STAGES)}]")
    STAGES[stage]()
