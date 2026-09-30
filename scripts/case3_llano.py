"""Case 3: the Granite Gravel Aquifer, Llano Uplift, central Texas."""

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
)
from ofag.services.project_service import ProjectService

if TYPE_CHECKING:
    from ofag.agent.diagnosis import Diagnosis
    from ofag.agent.duplicates import Copies
    from ofag.services.interpretation_service import LayeredSection

CASE = Path("data/case3_Llano")
ERT = CASE / "ert"
SRT = CASE / "srt"
TDEM = CASE / "tdem"
WELLS = CASE / "wells"
DEM = CASE / "dem/llano_3dep_1m.tif"
RESULT_ROOT = Path("Result")
PROJECT_NAME = "Llano Uplift"

#: UTM zone 14N on NAD83, which is what central Texas is in. The release gives
#: latitude and longitude on NAD83 and an along-line coordinate; the along-line
#: one is what the 2D inversions use and this is for placing the lines against
#: each other.
CRS = "EPSG:26914"

#: How far apart the lines actually are, measured from the delivered
#: coordinates rather than taken from the release's summary.
#:
#: The summary says the survey is "within a 100-meter by 100-m survey area". It
#: spans 276 by 175 m, and the useful number is smaller than either: SRT2 comes
#: within **0.4 to 0.9 m** of both resistivity lines, so seismic and resistivity
#: share a crossing rather than a neighbourhood.
LINE_SEPARATION_M = {"ERT1-SRT2": 0.9, "ERT2-SRT2": 0.4}

#: The declared relative error, and the floor beneath it.
#:
#: Declared, because this format carries none of the three things case 2 could
#: measure from: no per-reading error column, no reciprocal pairs, no contact
#: resistance. Five per cent is what case 2 used as its floor and is ordinary
#: practice; the absolute term keeps a near-zero reading from claiming a
#: near-zero error. Both are stated here so a result can be read against them.
ERT_RELATIVE_ERROR = 0.05
ERT_ABSOLUTE_FLOOR_OHM = 1.0e-4

#: Drop a reading whose apparent resistivity comes back non-positive. None do
#: in this release -- 0 of 243 on each profile -- so this costs nothing and is
#: set anyway, because a filter that only runs when it is needed is a filter
#: nobody has checked.
DROP_NON_POSITIVE = True

#: The electrodes are inverted at their true elevations, and not because it
#: improves the fit.
#:
#: It was set here on the argument that profile 2 falls 9.75 m over its 188 m
#: and that a half-space geometric factor is about five per cent wrong on
#: terrain, so the relief had to be modelled. Measured, that argument is wrong.
#: Inverting both profiles flat gives 3.074 and 0.747 against 3.090 and 0.762
#: at true elevation -- flat is very slightly the better fit on both. A 9.75 m
#: fall over 188 m is nearly a plane, and a tilted plane is nearly a rotated
#: half-space, which is the same reason the authors' own settings asked
#: RES2DINV to remove the end-to-end trend before inverting.
#:
#: It stays on for the other reason. The section has to be compared with a
#: borehole that refuses at 2.3 m and with a seismic line a metre away, and
#: both of those are at real elevations. Topography here buys the geometry,
#: not the misfit.
USE_TOPOGRAPHY = True

#: Where the surface comes from. A third source appeared, and the record this
#: replaces said in as many words that a third source reverses it.
#:
#: The release states the surface twice and the two disagree by up to 2.44 m
#: (F037). The `.dat` files carry a trailing topography block; `electrodes_xyz.txt`
#: tabulates the same forty-eight positions separately. The table was chosen on
#: shape -- the scatter of its second difference is 0.23 and 0.25 m against the
#: block's 1.35 and 1.99, and the block steps 2.4 m between electrodes 4 m
#: apart, a 60 per cent slope on a line whose whole fall is 5 per cent.
#:
#: Both lists are contour crossings. Every elevation in the release, 96
#: electrodes and 48 geophones, is a whole number of feet from 938 to 970 with
#: 965 absent: the vertical resolution is 0.3048 m and ERT1's entire relief is
#: six steps of it (F048, A12).
#:
#: The third source settles it and is not a judgement. Two independent USGS
#: products -- 1 m bare-earth lidar flown in 2018 and the 1/3 arc-second
#: seamless DEM -- agree with each other to 6 cm at these stations and both sit
#: 2.4 to 2.7 m above the release's table, carrying three quarters of its
#: relief: 1.10 m against 1.83 on ERT1 and 7.49 against 9.75 on ERT2. Two
#: products that disagree with a third and not with each other is not a tie.
#:
#: The 2.4 m is the same eight feet the release's own two lists differ by,
#: which is the most likely account of all three numbers at once.
#:
#: This is wrong if the lidar is shown to be a canopy return rather than ground
#: here, or if a levelled benchmark on the site disagrees with it.
ELEVATION_SOURCE = "dem/llano_3dep_1m.tif"

#: The tile the surface is sampled from. USGS 3DEP 1 m, tile 14 x55y340 of
#: project TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA, cropped to the survey plus
#: 400 m, read bilinear at each station.
#:
#: Cited by its ScienceBase item, which is the persistent handle. Of the twelve
#: 3DEP downloadable collections exactly one, Seamless 1 m, carries a
#: registered DOI (10.5066/P13LJKFS) and it does not reach Llano, so there is
#: no DOI for this tile and the dash is the honest entry -- as the Stillwater
#: table already does for USGS I-797.
#:
#: The selection rule is about permanence rather than about the shape of the
#: string, and by that test the S3 object key is the weaker of the two: the
#: staged elevation products are republished under dated names with a
#: `current` and a `historical` split, so the key below is a convenience and
#: the ScienceBase item is the identifier.
DEM_SOURCE = "https://www.sciencebase.gov/catalog/item/619c3717d34eb622f6931b2b"

#: Below this the two lists are treated as agreeing and nothing is said.
ELEVATION_DISAGREEMENT_M = 0.05

#: Their settings, for comparison rather than imitation: 7 iterations, a
#: vertical-to-horizontal flatness ratio of 1.0, Gauss-Newton, and robust (L1)
#: constraints on both data and model with cutoffs of 0.05.
#:
#: Both L1 norms were tried here and neither is switched on, and the reason
#: recorded here was wrong for as long as it stood.
#:
#: It read that blocky model constraints moved profile 1's five-to-fifteen
#: metre band by one ohm-metre. That number is the difference between the two
#: sections' **global maxima**, which sit at 33 m depth and x = 85 m -- twenty
#: metres below the band and outside the x = 48-76 m window the authors' 912
#: ohm.m is read in. Scored inside that window the norm nearly doubles the
#: section: 151 to 263 ohm.m at the median, 312 to 619 at the maximum, with
#: chi squared falling 3.079 to 2.703.
#:
#: So the norm is not a null. It is a large change that still misses the bar
#: of 2, on a profile whose worst-fitting stretch is that same window, and it
#: is left off because it does not close the gap rather than because it does
#: nothing. Robust data weighting is left off for a different reason: run
#: alone it takes chi squared to 4.65, which is what a structural misfit does
#: when an outlier weight is applied to it.
#:
#: The same was asked of the smoothing strength: from lambda 50 down to 2 the
#: profile-1 misfit falls monotonically, 4.31 to 2.33, and never reaches the
#: bar.
ERT_LAMBDA = 20.0
ERT_VERTICAL_WEIGHT = 1.0
ERT_MAX_ITERATIONS = 12

#: Both profiles are inverted on identical settings, and this is the reason.
#:
#: Profile 2 fits and profile 1 does not, and that difference is worth having
#: only if it belongs to the data. Tuning profile 1 until it fits -- a smaller
#: lambda, an L1 norm, a looser declared error -- would buy a number and spend
#: the comparison, because the two sections would then differ by the operator
#: as much as by the ground. The misfit is reported instead, and located.
SETTINGS_ARE_SHARED = True

#: The starting model and the range the inversion may not leave. Weathered
#: granite: the delivered apparent resistivities have medians of 140 and
#: 176 ohm.m and reach 48 to 353 at the fifth and ninety-fifth percentiles.
STARTING_RESISTIVITY = 150.0
RESISTIVITY_BOUNDS = (5.0, 20_000.0)

#: How deep the parameter domain goes. The arrays are 188 m long, so pyGIMLi's
#: own rule of thumb would take it deeper than the data can see; the borehole
#: refuses the auger at 2.3 m and the interesting ground is the top few tens of
#: metres.
MESH_DEPTH_M = 40.0

#: What counts as fitted, the same bar case 2 set.
ERT_ACCEPTABLE_CHI_SQUARED = 2.0
SRT_ACCEPTABLE_CHI_SQUARED = 2.0


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
            enabled_methods=("ert", "seismic", "aem"),
        )
    )


def _state_path(folder: object) -> Path:
    return Path(folder.root) / "case_state.json"  # type: ignore[attr-defined]


def _load_state(folder: object) -> dict:
    path = _state_path(folder)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save_state(folder: object, **values: object) -> dict:
    state = _load_state(folder) | values
    _state_path(folder).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def _dem_elevations(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    """The land surface at each station, from the lidar."""
    from pyproj import Transformer

    from ofag.formats.raster import sample_elevation

    east, north = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(
        np.asarray(longitude, dtype=float), np.asarray(latitude, dtype=float)
    )
    return sample_elevation(DEM, east, north, crs=CRS, elevation_unit="m")


def _report_terrain(name: str, released: np.ndarray, sampled: np.ndarray) -> None:
    """A12's two numbers for both surfaces, and what they cost against each other."""
    from ofag.agent.gates import measure_terrain, refuse_unmeasured_terrain

    ground = {
        f"{name} as released": measure_terrain(
            name, released, source="the release's whole-foot table, a contour readoff"
        ),
        f"{name} from the lidar": measure_terrain(
            name, sampled, source="3DEP 1 m bare earth, bilinear at each station"
        ),
    }
    staircase = set(refuse_unmeasured_terrain(ground))
    for label, terrain in ground.items():
        note = "  <- mostly its own quantum" if label in staircase else ""
        print(f"          {terrain.summary}{note}")
    offset = float(np.median(sampled - released))
    print(
        f"          the lidar sits {offset:+.2f} m from the table; detrended they differ "
        f"by {np.std(sampled - released - offset):.2f} m rms"
    )


def _electrode_elevations(profile: int) -> dict[float, float]:
    """Surface elevation at each along-line position."""
    table = np.genfromtxt(ERT / "electrodes_xyz.txt", delimiter="\t", names=True, encoding="utf-8")
    keep = table["ERT_Profile_ID"] == profile
    sampled = _dem_elevations(table["Latitude"][keep], table["Longitude"][keep])
    _report_terrain(f"ERT{profile}", table["Surface_Elevation_meters_above_NAVD88"][keep], sampled)
    return dict(zip(np.round(table["Profile_x_Coordinate_meters"][keep], 3), sampled, strict=True))


def _released_elevations(profile: int) -> dict[float, float]:
    """The release's separate electrode table, which is its second statement."""
    table = np.genfromtxt(ERT / "electrodes_xyz.txt", delimiter="\t", names=True, encoding="utf-8")
    keep = table["ERT_Profile_ID"] == profile
    return dict(
        zip(
            np.round(table["Profile_x_Coordinate_meters"][keep], 3),
            table["Surface_Elevation_meters_above_NAVD88"][keep],
            strict=True,
        )
    )


def _elevation_copies(profile: int, survey: object) -> "Copies | None":
    """Difference the release's two statements of the surface, and settle them."""
    from ofag.agent.duplicates import NEITHER, difference, refuse_unresolved

    block = survey.topography_m  # type: ignore[attr-defined]
    if block is None:
        return None
    released = _released_elevations(profile)
    positions = np.fromiter(released, dtype=float)
    # Match stations by position.
    at = {round(float(x), 3): float(z) for x, z in zip(block[:, 0], block[:, 1], strict=True)}
    missing = [x for x in positions if round(x, 3) not in at]
    if missing:
        raise SystemExit(f"profile {profile}: the block has no elevation at x = {missing[:5]}")
    copies = difference(
        f"surface elevation, ERT{profile}",
        np.array([at[round(float(x), 3)] for x in positions]),
        np.fromiter(released.values(), dtype=float),
        unit="m",
        first_from="the .dat's own topography block",
        second_from="electrodes_xyz.txt",
        agree_within=ELEVATION_DISAGREEMENT_M,
    )
    return refuse_unresolved(copies, took=NEITHER, because=ELEVATION_RESOLVED_BY)


#: What settled the release's two elevation lists, once neither turned out to
#: be the surface. Quoted into the gate so the criterion lives beside the
#: choice rather than in a paragraph somewhere above it.
ELEVATION_RESOLVED_BY = (
    "1 m bare-earth lidar and the 1/3 arc-second DEM agree with each other to 6 cm at these "
    "stations and both sit 2.4 to 2.7 m above the table with three quarters of its relief, "
    "which is the eight feet the two lists differ by"
)


def import_ert() -> None:
    """Read both RES2DINV profiles, with the elevations the release gives."""
    from ofag.formats.res2dinv import read_res2dinv
    from ofag.services.import_store import ImportStore

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    store = ImportStore(Path(folder.imports_root))  # type: ignore[attr-defined]

    imported = []
    print(
        f"import    {'profile':10s} {'n':>5s} {'elec':>5s} "
        f"{'relief':>7s} {'K*R<=0':>7s} {'rho med':>8s}"
    )
    for profile in (1, 2):
        survey = read_res2dinv(ERT / f"ert{profile}_input.dat")
        if survey.values.size != survey.declared_measurements:
            raise SystemExit(
                f"profile {profile}: parsed {survey.values.size} of "
                f"{survey.declared_measurements} declared measurements"
            )
        elevations = _electrode_elevations(profile)
        copies = _elevation_copies(profile, survey)
        missing = [x for x in np.round(survey.electrodes_m[:, 0], 3) if x not in elevations]
        if missing:
            raise SystemExit(f"profile {profile}: no elevation for x = {missing[:5]}")
        # The plugin wants (x, y, z); a 2D line has no y, and z is the surface.
        electrodes = np.column_stack(
            [
                survey.electrodes_m[:, 0],
                np.zeros(survey.electrodes_m.shape[0]),
                [elevations[x] for x in np.round(survey.electrodes_m[:, 0], 3)],
            ]
        )

        dataset_id, destination = store.new_dataset()
        np.save(destination / "electrodes_m.npy", electrodes)
        np.save(destination / "quadrupoles.npy", survey.quadrupoles)
        resistance = survey.resistance_ohm
        (destination / "observations_ohm.csv").write_text(
            "resistance_ohm\n" + "\n".join(f"{v:.10e}" for v in resistance) + "\n",
            encoding="utf-8",
        )
        apparent = survey.geometric_factor * resistance
        imported.append(
            {
                "profile": profile,
                "title": survey.title,
                "source": (ERT / f"ert{profile}_input.dat").as_posix(),
                "dataset_id": str(dataset_id),
                "electrodes_path": (destination / "electrodes_m.npy").as_posix(),
                "quadrupoles_path": (destination / "quadrupoles.npy").as_posix(),
                "observations_path": (destination / "observations_ohm.csv").as_posix(),
                "measurements": int(resistance.size),
                "electrodes": int(electrodes.shape[0]),
                "spacing_m": survey.electrode_spacing_m,
                "relief_m": float(np.ptp(electrodes[:, 2])),
                "non_positive_apparent": int((apparent <= 0).sum()),
                "elevation_source": ELEVATION_SOURCE,
                "released_lists_differ_by_m": copies.largest if copies else 0.0,
            }
        )
        print(
            f"          ERT{profile:<7d} {resistance.size:5d} {electrodes.shape[0]:5d} "
            f"{np.ptp(electrodes[:, 2]):6.2f}m {int((apparent <= 0).sum()):7d} "
            f"{np.median(apparent):7.1f}"
        )
        if copies is not None and not copies.agree:
            print(f"          {'':10s} {copies.summary}")
            print(f"          {'':10s} settled by neither: {ELEVATION_RESOLVED_BY[:96]}...")
    _save_state(folder, ert_imports=imported)
    print(f"\n          written under {folder.imports_root}")  # type: ignore[attr-defined]


def _resistance(item: dict) -> np.ndarray:
    return np.loadtxt(item["observations_path"], delimiter=",", skiprows=1)


def _uncertainty(item: dict) -> np.ndarray:
    """A declared relative error per measurement, with an absolute floor."""
    resistance = np.abs(_resistance(item))
    return np.maximum(ERT_RELATIVE_ERROR * resistance, ERT_ABSOLUTE_FLOOR_OHM)


def _run_spec(record: object, item: dict) -> RunSpec:
    from ofag.plugins.pygimli_ert import (
        ERTDataQualitySpec,
        ERTElectrodeArraySpec,
        ERTInversionSpec,
        ERTMeshSpec,
        ERTOptimizerSpec,
        ERTRegularizationSpec,
    )

    def ohm_m(value: float) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=QuantityType.RESISTIVITY, unit="ohm.m")

    name = f"ERT{item['profile']}"
    return RunSpec(
        plugin_id="pygimli.ert.dcip",
        plugin_version="0.1.0",
        engine="pygimli",
        project_id=record.project_id,  # type: ignore[attr-defined]
        label=f"Llano {name}, {item['measurements']} measurements",
        dataset=DatasetSpec(
            name=f"llano-{name.lower()}",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.TRANSFER_RESISTANCE,
            units="ohm",
        ),
        datasets=(
            DataChannelSpec(
                channel_id="dc",
                dataset=DatasetSpec(
                    name=f"llano-{name.lower()}-dc",
                    coordinate_convention=CoordinateConvention(crs=CRS),
                    physical_quantity=QuantityType.TRANSFER_RESISTANCE,
                    units="ohm",
                ),
                observations_path=item["observations_path"],
                data_uncertainty=QuantitySpec(
                    value=_uncertainty(item).tolist(),
                    quantity_type=QuantityType.TRANSFER_RESISTANCE,
                    unit="ohm",
                ),
            ),
        ),
        physics=ERTInversionSpec(
            array=ERTElectrodeArraySpec(
                electrodes_path=item["electrodes_path"],
                quadrupoles_path=item["quadrupoles_path"],
            ),
            mesh=ERTMeshSpec(
                dimension=2,
                depth=QuantitySpec(value=MESH_DEPTH_M, quantity_type=QuantityType.LENGTH, unit="m"),
            ),
            regularization=ERTRegularizationSpec(
                lam=ERT_LAMBDA,
                vertical_weight=ERT_VERTICAL_WEIGHT,
                lower_bound=ohm_m(RESISTIVITY_BOUNDS[0]),
                upper_bound=ohm_m(RESISTIVITY_BOUNDS[1]),
            ),
            optimizer=ERTOptimizerSpec(max_iterations=ERT_MAX_ITERATIONS),
            starting_resistivity=ohm_m(STARTING_RESISTIVITY),
            quality=ERTDataQualitySpec(drop_non_positive=DROP_NON_POSITIVE),
        ).model_dump(mode="json"),
    )


def invert_ert() -> None:
    """One 2D section per resistivity profile."""

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("ert_imports"):
        raise SystemExit("run import_ert first")

    done = dict(state.get("ert_runs") or {})
    for item in state["ert_imports"]:
        key = f"ERT{item['profile']}"
        spec = _run_spec(record, item)
        done[key] = _dispatch(folder, key, spec)
        _save_state(folder, ert_runs=done)


#: How many gates the transient sounding's walk is run on.
#:
#: Eight, out of seventy-one: enough to cross three of the five repetition
#: rates, so the walk goes through the merging as well as the inversion.
TDEM_WALK_GATES = 8


def _dispatch(folder: object, key: str, spec: RunSpec, smaller: RunSpec | None = None) -> str:
    """Take one run through the ledger, in this case's voice."""
    from ofag.agent.obligations import ObligationError
    from ofag.agent.session import GuardedRuns
    from ofag.services.run_service import RunService

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    guarded = GuardedRuns(runs)
    try:
        taken = guarded.take(spec, smaller)
    except (ObligationError, ValueError) as refusal:
        raise SystemExit(f"{key}: {refusal}") from refusal

    if taken.walk is not None:
        print(
            f"          {key:16s} {'walk':10s} {taken.walk.seconds:5.0f} s on a smaller spec, "
            f"{len(taken.walk.readable)} artifacts read back"
        )
    _wait(runs, spec.run_id, key)
    return str(spec.run_id)


def _wait(runs: object, run_id: object, label: str) -> None:
    import time

    started = time.time()
    while True:
        record = runs.get(run_id)  # type: ignore[attr-defined]
        if record.state.value in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"):
            result = runs.result(run_id) if record.state.value == "SUCCEEDED" else None  # type: ignore[attr-defined]
            summary = result.summary if result else {}
            chi = next(
                (
                    float(summary[name])
                    for name in ("chi_squared", "chi_squared_median")
                    if isinstance(summary.get(name), int | float)
                ),
                float("nan"),
            )
            print(
                f"          {label:16s} {record.state.value:10s} chi-squared {chi:7.3f}  "
                f"{time.time() - started:5.0f} s" + (f"  {record.error}" if record.error else "")
            )
            return
        time.sleep(5.0)


# -- seismic refraction -------------------------------------------------------

#: The traveltime a picking program writes when it has nothing to write.
#:
#: Not a guess. It appears exactly, to the last decimal, 14 times in SRT2,
#: always within a few stations of the shot -- where the
#: true arrival is shortest and hardest to pick -- and picks of 9.824 ms exist
#: beside it, so it is not an instrument floor. It is the default.
PICK_DEFAULT_S = 0.010

#: How far the earliest arrival in a gather may sit from its own shot before
#: the whole gather is rejected, in metres.
#:
#: Two station intervals. The first energy to reach a spread reaches the trace
#: nearest the source, so this distance is zero for a sound gather and one
#: interval for a gather whose near traces are defaulted. Eight of the nine
#: gathers in this release sit at 0 or 4 m. The ninth sits at 16.
GATHER_REJECT_M = 8.0

#: The refraction line that crosses both ERT profiles inside the model volume.
SRT_PROFILES = (2,)

#: The mesh and the regularization, shared by both profiles for the reason the
#: resistivity profiles share theirs.
SRT_MESH_DEPTH_M = 30.0
SRT_LAMBDA = 30.0
SRT_VERTICAL_WEIGHT = 0.5
SRT_SECONDARY_NODES = 3
SRT_MAX_ITERATIONS = 12

#: The gradient the inversion starts from, and the range it may not leave.
#: Weathered granite: the authors' own models run 0.22 to 1.59 km/s.
SRT_START_VELOCITY = (400.0, 3000.0)
SRT_VELOCITY_BOUNDS = (200.0, 6000.0)

#: Nothing in the ground carries a P wave slower than this. Set as a guard
#: rather than because it is needed: with the bad gather rejected it removes
#: nothing, and a filter that only runs when it is needed is one nobody has
#: checked.
SRT_MINIMUM_APPARENT_VELOCITY = 200.0


def _srt_geometry(profile: int) -> np.ndarray:
    """The 24 stations of one spread, as (x, 0, elevation) in metres."""
    table = np.genfromtxt(SRT / "geometry.txt", delimiter="\t", names=True, encoding="utf-8")
    keep = table["SRT_Profile_ID"] == profile
    x = table["Profile_x_Coordinate_meters"][keep]
    z = _dem_elevations(table["Latitude"][keep], table["Longitude"][keep])
    _report_terrain(f"SRT{profile}", table["Surface_Elevation_meters_above_NAVD88"][keep], z)
    order = np.argsort(x)
    return np.column_stack([x[order], np.zeros(order.size), z[order]])


def import_srt() -> None:
    """Read both pick files, reject what reciprocity and geometry condemn."""
    from ofag.agent.picks import refuse_unsound_picks
    from ofag.formats.seisimager import read_first_arrivals
    from ofag.services.import_store import ImportStore

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    store = ImportStore(Path(folder.imports_root))  # type: ignore[attr-defined]

    imported = []
    for profile in SRT_PROFILES:
        arrivals = read_first_arrivals(SRT / f"srt{profile}_first_arrivals.txt")
        if arrivals.parsed_shots != arrivals.declared_shots:
            raise SystemExit(
                f"SRT{profile}: parsed {arrivals.parsed_shots} of "
                f"{arrivals.declared_shots} declared shots"
            )
        sensors = _srt_geometry(profile)
        index = {round(float(x), 3): position for position, x in enumerate(sensors[:, 0])}

        # The measured error, which is the whole reason the shot-receiver pairing is
        # kept.
        left, right = arrivals.reciprocal_pairs()
        is_default = np.isclose(arrivals.traveltime_s, PICK_DEFAULT_S, atol=1e-9)
        measured = ~is_default[left] & ~is_default[right]
        left, right = left[measured], right[measured]
        difference = np.abs(arrivals.traveltime_s[left] - arrivals.traveltime_s[right])
        sigma = float(np.median(difference) / np.sqrt(2.0))

        misplaced = {
            shot
            for shot, distance in arrivals.earliest_arrival_offset_m.items()
            if distance > GATHER_REJECT_M
        }
        defaulted = np.isclose(arrivals.traveltime_s, PICK_DEFAULT_S, atol=1e-9)
        zero_offset = arrivals.offset_m == 0
        keep = ~defaulted & ~zero_offset & ~np.isin(arrivals.shot_x_m, list(misplaced))
        # The three lines above were right and were only here.
        unsound = refuse_unsound_picks(arrivals, keep, gather_tolerance_m=GATHER_REJECT_M)

        pairs = np.asarray(
            [
                [index[round(float(s), 3)], index[round(float(r), 3)]]
                for s, r in zip(arrivals.shot_x_m[keep], arrivals.receiver_x_m[keep], strict=True)
            ],
            dtype=np.int64,
        )
        dataset_id, destination = store.new_dataset()
        np.save(destination / "sensors_m.npy", sensors)
        np.save(destination / "shot_receiver.npy", pairs)
        (destination / "traveltime_s.csv").write_text(
            "traveltime_s\n" + "\n".join(f"{v:.10e}" for v in arrivals.traveltime_s[keep]) + "\n",
            encoding="utf-8",
        )
        imported.append(
            {
                "profile": profile,
                "source": (SRT / f"srt{profile}_first_arrivals.txt").as_posix(),
                "dataset_id": str(dataset_id),
                "sensors_path": (destination / "sensors_m.npy").as_posix(),
                "pairs_path": (destination / "shot_receiver.npy").as_posix(),
                "observations_path": (destination / "traveltime_s.csv").as_posix(),
                "picks": int(keep.sum()),
                "picks_read": int(arrivals.traveltime_s.size),
                "sigma_s": sigma,
                "reciprocal_pairs": int(left.size),
                "rejected_gathers": sorted(misplaced),
                "relief_m": float(np.ptp(sensors[:, 2])),
            }
        )
        print(
            f"import    SRT{profile}  {int(keep.sum()):3d} of {arrivals.traveltime_s.size} picks "
            f"kept on {len(sensors)} stations, relief {np.ptp(sensors[:, 2]):.2f} m"
        )
        print(
            f"          dropped {int(zero_offset.sum())} zero-offset, "
            f"{int(defaulted.sum())} at the {1e3 * PICK_DEFAULT_S:.0f} ms default"
            + (
                ", and every pick of the shot at x = "
                + ", ".join(f"{s:.0f}" for s in sorted(misplaced))
                + " m"
                if misplaced
                else ""
            )
        )
        print(
            f"          measured error from {left.size} reciprocal pairs: "
            f"sigma = {1e3 * sigma:.2f} ms"
            + (
                f" (worst pair disagrees by {1e3 * difference.max():.1f} ms)"
                if difference.size
                else ""
            )
        )
        if not unsound.sound or unsound.zero_offset:
            print(f"          {unsound.summary}")
    _save_state(folder, srt_imports=imported)


def _srt_run_spec(record: object, item: dict) -> RunSpec:
    def quantity(value: float, kind: QuantityType, unit: str) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=kind, unit=unit)

    velocity = QuantityType.P_WAVE_VELOCITY
    name = f"SRT{item['profile']}"
    dataset = DatasetSpec(
        name=f"llano-{name.lower()}",
        coordinate_convention=CoordinateConvention(crs=CRS),
        physical_quantity=QuantityType.TRAVELTIME,
        units="s",
    )
    return RunSpec(
        plugin_id="pygimli.seismic.traveltime",
        plugin_version="0.1.0",
        engine="pygimli",
        project_id=record.project_id,  # type: ignore[attr-defined]
        label=f"Llano {name}, {item['picks']} picks",
        dataset=dataset,
        datasets=(
            DataChannelSpec(
                channel_id="traveltime",
                dataset=dataset,
                observations_path=item["observations_path"],
                # Absolute, in seconds, and measured rather than declared.
                data_uncertainty=quantity(item["sigma_s"], QuantityType.TRAVELTIME, "s"),
            ),
        ),
        physics={
            "array": {
                "sensors_path": item["sensors_path"],
                "shot_receiver_path": item["pairs_path"],
            },
            "mesh": {
                "dimension": 2,
                "depth": quantity(SRT_MESH_DEPTH_M, QuantityType.LENGTH, "m").model_dump(
                    mode="json"
                ),
                "secondary_nodes": SRT_SECONDARY_NODES,
            },
            "regularization": {
                "lam": SRT_LAMBDA,
                "vertical_weight": SRT_VERTICAL_WEIGHT,
                "lower_velocity": quantity(SRT_VELOCITY_BOUNDS[0], velocity, "m/s").model_dump(
                    mode="json"
                ),
                "upper_velocity": quantity(SRT_VELOCITY_BOUNDS[1], velocity, "m/s").model_dump(
                    mode="json"
                ),
            },
            "starting_model": {
                "use_gradient": True,
                "top_velocity": quantity(SRT_START_VELOCITY[0], velocity, "m/s").model_dump(
                    mode="json"
                ),
                "bottom_velocity": quantity(SRT_START_VELOCITY[1], velocity, "m/s").model_dump(
                    mode="json"
                ),
            },
            "optimizer": {"max_iterations": SRT_MAX_ITERATIONS},
            "quality": {
                "drop_zero_offset": True,
                "minimum_apparent_velocity": quantity(
                    SRT_MINIMUM_APPARENT_VELOCITY, velocity, "m/s"
                ).model_dump(mode="json"),
            },
        },
    )


def invert_srt() -> None:
    """One velocity section per refraction profile."""

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("srt_imports"):
        raise SystemExit("run import_srt first")

    # Rebuilt from the imports rather than merged into, so a profile dropped from
    # SRT_PROFILES does not leave its old run behind in the state.
    done = {}
    for item in state["srt_imports"]:
        key = f"SRT{item['profile']}"
        spec = _srt_run_spec(record, item)
        done[key] = _dispatch(folder, key, spec)
        _save_state(folder, srt_runs=done)


# -- the transient sounding ---------------------------------------------------

#: Where the transmitter loop was, in UTM 14N, and how it was arrived at.
#:
#: The `.usf` declares neither a location nor a z direction, which is why both
#: are passed in rather than defaulted (F029, F001). The position is the centre
#: of the 100 by 100 m loop: the self-potential survey inside it is gridded
#: 0-100 m in both directions with latitude and longitude at every one of its
#: 437 stations, so an affine fit of that grid to UTM places local (50, 50) to
#: within a median 1.4 m.
#:
#: That puts the loop centre **0.6 m from ERT2 at x = 60 m and 2.3 m from
#: SRT2 at x = 48 m** -- on the same ground as the crossing the other two
#: methods already share, which is what makes a three-method comparison
#: possible at all here.
LOOP_CENTRE_M = (559150.61, 3390953.70, 291.74)
LOOP_Z_DIRECTION = "DOWN"

#: One gate, one measurement. The five sweeps are five repetition rates rather
#: than five repeats, so there is no scatter to stack and the instrument's own
#: per-gate error bar is the uncertainty. It runs from 0.1 per cent at the
#: earliest gates to 22 per cent at the latest, which is the shape an error
#: should have and a single declared percentage would not.
TDEM_MINIMUM_REPEATS = 1

#: What the `.usf`'s declared turn-off ramps have to be multiplied by.
#:
#: The file says 5.1e-9 s for the 1.5 A sweeps and 2.7e-8 s for the 9.5 A ones.
#: The loop is 100 by 100 m -- about 0.73 mH -- so switching 1.5 A out of it
#: takes microseconds at any transmitter voltage, and the IX1D project for this
#: same sounding holds 5.1 us and 27 us. A thousandfold slip of unit, uniform
#: across every sweep, so one factor corrects it.
#:
#: It is not cosmetic. At the declared value the import's earliest-gate rule
#: compares the gates against 1.53e-8 s and drops none of them; at the right
#: one it drops the first four of sweep 1, which sit inside the turn-off
#: transient and are not measurements of the ground (F054).
TDEM_RAMP_TIME_SCALE = 1000.0

#: The layered earth the sounding is inverted on: logarithmically thickening
#: from 1 m, which is how a diffusive method's resolution falls with depth.
TDEM_LAYER_COUNT = 25
TDEM_FIRST_LAYER_M = 1.0
TDEM_LAST_LAYER_M = 20.0

#: The starting halfspace and the range the inversion may not leave. The ERT
#: at this point reads 54 to 288 ohm.m over the top 25 m, so 100 ohm.m --
#: 0.01 S/m -- starts between them without being either.
TDEM_START_CONDUCTIVITY = 0.01
TDEM_CONDUCTIVITY_BOUNDS = (1e-4, 1.0)

#: What counts as fitted.
#: A floor under the stated error bar, as a fraction of the reading.
#:
#: Measured, not declared, and it is a different quantity from the bar the
#: file states. That bar is stacking repeatability inside one repetition rate
#: and reaches 0.03 per cent at the early gates; read as an accuracy it claims
#: the ground is known to three parts in ten thousand.
#:
#: The five rates overlap in time, so where two of them measured within two
#: per cent of the same moment their disagreement is everything the stated bar
#: leaves out -- gain, geometry, drift, and the one-dimensional assumption.
#: Fifteen such pairs differ by a median of 5.8 per cent, which over root two
#: is 4.1 per cent on one reading. This is the sounding's version of what
#: reciprocity gave the refraction lines (A4).
TDEM_MEASURED_ERROR = 0.041

TDEM_ACCEPTABLE_CHI_SQUARED = 2.0


def _tdem_layers() -> np.ndarray:
    """Layer thicknesses, thickening logarithmically with depth."""
    return np.geomspace(TDEM_FIRST_LAYER_M, TDEM_LAST_LAYER_M, TDEM_LAYER_COUNT)


def import_tdem() -> None:
    """Read the sounding, with the two things its file does not declare."""
    from ofag.core.schemas import CoordinateConvention as Convention
    from ofag.services.tem_import import TemImportRequest, TemImportService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    imported = TemImportService(import_root=Path(folder.imports_root)).import_usf_directory(  # type: ignore[attr-defined]
        TemImportRequest(
            source_directory=TDEM.as_posix(),
            coordinate_convention=Convention(crs=CRS),
            default_location_m=LOOP_CENTRE_M,
            default_z_direction=LOOP_Z_DIRECTION,
            minimum_repeats=TDEM_MINIMUM_REPEATS,
            declared_ramp_time_scale=TDEM_RAMP_TIME_SCALE,
        )
    )
    # Five repetition rates over one loop at one place, so they are one sounding
    # measured five ways rather than five soundings.
    curves = sorted(imported.curves, key=lambda c: c.times_s.min())
    times = np.concatenate([c.times_s for c in curves])
    values = np.concatenate([c.values for c in curves])
    uncertainty = np.concatenate([c.uncertainty for c in curves])
    order = np.argsort(times)
    times, values, uncertainty = times[order], values[order], uncertainty[order]

    destination = Path(folder.imports_root) / str(imported.dataset_id)  # type: ignore[attr-defined]
    observations = destination / "tdem_dbdt.csv"
    observations.write_text(
        "time_s,magnetic_flux_density_time_derivative_t_s\n"
        + "\n".join(f"{t:.10e},{v:.10e}" for t, v in zip(times, values, strict=True))
        + "\n",
        encoding="utf-8",
    )
    np.save(destination / "tdem_times_s.npy", times)
    np.save(destination / "tdem_uncertainty.npy", uncertainty)

    slope = np.diff(np.log(np.abs(values))) / np.diff(np.log(times))
    _save_state(
        folder,
        tdem_import={
            "dataset_id": str(imported.dataset_id),
            "observations_path": observations.as_posix(),
            "times_path": (destination / "tdem_times_s.npy").as_posix(),
            "uncertainty_path": (destination / "tdem_uncertainty.npy").as_posix(),
            "gates": int(times.size),
            "loop_radius_m": float(curves[0].loop_radius_m),
            "configurations": [c.configuration_id for c in curves],
            "location_m": list(LOOP_CENTRE_M),
        },
    )
    print(
        f"import    TDEM  {times.size} gates over {len(curves)} repetition rates, "
        f"t {times.min() * 1e6:.2f} to {times.max() * 1e6:.0f} us, "
        f"equal-area loop radius {curves[0].loop_radius_m:.1f} m"
    )
    print(
        f"          stated error {100 * np.median(np.abs(uncertainty / values)):.1f}% median, "
        f"{100 * np.abs(uncertainty / values).min():.1f}% to "
        f"{100 * np.abs(uncertainty / values).max():.0f}%"
    )
    print(
        f"          merged decay has a log-log slope of {np.median(slope):.2f}, against the "
        f"-2.5 a late-time layered decay wants"
    )


def _tdem_run_spec(record: object, item: dict) -> RunSpec:
    times = np.load(item["times_path"])
    uncertainty = np.load(item["uncertainty_path"])
    radius = item["loop_radius_m"]
    observed = np.loadtxt(item["observations_path"], delimiter=",", skiprows=1)[:, 1]
    # The larger of what the instrument stated and what the rates disagree by.
    floor = np.maximum(np.abs(uncertainty), TDEM_MEASURED_ERROR * np.abs(observed))

    def quantity(value: object, kind: QuantityType, unit: str) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=kind, unit=unit)

    rate = QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE
    dataset = DatasetSpec(
        name="llano-tdem",
        coordinate_convention=CoordinateConvention(crs=CRS),
        physical_quantity=rate,
        units="T/s",
    )
    return RunSpec(
        plugin_id="simpeg.aem.tdem1d",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        label=f"Llano TDEM, {item['gates']} gates",
        dataset=dataset,
        # This plugin takes its data through `parameters` rather than a data channel,
        # which is the older of the two forms the project supports.
        parameters={
            "observations_path": item["observations_path"],
            # The instrument's own error bar, per gate, absolute.
            "data_uncertainty": quantity(floor.tolist(), rate, "T/s").model_dump(mode="json"),
        },
        physics={
            "system": {
                "times": quantity(times.tolist(), QuantityType.TIME, "s").model_dump(mode="json"),
                "source_location": quantity([0.0, 0.0, 0.0], QuantityType.LENGTH, "m").model_dump(
                    mode="json"
                ),
                "receiver_location": quantity([0.0, 0.0, 0.0], QuantityType.LENGTH, "m").model_dump(
                    mode="json"
                ),
                "source_radius": quantity(radius, QuantityType.LENGTH, "m").model_dump(mode="json"),
                # One amp, because the import divided the transmitter current out of
                # every gate and the data is now T/s per amp.
                "source_current": quantity(1.0, QuantityType.ELECTRIC_CURRENT, "A").model_dump(
                    mode="json"
                ),
                # A step off, because the declared ramps are 5 and 27 nanoseconds
                # against a first gate at 6.81 microseconds -- 250 ramps later at worst.
                "waveform": "step_off",
                "receiver_quantity": "magnetic_flux_density_time_derivative",
            },
            "earth": {
                "layer_thicknesses": quantity(
                    _tdem_layers().tolist(), QuantityType.LENGTH, "m"
                ).model_dump(mode="json"),
            },
            "model": {
                "initial_conductivity": quantity(
                    TDEM_START_CONDUCTIVITY, QuantityType.CONDUCTIVITY, "S/m"
                ).model_dump(mode="json"),
                "lower_bound": quantity(
                    TDEM_CONDUCTIVITY_BOUNDS[0], QuantityType.CONDUCTIVITY, "S/m"
                ).model_dump(mode="json"),
                "upper_bound": quantity(
                    TDEM_CONDUCTIVITY_BOUNDS[1], QuantityType.CONDUCTIVITY, "S/m"
                ).model_dump(mode="json"),
            },
            "optimizer": {"max_iterations": 20},
        },
    )


def _tdem_sample_spec(record: object, item: dict) -> RunSpec:
    """The sounding on its first few gates, for the walk."""
    times = np.load(item["times_path"])[:TDEM_WALK_GATES]
    uncertainty = np.load(item["uncertainty_path"])[:TDEM_WALK_GATES]
    observed = np.loadtxt(item["observations_path"], delimiter=",", skiprows=1)[:TDEM_WALK_GATES]
    destination = Path(item["observations_path"]).with_name("tdem_dbdt_walk.csv")
    destination.write_text(
        "time_s,magnetic_flux_density_time_derivative_t_s\n"
        + "\n".join(f"{t:.10e},{v:.10e}" for t, v in zip(times, observed[:, 1], strict=True))
        + "\n",
        encoding="utf-8",
    )
    walk_times = destination.with_name("tdem_times_walk.npy")
    walk_error = destination.with_name("tdem_uncertainty_walk.npy")
    np.save(walk_times, times)
    np.save(walk_error, uncertainty)
    smaller = dict(
        item,
        observations_path=destination.as_posix(),
        times_path=walk_times.as_posix(),
        uncertainty_path=walk_error.as_posix(),
        gates=int(times.size),
    )
    return _tdem_run_spec(record, smaller)


def invert_tdem() -> None:
    """One layered model under the loop centre."""

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("tdem_import"):
        raise SystemExit("run import_tdem first")
    spec = _tdem_run_spec(record, state["tdem_import"])
    walk = _tdem_sample_spec(record, state["tdem_import"])
    _save_state(folder, tdem_run=_dispatch(folder, "TDEM", spec, smaller=walk))


# -- the holes ----------------------------------------------------------------

FEET_TO_M = 0.3048

#: The water table, in metres below ground, from well A's hydrograph.
#:
#: Read rather than inverted, and it is the one depth in this case that no
#: geophysics had to produce. The release's own stated purpose was to see
#: whether the transient sounding and the refraction could map it.
WATER_TABLE_M = 15.5

#: What borehole D's log actually says, against what one line of it says.
#:
#: "Augur refusal at 7.5-8.0 ft" is 2.3 m and was read here twice as the base
#: of weathering before the next two rows were read: a smaller auger goes in,
#: the colour changes, and from 9 to 24 ft it is "GGA soft and fast cutting".
#: The refusal is a cemented horizon inside the granite gravel with soft
#: aquifer under it, not bedrock (F040).
HARD_HORIZON_FT = (7.0, 9.0)
HOLE_BOTTOM_FT = 24.0


def wells() -> None:
    """What the holes say, and what the release says about the seismic."""
    import csv

    with (WELLS / "borehole_D_log.txt").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="	"))

    print(f"{'borehole D':16s} {'from':>7s} {'to':>7s}  unit")
    for row in rows:
        top = float(row["Topd_Depth_feet"]) * FEET_TO_M
        bottom = float(row["Bottom_Depth_feet"]) * FEET_TO_M
        remark = (row.get("Notes") or "").strip()
        print(
            f"{'':16s} {top:6.2f}m {bottom:6.2f}m  {row['Horizon']}"
            + (f"   {remark[:64]}" if remark else "")
        )
    deepest = float(rows[-1]["Bottom_Depth_feet"]) * FEET_TO_M
    first = float(rows[1]["Topd_Depth_feet"]) * FEET_TO_M
    print()
    print(
        f"{'':16s} one unit from {first:.2f} m to {deepest:.2f} m. The refusal at "
        f"{HARD_HORIZON_FT[0] * FEET_TO_M:.2f} to {HARD_HORIZON_FT[1] * FEET_TO_M:.2f} m is a "
        f"hard horizon inside it, drilled through."
    )
    print(
        f"{'':16s} well A puts the water table at {WATER_TABLE_M:.1f} m below ground, and it "
        f"is the only depth in this case no inversion produced."
    )
    print()
    print(f"{'':16s} the release's own metadata says the seismic 'may be subject to erroneous")
    print(f"{'':16s} depths ... because of the presence of velocity inversions within the")
    print(f"{'':16s} aquifer, which were confirmed by observation and drilling in borehole D'.")
    print(f"{'':16s} A refraction survey cannot see beneath a layer slower than the one above")
    print(f"{'':16s} it, and the hard horizon this log records is that layer.")


# -- the model ----------------------------------------------------------------

#: The volume, as UTM 14N bounds and a cell size.
#:
#: Taken from where the instruments actually stood, with a margin of one cell,
#: rather than from the release's "100-metre by 100-m survey area": the
#: resistivity lines are 188 m long and the site spans 276 by 175 m (F037 of
#: case 1's kind -- a stated extent that the coordinates contradict).
MODEL_CELL_M = (5.0, 5.0, 1.0)
MODEL_DEPTH_M = 40.0
MODEL_MARGIN_M = 10.0

#: The depth grid every section is resampled onto before it becomes columns.
COLUMN_DEPTHS_M = np.arange(0.0, MODEL_DEPTH_M, 1.0)

#: How far apart the two resistivity methods may read the same ground before
#: the model stops treating them as one measurement, as a ratio.
#:
#: They are checked rather than assumed to agree, on the one column where the
#: sounding, a resistivity line and a refraction line all stand within 2.3 m.
#: In the top 6 m the two read 67 against 91, 78 against 34 and 97 against 79
#: ohm.m -- ratios of 1.35, 0.44 and 0.81. Below that they part systematically,
#: reaching 2.3 by 16 m, which is where the resistivity lines are running out
#: of coverage and their values are being pulled back toward the starting
#: model. A factor of two is the line between the two regimes.
METHODS_AGREE_WITHIN = 2.0

#: Above this the ground is fresh Town Mountain Granite rather than the gravel
#: weathered out of it.
#:
#: Declared, and a cut through a gradational body. The current recovered
#: sounding rises from 22.7 ohm.m at the top through 779 at 12.9 m and
#: 956.9 at 15.6 m, so 800 is a declared cut across two fitted layers rather
#: than an independently resolved geological contact.
#: Nothing here resolves a contact; this is a line drawn at a stated value,
#: and the share below is a share of that line.
GRANITE_OHM_M = 800.0

#: How far from the sounding the granite top may be claimed.
#:
#: One sounding, so this is the only number standing between a point
#: measurement and a surface drawn across the whole site. Half the transmitter
#: loop's side: inside that the loop's own footprint is the measurement, and
#: outside it nothing was measured at all.
TDEM_REACH_M = 50.0

#: How far from a resistivity line a cell may be before no unit is claimed.
#: The two lines cross, so the covered ground is an X rather than an area, and
#: this is what makes the model say so instead of filling the corners.
ERT_REACH_M = 25.0

#: Where the sounding stops resolving, below ground.
#:
#: Stated rather than derived, and the shallower of what a 100 m loop can
#: reach and what the layer thicknesses can express.
TDEM_RESOLVED_M = 60.0

#: How far a cell's coverage may fall below the best cell's before the line is
#: read as having stopped resolving. Two decades, the same bar the plugin's
#: summary counts covered cells at.
#:
#: It sits on a slope and the slope is steep, which is the number to read
#: beside it. The deepest cell still above the cut, on the two profiles:
#:
#:     drop      1.5     2.0     2.5     3.0
#:     ERT1      7.6    13.9    25.2    36.2  m
#:     ERT2      7.1    17.2    32.5    42.6  m
#:
#: Half a decade is eleven metres of claimed aquifer, so the resistivity's
#: share of the volume is this constant as much as it is the data. Anything
#: read off that share has to carry the sensitivity with it.
#:
#: This is wrong if a second method ever reaches the same ground and disagrees
#: about where the resistivity stops being resolved, which would make the
#: cutoff measurable instead of declared.
ERT_COVERAGE_DROP = 2.0


def _line_columns(profile: int, run_key: str, table: str) -> "LayeredSection":
    """One 2D section resampled into a column under each sensor."""
    from ofag.services.interpretation_service import LayeredSection

    projects, record = _project()
    state = _load_state(projects.folder(record.project_id))  # type: ignore[attr-defined]
    directory = Path(RESULT_ROOT) / PROJECT_NAME.replace(" ", "-") / "runs" / state[table][run_key]
    geometry = np.load(directory / "mesh_geometry.npz")
    model = np.load(directory / "recovered_model.npy")
    cell_x = geometry["cell_centers_m"][:, 0]
    # A 2D pyGIMLi mesh carries elevation in its second column and leaves the third at
    # zero, which is the trap a reader of these files has to know.
    cell_z = geometry["cell_centers_m"][:, 1]

    easting, northing, along, surface = _sensor_positions(profile, table)
    values = np.empty((easting.size, COLUMN_DEPTHS_M.size))
    for index, (x, top) in enumerate(zip(along, surface, strict=True)):
        near = np.abs(cell_x - x) <= 4.0
        for layer, depth in enumerate(COLUMN_DEPTHS_M):
            band = near & (np.abs((top - cell_z) - depth) <= 1.0)
            values[index, layer] = np.median(model[band]) if band.any() else np.nan
    return LayeredSection(
        easting_m=easting,
        northing_m=northing,
        values=values,
        layer_top_depth_m=COLUMN_DEPTHS_M,
    )


def _sensor_positions(profile: int, table: str) -> tuple[np.ndarray, ...]:
    """Where one line's sensors are, in UTM and along the line."""
    from pyproj import Transformer

    if table == "ert_runs":
        source = np.genfromtxt(
            ERT / "electrodes_xyz.txt", delimiter="\t", names=True, encoding="utf-8"
        )
        keep = source["ERT_Profile_ID"] == profile
    else:
        source = np.genfromtxt(SRT / "geometry.txt", delimiter="\t", names=True, encoding="utf-8")
        keep = source["SRT_Profile_ID"] == profile
    transformer = Transformer.from_crs("EPSG:4269", CRS, always_xy=True)
    easting, northing = transformer.transform(source["Longitude"][keep], source["Latitude"][keep])
    along = source["Profile_x_Coordinate_meters"][keep]
    from ofag.formats.raster import sample_elevation

    surface = sample_elevation(DEM, easting, northing, crs=CRS, elevation_unit="m")
    order = np.argsort(along)
    return (
        np.asarray(easting)[order],
        np.asarray(northing)[order],
        along[order],
        surface[order],
    )


def _tdem_column() -> "LayeredSection":
    """The sounding, as one column at the loop centre."""
    from ofag.services.interpretation_service import LayeredSection

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    directory = Path(folder.runs_root) / state["tdem_run"]  # type: ignore[attr-defined]
    conductivity = np.load(directory / "recovered_conductivity_s_m.npy")
    top = np.load(directory / "layer_top_depth_m.npy")
    layer = np.clip(np.searchsorted(top, COLUMN_DEPTHS_M, side="right") - 1, 0, len(top) - 1)
    resistivity = (1.0 / conductivity)[layer]
    centre = state["tdem_import"]["location_m"]
    return LayeredSection(
        easting_m=np.array([centre[0]]),
        northing_m=np.array([centre[1]]),
        values=resistivity.reshape(1, -1),
        layer_top_depth_m=COLUMN_DEPTHS_M,
    )


def _ert_resolved_depth(profile: int, coverage_drop: float = ERT_COVERAGE_DROP) -> float:
    """The deepest cell one resistivity line still has sensitivity in."""
    projects, record = _project()
    state = _load_state(projects.folder(record.project_id))  # type: ignore[attr-defined]
    directory = (
        Path(RESULT_ROOT)
        / PROJECT_NAME.replace(" ", "-")
        / "runs"
        / state["ert_runs"][f"ERT{profile}"]
    )
    geometry = np.load(directory / "mesh_geometry.npz")
    coverage = np.load(directory / "model_coverage.npy")
    _, _, along, surface = _sensor_positions(profile, "ert_runs")
    top = np.interp(geometry["cell_centers_m"][:, 0], along, surface)
    depth = top - geometry["cell_centers_m"][:, 1]
    return float(depth[coverage > coverage.max() - coverage_drop].max())


def _joined(*sections: "LayeredSection") -> "LayeredSection":
    """Several lines of one method, as the one section that method is."""
    from ofag.services.interpretation_service import LayeredSection

    return LayeredSection(
        easting_m=np.concatenate([s.easting_m for s in sections]),
        northing_m=np.concatenate([s.northing_m for s in sections]),
        values=np.vstack([s.values for s in sections]),
        layer_top_depth_m=sections[0].layer_top_depth_m,
    )


def _methods_agree(resistivity: "LayeredSection", sounding: "LayeredSection") -> dict:
    """How far the two resistivity methods are from each other, where both reach."""
    from scipy.spatial import cKDTree

    near = cKDTree(resistivity.stations_m).query(sounding.stations_m)[0] <= ERT_REACH_M
    if not near.any():
        return {"compared": 0, "same_side": float("nan"), "median_ratio": float("nan")}
    nearest = cKDTree(resistivity.stations_m).query(sounding.stations_m)[1][near]
    line = resistivity.values[nearest][0]
    column = sounding.values[near][0]
    both = np.isfinite(line) & np.isfinite(column) & (COLUMN_DEPTHS_M <= _ert_resolved_depth(2))
    if not both.any():
        return {"compared": 0, "same_side": float("nan"), "median_ratio": float("nan")}
    same = (line[both] > GRANITE_OHM_M) == (column[both] > GRANITE_OHM_M)
    return {
        "compared": int(both.sum()),
        "same_side": float(same.mean()),
        "median_ratio": float(np.median(column[both] / line[both])),
    }


#: Runs that missed their bar and are read into the model anyway, each with
#: the diagnosis that earns it.
#:
#: A diagnosis rather than a sentence, because the two runs that miss here are
#: not the same kind of thing and a sentence would record them as though they
#: were. ERT1 is a line that is wrong in two places. The sounding, which the
#: model does read for its granite, fits its data about as well as the data
#: agrees with itself.
#:
#: The alternative for ERT1 is to leave the line out, and that costs half the
#: resistivity coverage: the claimed share of the volume falls from 31 to
#: about 13 per cent, measured before the surface moved to the lidar.
#:
#: This is wrong if the misfit is ever traced to something that affects the
#: whole line rather than those stretches, or if the model comes to depend on
#: ERT1 over x = 0-12 or 64-76 m, where the readings it cannot explain are.
def _diagnoses() -> dict[str, "Diagnosis"]:
    from ofag.agent.diagnosis import Diagnosis, RuledOut

    return {
        "ERT1": Diagnosis(
            misfit=3.079,
            target=ERT_ACCEPTABLE_CHI_SQUARED,
            where=(
                "17 of 243 readings over 15 per cent, attributed to their four electrodes and "
                "falling in two groups at x = 0-12 and 64-76 m with one outlier at 168, while the "
                "median reading fits to 4.0 per cent -- inside the declared error"
            ),
            ruled_out=(
                RuledOut(
                    hypothesis="the terrain, which three sources state and no two agree on",
                    measurement="inverted the profile flat, on each of the release's two "
                    "elevation lists, and on 1 m lidar",
                    result="3.074 flat, 3.090 on the table, 3.165 on the embedded block, 3.079 "
                    "on the lidar: flat is still marginally the best of the four",
                ),
                RuledOut(
                    hypothesis="the model norm, since the authors used robust L1 constraints",
                    measurement="inverted with blocky L1 and again with robust data, and scored "
                    "inside x = 48-76 m where the authors' 912 ohm.m is read, not over the "
                    "whole line",
                    result="blocky L1 nearly doubles that window -- 151 to 263 ohm.m median, "
                    "312 to 619 maximum -- and takes chi squared from 3.079 to 2.703. It is "
                    "ruled out as the whole explanation and not as a factor",
                ),
                RuledOut(
                    hypothesis="the smoothing strength, which trades misfit for structure",
                    measurement="swept lambda from 50 down to 2",
                    result="4.31, 3.09, 2.73, 2.49, 2.33 -- monotonic, and never reaching the bar",
                ),
            ),
            remaining=(
                "the two-dimensional assumption: a compact body near x = 64-76 m, off the line "
                "or too small for a smooth section to hold. The survey has no second "
                "measurement over that ground, so this case cannot test it"
            ),
        ),
    }


def _refuse_unfitted_runs(folder: object, state: dict) -> None:
    """Refuse to read a run into geology unless it fit, or someone said why."""
    from uuid import UUID

    from ofag.agent.gates import refuse_unfitted
    from ofag.services.run_service import RunService

    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    misfits: dict[str, float | None] = {}
    bars: dict[str, float] = {}
    for table, bar in (
        ("ert_runs", ERT_ACCEPTABLE_CHI_SQUARED),
        ("srt_runs", SRT_ACCEPTABLE_CHI_SQUARED),
    ):
        for key, run_id in (state.get(table) or {}).items():
            result = runs.result(UUID(run_id))
            chi = (result.summary if result else {}).get("chi_squared")
            misfits[key] = float(chi) if isinstance(chi, int | float) else None
            bars[key] = bar

    diagnoses = _diagnoses()
    for key in refuse_unfitted(misfits, bars, diagnoses):
        print(f"          {key} did not fit and is used anyway.")
        print(f"          {diagnoses[key].summary[:150]}")


def build_model() -> None:
    """Two units and the ground where neither is claimed."""
    from scipy.spatial import cKDTree

    from ofag.agent.gates import refuse_unstated_reach
    from ofag.core.schemas import UnitRule, UnitRuleKind
    from ofag.services.interpretation_service import InterpretationService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    for needed in ("ert_runs", "tdem_run"):
        if not state.get(needed):
            raise SystemExit(f"run the stage that produces {needed} first")
    _refuse_unfitted_runs(folder, state)

    # Both lines, as one section.
    resistivity = _joined(
        _line_columns(1, "ERT1", "ert_runs"), _line_columns(2, "ERT2", "ert_runs")
    )
    sounding = _tdem_column()
    stations = resistivity.stations_m

    east = np.arange(
        stations[:, 0].min() - MODEL_MARGIN_M,
        stations[:, 0].max() + MODEL_MARGIN_M,
        MODEL_CELL_M[0],
    )
    north = np.arange(
        stations[:, 1].min() - MODEL_MARGIN_M,
        stations[:, 1].max() + MODEL_MARGIN_M,
        MODEL_CELL_M[1],
    )
    down = np.arange(0.0, MODEL_DEPTH_M, MODEL_CELL_M[2]) + MODEL_CELL_M[2] / 2
    x, y = np.meshgrid(east, north, indexing="ij")
    columns = np.column_stack([x.ravel(), y.ravel()])
    from ofag.formats.raster import sample_elevation

    column_ground = sample_elevation(DEM, columns[:, 0], columns[:, 1], crs=CRS, elevation_unit="m")
    depth = np.tile(down, len(columns))
    ground = np.repeat(column_ground, len(down))
    centres = np.column_stack([np.repeat(columns, len(down), axis=0), ground - depth])
    volume = np.full(centres.shape[0], float(np.prod(MODEL_CELL_M)))

    # Where the sounding is the only thing that reaches, and how far it reaches.
    to_sounding = cKDTree(sounding.stations_m).query(centres[:, :2])[0]
    to_line = cKDTree(stations).query(centres[:, :2])[0]
    # How deep each line resolved, from its own coverage rather than from the depth of
    # its mesh.
    ert_depth = min(_ert_resolved_depth(1), _ert_resolved_depth(2))
    declared = refuse_unstated_reach(
        {
            "ERT1 and ERT2": (ert_depth, "measured from each run's own coverage array"),
            "TDEM": (TDEM_RESOLVED_M, "declared: nothing here computes a depth of investigation"),
        }
    )
    for name in declared:
        print(f"          {name}'s reach is declared rather than measured")
    resolved = np.where(to_sounding <= TDEM_REACH_M, TDEM_RESOLVED_M, 0.0)
    resolved = np.maximum(resolved, np.where(to_line <= ERT_REACH_M, ert_depth, 0.0))
    print(f"          the resistivity lines resolve to {ert_depth:.1f} m, from their coverage")

    # Order is a statement about which evidence is harder, and first match wins.
    rules = (
        UnitRule(
            name="nothing measured here",
            source="no method in reach",
            kind=UnitRuleKind.BELOW_SURFACE,
            surface="resolved",
        ),
        UnitRule(
            name="Town Mountain Granite",
            source="TDEM, one sounding",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="tdem",
            threshold=GRANITE_OHM_M,
            below_threshold=False,
            reach_m=TDEM_REACH_M,
        ),
        UnitRule(
            name="Granite Gravel Aquifer, by ERT",
            source="ERT1 and ERT2, a measured resistivity",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="ert",
            threshold=GRANITE_OHM_M,
            below_threshold=True,
            reach_m=ERT_REACH_M,
        ),
        UnitRule(
            name="Granite Gravel Aquifer, by TDEM",
            source="TDEM, beyond the lines",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="tdem",
            threshold=GRANITE_OHM_M,
            below_threshold=True,
            reach_m=TDEM_REACH_M,
        ),
        UnitRule(
            name="in the volume, out of reach",
            source="no section within reach",
            kind=UnitRuleKind.REMAINDER,
        ),
    )
    service = InterpretationService()
    model = service.assign_units(
        rules,
        cell_centres_m=centres,
        cell_volume_m3=volume,
        depth_below_ground_m=depth,
        surfaces={"resolved": ground - resolved},
        sections={"tdem": sounding, "ert": resistivity},
    )

    # These are alternative interpretations of the same finished inversions, not
    # posterior probabilities or another inversion.
    settings = np.array(
        [
            (threshold, radius, drop)
            for threshold in (600.0, GRANITE_OHM_M, 1000.0)
            for radius in (25.0, TDEM_REACH_M, 75.0)
            for drop in (1.5, ERT_COVERAGE_DROP, 2.5)
        ],
        dtype=float,
    )
    variants = np.empty((len(settings), len(depth)), dtype=np.uint8)
    for index, (threshold, radius, drop) in enumerate(settings):
        line_depth = min(_ert_resolved_depth(1, drop), _ert_resolved_depth(2, drop))
        variant_reach = np.maximum(
            np.where(to_sounding <= radius, TDEM_RESOLVED_M, 0.0),
            np.where(to_line <= ERT_REACH_M, line_depth, 0.0),
        )
        variant_rules = list(rules)
        variant_rules[1] = rules[1].model_copy(update={"threshold": threshold, "reach_m": radius})
        variant_rules[2] = rules[2].model_copy(update={"threshold": threshold})
        variant_rules[3] = rules[3].model_copy(update={"threshold": threshold, "reach_m": radius})
        variants[index] = service.assign_units(
            tuple(variant_rules),
            cell_centres_m=centres,
            cell_volume_m3=volume,
            depth_below_ground_m=depth,
            surfaces={"resolved": ground - variant_reach},
            sections={"tdem": sounding, "ert": resistivity},
        ).unit
    stability = np.mean(variants == model.unit, axis=0)
    sensitivity_path = Path(folder.imports_root) / "model_sensitivity.npz"  # type: ignore[attr-defined]
    np.savez_compressed(
        sensitivity_path,
        settings_threshold_ohm_m_reach_m_coverage_drop=settings,
        unit_by_setting=variants,
        agreement_with_baseline_fraction=stability,
        granite_frequency=np.mean(variants == 1, axis=0),
    )

    path = Path(folder.imports_root) / "geological_model.npz"  # type: ignore[attr-defined]
    np.savez_compressed(
        path,
        unit=model.unit,
        unit_names=np.array([rule.name for rule in rules]),
        unit_sources=np.array([rule.source for rule in rules]),
        cell_centres_m=centres,
        support_distance_m=model.support_distance_m,
        resolved_depth_m=resolved,
        ground_elevation_m=ground,
        report=json.dumps(model.report.model_dump(mode="json")),
    )
    _save_state(
        folder,
        geological_model_path=path.as_posix(),
        model_sensitivity_path=sensitivity_path.as_posix(),
    )

    print(
        f"build     {centres.shape[0]:,} cells over {np.ptp(east):.0f} by {np.ptp(north):.0f} m "
        f"to {MODEL_DEPTH_M:.0f} m, at {MODEL_CELL_M[0]:.0f} m across and "
        f"{MODEL_CELL_M[2]:.0f} m down"
    )
    print()
    print(f"          {'unit':26s} {'share':>7s} {'cells':>9s}  resolved by")
    for item in model.report.units:
        print(
            f"          {item.name:26s} {100 * item.volume_share:6.1f}% "
            f"{item.cell_count:9,d}  {item.source}"
        )
    print()
    agreement = _methods_agree(resistivity, sounding)
    print(
        f"          where both resistivity methods reach the same ground they agree on which "
        f"side of {GRANITE_OHM_M:.0f} ohm.m it falls at "
        f"{100 * agreement['same_side']:.0f}% of {agreement['compared']} depths, and their "
        f"values differ by a median factor of {agreement['median_ratio']:.2f}"
    )
    print(
        f"          the granite top is one sounding's reading, claimed no further than "
        f"{TDEM_REACH_M:.0f} m from it, and it is a cut at {GRANITE_OHM_M:.0f} ohm.m through a "
        f"weathering profile rather than a contact anything resolved. No second method reaches "
        f"the depth it is drawn at."
    )
    print(f"          written to {path.as_posix()}")
    print(
        f"          {len(settings)} declared-setting variants written to "
        f"{sensitivity_path.as_posix()}; agreement is not a calibrated probability"
    )


#: How large a relative residual counts as a reading the model failed to
#: explain, for the purpose of saying where a misfit sits. Well above the five
#: per cent declared error, so ordinary scatter does not enter.
MISFIT_RESIDUAL = 0.15


def _locate_misfit(item: dict, run_directory: Path) -> str:
    """Which part of the line a profile's unexplained readings belong to."""
    observed = np.load(run_directory / "observed_apparent_resistivity.npy")
    predicted = np.load(run_directory / "predicted_apparent_resistivity.npy")
    residual = np.abs((predicted - observed) / observed)
    bad = residual > MISFIT_RESIDUAL
    if not bad.any():
        return ""
    quadrupoles = np.load(item["quadrupoles_path"])
    electrodes = np.load(item["electrodes_path"])
    used = np.bincount(quadrupoles.ravel(), minlength=len(electrodes))
    failed = np.bincount(quadrupoles[bad].ravel(), minlength=len(electrodes))
    rate = np.divide(failed, used, out=np.zeros(len(electrodes)), where=used > 0)
    baseline = bad.sum() / residual.size
    implicated = np.flatnonzero((rate > 2 * baseline) & (used >= 5))
    # Listed rather than given as a span.
    positions = np.sort(electrodes[implicated, 0])
    where = (
        ", at x = " + ", ".join(f"{value:.0f}" for value in positions) + " m"
        if 0 < implicated.size <= 12
        else f", on {implicated.size} electrodes across the line"
        if implicated.size
        else ""
    )
    return (
        f"{bad.sum()} of {residual.size} readings over {100 * MISFIT_RESIDUAL:.0f}%{where}; "
        f"the median reading is {100 * np.median(residual):.1f}%"
    )


def report() -> None:
    """Every profile this case has inverted, and whether it is finished."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    records = {str(item.spec.run_id): item for item in runs.list_runs()}

    imports = state.get("ert_imports") or []
    done = state.get("ert_runs") or {}
    print(f"{'profile':16s} {'state':10s} {'chi2':>8s}  run")
    complete = bool(imports)
    for item in imports:
        key = f"ERT{item['profile']}"
        run_id = done.get(key)
        stored = records.get(str(run_id)) if run_id else None
        if stored is None:
            print(f"{key:16s} {'MISSING':10s} {'-':>8s}  run invert_ert")
            complete = False
            continue
        result = runs.result(stored.spec.run_id)
        chi = result.summary.get("chi_squared") if result else None
        fitted = isinstance(chi, int | float) and chi <= ERT_ACCEPTABLE_CHI_SQUARED
        shown = f"{chi:8.3f}" if isinstance(chi, int | float) else f"{'-':>8s}"
        print(f"{key:16s} {str(stored.state):10s} {shown}  {run_id}")
        if not fitted:
            located = _locate_misfit(item, Path(folder.runs_root) / str(run_id))  # type: ignore[attr-defined]
            print(f"{'':16s} does not fit: {located}")
        complete = complete and str(stored.state) == "SUCCEEDED" and fitted
    for item in state.get("srt_imports") or []:
        key = f"SRT{item['profile']}"
        run_id = (state.get("srt_runs") or {}).get(key)
        stored = records.get(str(run_id)) if run_id else None
        if stored is None:
            print(f"{key:16s} {'MISSING':10s} {'-':>8s}  run invert_srt")
            complete = False
            continue
        result = runs.result(stored.spec.run_id)
        summary = result.summary if result else {}
        chi = summary.get("chi_squared")
        fitted = isinstance(chi, int | float) and chi <= SRT_ACCEPTABLE_CHI_SQUARED
        shown = f"{chi:8.3f}" if isinstance(chi, int | float) else f"{'-':>8s}"
        print(f"{key:16s} {str(stored.state):10s} {shown}  {run_id}")
        touched = summary.get("cells_touched_share")
        if isinstance(touched, float):
            # The number that says how much of the section the data paid for.
            print(
                f"{'':16s} rays reached {100 * touched:.0f}% of "
                f"{summary.get('model_cells')} cells, from {summary.get('picks')} picks"
            )

        if not fitted:
            print(f"{'':16s} does not fit")
        complete = complete and str(stored.state) == "SUCCEEDED" and fitted
    run_id = state.get("tdem_run")
    stored = records.get(str(run_id)) if run_id else None
    if stored is None:
        print(f"{'TDEM':16s} {'MISSING':10s} {'-':>8s}  run invert_tdem")
        complete = False
    else:
        result = runs.result(stored.spec.run_id)
        chi = (result.summary if result else {}).get("chi_squared")
        fitted = isinstance(chi, int | float) and chi <= TDEM_ACCEPTABLE_CHI_SQUARED
        shown = f"{chi:8.3f}" if isinstance(chi, int | float) else f"{'-':>8s}"
        print(f"{'TDEM':16s} {str(stored.state):10s} {shown}  {run_id}")
        if not fitted:
            # Report residuals against repeat-rate variation.
            print(
                f"{'':16s} does not fit, and the five repetition rates disagree with each "
                f"other by a median 5.8% where they overlap"
            )
        complete = complete and str(stored.state) == "SUCCEEDED" and fitted

    if state.get("geological_model_path"):
        report_ = json.loads(
            str(np.load(state["geological_model_path"], allow_pickle=False)["report"])
        )
        print()
        print(f"{'model':16s} {'unit':28s} {'share':>7s}")
        for unit in report_["units"]:
            print(f"{'':16s} {unit['name']:28s} {100 * unit['volume_share']:6.1f}%")
    else:
        print()
        print(f"{'model':16s} not built: run build_model")
        complete = False

    print()
    print(
        "case 3 is complete as far as it has been taken"
        if complete
        else "case 3 is NOT complete: a run is delivered when it fits to chi-squared "
        f"{ERT_ACCEPTABLE_CHI_SQUARED:.0f}"
    )


STAGES = {
    "import_ert": import_ert,
    "invert_ert": invert_ert,
    "import_srt": import_srt,
    "invert_srt": invert_srt,
    "wells": wells,
    "import_tdem": import_tdem,
    "invert_tdem": invert_tdem,
    "build_model": build_model,
    "report": report,
}

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage not in STAGES:
        raise SystemExit(f"usage: {Path(__file__).name} [{'|'.join(STAGES)}]")
    STAGES[stage]()
