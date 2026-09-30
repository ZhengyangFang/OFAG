"""Case 2: the Cedar River alluvial aquifer at Cedar Rapids, Iowa."""

import csv
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
    from ofag.services.interpretation_service import LayeredSection

CASE = Path("data/case2_Cedarrapids")
ERT = CASE / "ert"
AEM = CASE / "aem"
RESULT_ROOT = Path("Result")
PROJECT_NAME = "Cedar Rapids"

#: NAD83 UTM zone 15N, which is what the AEM release is posted in and what
#: everything here is reprojected to.
CRS = "EPSG:26915"

#: The modelling volume, in metres. Chosen by measurement rather than by
#: eye, and the measurement is in `docs/case2_cedar_rapids.md`.
#:
#: Inside it the AEM puts the resistive aquifer at a median 26.5 m depth,
#: 304 ohm.m, 58 m thick; over the rest of the survey the same statistic is
#: 31 m, 168 ohm.m and 38 m, and the depth spreads from 0 to 85 m at the tenth
#: and ninetieth percentiles -- which is what "there is often no coherent
#: resistive layer" looks like as a number. This box is also the densest part
#: of the survey, 3,572 soundings per km2 against 2,601 for a box drawn round
#: all five ERT sites.
#:
#: It costs one site. Edwards CW3 sits 2.2 km east, outside, where the aquifer
#: is thinner and weaker (194 ohm.m, 42 m). That makes it the case's
#: out-of-volume control rather than a loss: ground the model never saw, where
#: the AEM says conditions differ.
VOLUME = (603_500.0, 606_500.0, 4_650_000.0, 4_651_500.0)

#: The ERT sites, from the release's own README, in WGS84 degrees.
#:
#: This is the only geographic placement the release gives: the `.stg` files
#: carry electrode coordinates along the line and nothing that puts the line
#: on the earth. Four of the five spans agree with their own electrode tables
#: to within a few metres. Ellis CW1's stated ends are 477 m apart against a
#: 275 m electrode line, so its endpoints are wrong and its electrodes are
#: not -- the midpoint and azimuth are used, the stated length is not.
#:
#: That sentence described nothing for as long as it stood here. These
#: coordinates were declared and never read: the dictionary was iterated for
#: its keys, to find the directories, and the five pairs of degrees sat in the
#: file unused until A12 asked where the ground was. `_site_positions` is the
#: construction the paragraph above claims, written afterwards. F055, again.
ERT_SITES = {
    "Ellis_CW1": ((41.9984, -91.7340), (42.0024, -91.7361)),
    "Edwd_CW3": ((42.0095, -91.7070), (42.0073, -91.7085)),
    "SVP_CW6": ((42.0076, -91.7417), (42.0085, -91.7448)),
    "SVP_S10": ((41.9985, -91.7313), (41.9982, -91.7284)),
    "SVPDemo-Day": ((42.0054, -91.7342), (42.0049, -91.7310)),
}

#: The plugin's own relative-error threshold is not used. It is applied to the
#: uncertainty this script passes, not to the instrument's error column, so
#: with an error model it would refuse exactly the low-resistance readings the
#: model says are uncertain and keep them out of the misfit it is meant to
#: describe. Every reading this case refuses is refused in `import_ert`, by a
#: criterion stated there.
MAX_RELATIVE_ERROR = None

#: Drop a reading whose apparent resistivity comes back non-positive.
#:
#: Judged on `r * k` and not on `r`, which the plugin's own quality spec is
#: careful about: a dipole-dipole geometric factor is negative, so every one
#: of its readings has a negative transfer resistance and none of that is a
#: fault. What cannot describe ground is a negative *apparent resistivity*.
DROP_NON_POSITIVE = True

#: The range the inversion may not leave. The starting model is the line's
#: own median apparent resistivity (`_run_spec`).
RESISTIVITY_BOUNDS = (5.0, 5_000.0)

#: How deep the parameter domain goes. The arrays reach about 50 m by the usual
#: rule of thumb, so a 60 m domain holds what the data can say and a little
#: beyond it, and nothing so deep that the figure invites reading it.
MESH_DEPTH_M = 60.0

#: Half of every dipole-dipole file is the reciprocal of the other half --
#: about 1,500 pairs in 3,000 readings, `(A, B, M, N)` and `(M, N, A, B)`.
#: Reciprocity makes those the same measurement (Parasnis, 1988), and their
#: disagreement is the one error estimate the survey measured about itself.
#: The procedure below is the one White et al. (2024, doi:10.1093/gji/ggae313)
#: applied to a SuperSting R8 dipole-dipole survey, itself after Tso et al.
#: (2017, doi:10.1016/j.jappgeo.2017.09.009) and Blanchy et al. (2020,
#: doi:10.1016/j.cageo.2020.104423):
#:
#: 1. each pair is averaged, and a reading with no reciprocal is refused;
#: 2. a pair whose reciprocal error |R_n - R_r| / mean(|R|) is 5 per cent or
#:    more is refused -- the commonest threshold in the literature Tso et al.
#:    tabulate, on the full-difference definition ResIPy and White et al. use;
#: 3. the rest are binned by resistance into 20 bins of equal count and a
#:    power law |dR| = a |R|^b is fitted to the bin means (Koestel et al.,
#:    2008, doi:10.1029/2007WR006755; Blanchy et al., 2020);
#: 4. each datum's error is that model, combined with a 2 per cent modelling
#:    error, because a reciprocal measures precision and not accuracy
#:    (LaBrecque et al., 1996, doi:10.1190/1.1443980; Tso et al., 2017).
#:
#: Tso et al. are explicit about the alternative of weighting each datum by its
#: own reciprocal: "individual errors should not be used directly for inversion
#: because in most practical situations they are only averages between two
#: points". The model is fitted per survey, so each line carries its own.
RECIPROCAL_ERROR_LIMIT = 0.05
ERROR_MODEL_BINS = 20
MODELLING_ERROR = 0.02

#: How the power law and the modelling error combine: in quadrature, as two
#: independent sources. White et al. say only that the two are "combined".
#: This is wrong if R2's own convention, which ResIPy writes for them, is
#: shown to add them linearly; the errors would then be up to 41% larger.
ERROR_COMBINATION = "quadrature"

#: The Schlumberger and inverse-Schlumberger files carry no reciprocals, so
#: nothing in them measures their error, and the procedure's first step --
#: refuse a reading with no reciprocal -- refuses the whole file. They are
#: read, counted and not inverted. Lending them the dipole-dipole model from
#: the same line was tried and does not hold: the two inverse-Schlumberger
#: surveys it was tested on stay at chi-squared 26 to 86 at every
#: regularization from 2 to 20, which is an error the model does not describe.
RECIPROCAL_ARRAYS = ("dipole-dipole",)

#: The regularization, relaxed during the inversion rather than fixed: lambda
#: starts at 100 and is multiplied by 0.8 after every iteration, and the run
#: stops at chi-squared 1 -- the smoothest model that fits, reached the way
#: Occam's inversion reaches it (Constable et al., 1987, doi:10.1190/1.1442303)
#: and as pyGIMLi's lambdaFactor implements it.
#:
#: It is not allowed below 10. A fixed lambda stalled above the target at 10,
#: 20 and 40 on Ellis CW1 and only fitted at 5, where the section fits the
#: reciprocal error model by adding electrode-scale vertical streaks and a
#: deep resistive body a smoother model does not need. Edwards CW3 relaxed to
#: 0.6 before stopping. A line that has not fitted when lambda reaches the
#: floor is reported as not fitting rather than roughened until it does.
#: This is wrong if the error model is shown to underestimate the error on
#: those lines; the floor would then be hiding a misfit the errors explain.
ERT_LAMBDA_START = 100.0
ERT_LAMBDA_FACTOR = 0.8
ERT_LAMBDA_FLOOR = 10.0

#: The error the delivered data is given in the control runs of
#: `invert_ert_baseline`: five per cent on every reading, what a survey with no
#: error estimate of its own is usually handed. The floor stops a near-zero
#: reading from claiming a near-zero error.
ERT_RELATIVE_ERROR = 0.05
ERT_ABSOLUTE_FLOOR_OHM = 1.0e-4

#: A reading is refused when the contact resistance of its own current pair,
#: measured before the survey and written to the `.crs` files, exceeds this.
#: Wilkinson et al. (2016, doi:10.1002/2015gl067494) filter an inline
#: dipole-dipole survey at 2,000 ohm, per measurement; high contact resistance
#: limits the injected current and lowers the signal (Ingeman-Nielsen et al.,
#: 2016, doi:10.1190/geo2015-0484.1).
#:
#: An electrode is refused outright, with every reading that uses it, when
#: every current pair it took part in read above the same limit -- the rule
#: that separates a badly coupled electrode from the good neighbours it was
#: paired with, whose own lowest readings stay near a few hundred ohm. Wilkinson
#: et al. (2012, doi:10.1111/j.1365-246x.2012.05372.x) do the same with an
#: electrode found to be poorly coupled: "any measurements involving it were
#: removed from the data". It matters for the arrays whose own `.crs` never
#: drove current through that electrode, which the per-reading rule cannot see.
#:
#: Judged per site rather than per file: the arrays ran the same day down the
#: same line, so a pair's reading in any of the site's files stands for all of
#: them, and the highest is kept. A pair no file measured is not judged.
MAX_CONTACT_RESISTANCE_OHM = 2_000.0

#: What counts as fitted. A run that converged is not a run that fits, and
#: the first version of `report` called a chi-squared of 70 complete because
#: the state was SUCCEEDED and the number was not None -- which is a test of
#: the harness, not of the result.
ERT_ACCEPTABLE_CHI_SQUARED = 2.0

#: Enough iterations for lambda to fall from the start to the floor, and no
#: more: 100 x 0.8^10 = 10.7 on the eleventh.
ERT_MAX_ITERATIONS = (
    int(np.floor(np.log(ERT_LAMBDA_FLOOR / ERT_LAMBDA_START) / np.log(ERT_LAMBDA_FACTOR))) + 1
)


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
            enabled_methods=("ert",),
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


def _site_positions(site: str, along_m: np.ndarray) -> np.ndarray:
    """Where one line's electrodes stand on the earth, as UTM easting/northing."""
    from pyproj import Transformer

    (start, finish) = ERT_SITES[site]
    to_utm = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    x0, y0 = to_utm.transform(start[1], start[0])
    x1, y1 = to_utm.transform(finish[1], finish[0])
    length = float(np.hypot(x1 - x0, y1 - y0))
    if length == 0.0:
        raise SystemExit(f"{site}: the README gives the same point twice")
    direction = np.array([x1 - x0, y1 - y0]) / length
    midpoint = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    offset = np.asarray(along_m, dtype=float) - float(np.mean(along_m))
    return midpoint + offset[:, None] * direction


def _site_along(site: str) -> np.ndarray:
    """Every distinct along-line electrode position at one site."""
    from ofag.formats.stg import read_stg

    return np.unique(
        np.concatenate(
            [read_stg(path).electrodes_m[:, 0] for name, _array, path in _surveys() if name == site]
        )
    )


def _ground_along(positions: np.ndarray) -> tuple[np.ndarray, float]:
    """The land surface at those positions, and how far the nearest reading was."""
    import pandas as pd
    from scipy.spatial import cKDTree

    table = pd.read_csv(AEM / "measured.csv", usecols=["X", "Y", "DTM"])
    ground = table.to_numpy(dtype=float)
    distance, nearest = cKDTree(ground[:, :2]).query(positions)
    return ground[nearest, 2], float(distance.max())


def _ert_terrain() -> dict[str, object]:
    """A12's two numbers for every resistivity line, before any of them is read."""
    from ofag.agent.gates import measure_terrain

    terrain: dict[str, object] = {}
    for site in ERT_SITES:
        elevation, furthest = _ground_along(_site_positions(site, _site_along(site)))
        terrain[site] = measure_terrain(
            site,
            elevation,
            source=(
                f"the airborne DTM at the nearest sounding, never further than {furthest:.0f} m, "
                "along the line placed from the README's midpoint and azimuth"
            ),
        )
    return terrain


def _surveys() -> list[tuple[str, str, Path]]:
    """Every individual survey, as (site, array, path), in a stable order."""
    found = []
    for site in ERT_SITES:
        for path in sorted((ERT / f"{site}_5m").rglob("*.stg")):
            if "COMBINED" in path.name.upper():
                continue
            stem = path.stem.upper()
            if "DIPDIP" in stem or "DIPDP" in stem:
                array = "dipole-dipole"
            elif "INV" in stem:
                array = "inverse Schlumberger"
            elif "SCHL" in stem:
                array = "Schlumberger"
            else:
                raise ValueError(f"cannot tell which array {path.name} is")
            found.append((site, array, path))
    return found


def _reciprocal_pairs(
    quadrupoles: np.ndarray, resistance: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each normal/reciprocal pair once: its quadrupole, mean resistance and error."""
    lookup = {tuple(row): index for index, row in enumerate(quadrupoles.tolist())}
    first, mean, difference = [], [], []
    for index, row in enumerate(quadrupoles.tolist()):
        other = lookup.get((row[2], row[3], row[0], row[1]))
        if other is None or other <= index:
            continue
        pair = np.abs([resistance[index], resistance[other]])
        first.append(index)
        mean.append(np.sign(resistance[index]) * pair.mean())
        difference.append(float(np.ptp(pair)))
    first_index = np.asarray(first, dtype=int)
    return (
        quadrupoles[first_index],
        np.asarray(mean, dtype=float),
        np.asarray(difference, dtype=float),
    )


def _fit_error_model(resistance: np.ndarray, difference: np.ndarray) -> tuple[float, float]:
    """|dR| = a |R|^b through the means of equal-count bins sorted by |R|."""
    order = np.argsort(np.abs(resistance))
    bins = np.array_split(order, ERROR_MODEL_BINS)
    r = np.array([np.abs(resistance[b]).mean() for b in bins])
    e = np.array([difference[b].mean() for b in bins])
    ok = (r > 0) & (e > 0)
    b, log_a = np.polyfit(np.log(r[ok]), np.log(e[ok]), 1)
    return float(np.exp(log_a)), float(b)


def import_ert() -> None:
    """Read every SuperSting file into electrodes, quadrupoles and resistance."""
    from ofag.agent.gates import refuse_unmeasured_terrain
    from ofag.formats.stg import read_stg
    from ofag.services.import_store import ImportStore

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    store = ImportStore(Path(folder.imports_root))  # type: ignore[attr-defined]

    terrain = _ert_terrain()
    # What the gate returns is the lines whose relief is mostly their own quantum, which
    # a continuously sampled DTM never is -- so the answer here is always empty and the
    # useful number is the relief against the line's own length.
    refuse_unmeasured_terrain(terrain)
    for site, ground in terrain.items():
        span = float(np.ptp(_site_along(site)))
        print(f"terrain   {ground.summary}")  # type: ignore[attr-defined]
        print(
            f"          {'':14s} {100 * ground.relief_m / span:.1f} per cent of the "  # type: ignore[attr-defined]
            f"{span:.0f} m line, inverted flat"
        )

    imported = []
    models: dict[str, tuple[float, float]] = {}
    print(
        f"import    {'survey':34s} {'read':>5s} {'unpair':>6s} {'>=5%':>5s} {'>2kohm':>6s} "
        f"{'kept':>5s}  error model"
    )
    # Dipole-dipole first, so each site's model exists before the arrays that borrow it.
    skipped = []
    for site, array, path in _surveys():
        if array not in RECIPROCAL_ARRAYS:
            skipped.append(f"{site} {array}")
            continue
        survey = read_stg(path)
        read = int(survey.resistance_ohm.size)
        quadrupoles, resistance, difference = _reciprocal_pairs(
            survey.quadrupoles, survey.resistance_ohm
        )
        paired = int(resistance.size)
        if paired:
            unpaired = read - 2 * paired
            relative = difference / np.abs(resistance)
            noisy = relative >= RECIPROCAL_ERROR_LIMIT
            refused_error = int(noisy.sum())
            quadrupoles, resistance, difference = (
                quadrupoles[~noisy],
                resistance[~noisy],
                difference[~noisy],
            )
        else:
            unpaired = refused_error = 0
            quadrupoles, resistance = survey.quadrupoles, survey.resistance_ohm.astype(float)

        # A reading whose own current pair was poorly coupled, in either direction of
        # the pair.
        contact = _contact_resistance(path)
        refused_electrodes = _poorly_coupled(contact)
        touching = np.isin(quadrupoles, refused_electrodes).any(axis=1)
        worst = np.array(
            [
                max(
                    contact.get(tuple(sorted(q[:2])), 0.0),
                    contact.get(tuple(sorted(q[2:])), 0.0) if paired else 0.0,
                )
                for q in quadrupoles.tolist()
            ]
        )
        coupled = (worst <= MAX_CONTACT_RESISTANCE_OHM) & ~touching
        refused_contact = int((~coupled).sum())
        quadrupoles, resistance = quadrupoles[coupled], resistance[coupled]
        if paired:
            difference = difference[coupled]
            models[site] = _fit_error_model(resistance, difference)
        model = models.get(site)
        if model is None:
            raise SystemExit(f"{site} {array}: no reciprocals, so no error model")

        dataset_id, destination = store.new_dataset()
        np.save(destination / "electrodes_m.npy", survey.electrodes_m)
        np.save(destination / "quadrupoles.npy", quadrupoles)
        (destination / "observations_ohm.csv").write_text(
            "resistance_ohm\n" + "\n".join(f"{v:.10e}" for v in resistance) + "\n",
            encoding="utf-8",
        )
        if paired:
            np.save(destination / "reciprocal_difference_ohm.npy", difference)
        e = survey.electrodes_m
        a_, b_, m_, n_ = (e[quadrupoles[:, i]] for i in range(4))

        def gap(p: np.ndarray, q: np.ndarray) -> np.ndarray:
            return np.asarray(np.linalg.norm(p - q, axis=1), dtype=float)

        with np.errstate(divide="ignore", invalid="ignore"):
            k = (
                2.0
                * np.pi
                / (1 / gap(a_, m_) - 1 / gap(b_, m_) - 1 / gap(a_, n_) + 1 / gap(b_, n_))
            )
        bad_sign = int((k * resistance <= 0).sum())
        imported.append(
            {
                "site": site,
                "array": array,
                "source": path.as_posix(),
                "dataset_id": str(dataset_id),
                "electrodes_path": (destination / "electrodes_m.npy").as_posix(),
                "quadrupoles_path": (destination / "quadrupoles.npy").as_posix(),
                "observations_path": (destination / "observations_ohm.csv").as_posix(),
                "readings": read,
                "measurements": int(resistance.size),
                "reciprocal_pairs": paired,
                "unpaired_refused": unpaired,
                "reciprocal_error_refused": refused_error,
                "contact_refused": refused_contact,
                "electrodes_refused": [int(e) + 1 for e in refused_electrodes],
                "error_model": {"a": model[0], "b": model[1], "fitted": bool(paired)},
                "electrodes": int(len(e)),
                "spacing_m": survey.spacing_m,
                "non_positive_apparent": bad_sign,
                "declared_records": survey.declared_records,
                "unparsed_records": survey.unparsed_records,
            }
        )
        print(
            f"          {site + ' ' + array:34.34s} {read:5d} {unpaired:6d} {refused_error:5d} "
            f"{refused_contact:6d} {resistance.size:5d}  |dR| = {model[0]:.2e} |R|^{model[1]:.2f}"
            + ("" if paired else "  (the site's DD)")
        )
    imported.sort(key=lambda item: (item["site"], item["array"]))
    print(f"          not inverted, no reciprocals to measure their error: {', '.join(skipped)}")
    _save_state(folder, ert_imports=imported, ert_without_reciprocals=skipped)
    total = sum(item["measurements"] for item in imported)
    print(f"\n          {len(imported)} surveys, {total:,} measurements")
    print(f"          written under {folder.imports_root}")  # type: ignore[attr-defined]


def _poorly_coupled(contact: dict[tuple[int, int], float]) -> np.ndarray:
    """Zero-based electrodes every one of whose measured pairs read above the limit."""
    lowest: dict[int, float] = {}
    for pair, ohm in contact.items():
        for electrode in pair:
            lowest[electrode] = min(lowest.get(electrode, np.inf), ohm)
    return np.array(
        sorted(e for e, ohm in lowest.items() if ohm > MAX_CONTACT_RESISTANCE_OHM), dtype=int
    )


def _contact_resistance(path: Path) -> dict[tuple[int, int], float]:
    """The contact resistance of every current pair the site measured, in ohm."""
    folder = Path(path).parent
    while folder.name and not folder.name.endswith("_5m"):
        folder = folder.parent
    readings: dict[tuple[int, int], float] = {}
    for source in sorted(folder.rglob("*.crs")) if folder.name else []:
        for line in source.read_text(errors="ignore").splitlines()[5:]:
            field = line.split(",")
            if len(field) < 8:
                continue
            try:
                ohm = abs(float(field[3]))
                pair = tuple(sorted((int(float(field[6])) - 1, int(float(field[7])) - 1)))
            except ValueError:
                continue
            readings[pair] = max(readings.get(pair, 0.0), ohm)  # type: ignore[index]
    return readings  # type: ignore[return-value]


def _run_spec(
    record: object, item: dict, label: str = "", lam: float = ERT_LAMBDA_START
) -> RunSpec:
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

    return RunSpec(
        plugin_id="pygimli.ert.dcip",
        plugin_version="0.1.0",
        engine="pygimli",
        project_id=record.project_id,  # type: ignore[attr-defined]
        label=f"ERT {item['site']} {item['array']}{label}",
        dataset=DatasetSpec(
            name=f"{item['site']}-{item['array'].replace(' ', '-')}",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.TRANSFER_RESISTANCE,
            units="ohm",
        ),
        datasets=(
            DataChannelSpec(
                channel_id="dc",
                dataset=DatasetSpec(
                    name=f"{item['site']}-{item['array'].replace(' ', '-')}-dc",
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
                lam=lam,
                lambda_factor=ERT_LAMBDA_FACTOR,
                lower_bound=ohm_m(RESISTIVITY_BOUNDS[0]),
                upper_bound=ohm_m(RESISTIVITY_BOUNDS[1]),
            ),
            optimizer=ERTOptimizerSpec(max_iterations=ERT_MAX_ITERATIONS),
            # None: pyGIMLi starts from the line's median apparent resistivity, as the
            # USGS inversions of these data started from its mean (Haj et al., 2021,
            # doi:10.3133/sir20215065, p. 10).
            starting_resistivity=None,
            quality=ERTDataQualitySpec(
                drop_non_positive=DROP_NON_POSITIVE,
                maximum_relative_error=MAX_RELATIVE_ERROR,
            ),
        ).model_dump(mode="json"),
    )


def _resistance(item: dict) -> np.ndarray:
    return np.loadtxt(item["observations_path"], delimiter=",", skiprows=1)


def _uncertainty(item: dict) -> np.ndarray:
    """One absolute error per measurement, in ohm, from the survey's error model."""
    resistance = np.abs(_resistance(item))
    model = item.get("error_model")
    if not model:
        return np.maximum(ERT_RELATIVE_ERROR * resistance, ERT_ABSOLUTE_FLOOR_OHM)
    measured = model["a"] * resistance ** model["b"]
    total = np.hypot(measured, MODELLING_ERROR * resistance)
    return np.maximum(total, ERT_ABSOLUTE_FLOOR_OHM)


def invert_ert() -> None:
    """One 2D section per dipole-dipole line, its regularization chosen to fit."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("ert_imports"):
        raise SystemExit("run import_ert first")
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]

    done: dict[str, str] = {}
    reached: dict[str, float] = {}
    for item in state["ert_imports"]:
        key = f"{item['site']}/{item['array']}"
        spec = _run_spec(record, item, label=", lambda 100 x 0.8 per iteration")
        report = runs.validate(spec)
        if not report.valid:
            for issue in report.issues:
                print(f"          {issue.field}: {issue.message}")
            raise SystemExit(f"{key} did not validate")
        runs.create(spec)
        runs.start(spec.run_id)
        _wait(runs, spec.run_id, key)
        # The lambda of the last iteration.
        progress = Path(folder.runs_root) / str(spec.run_id) / "progress.jsonl"  # type: ignore[attr-defined]
        entries = sum('"iteration completed"' in line for line in progress.read_text().splitlines())
        done[key] = str(spec.run_id)
        reached[key] = ERT_LAMBDA_START * ERT_LAMBDA_FACTOR ** max(entries - 2, 0)
        _save_state(folder, ert_runs=done, ert_lambda=reached)


def invert_ert_baseline() -> None:
    """The control: the thirteen surveys as delivered, with the declared error alone."""
    from ofag.formats.stg import read_stg
    from ofag.services.import_store import ImportStore
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    store = ImportStore(Path(folder.imports_root))  # type: ignore[attr-defined]
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]

    baseline = []
    for site, array, path in _surveys():
        survey = read_stg(path)
        dataset_id, destination = store.new_dataset()
        np.save(destination / "electrodes_m.npy", survey.electrodes_m)
        np.save(destination / "quadrupoles.npy", survey.quadrupoles)
        (destination / "observations_ohm.csv").write_text(
            "resistance_ohm\n" + "\n".join(f"{v:.10e}" for v in survey.resistance_ohm) + "\n",
            encoding="utf-8",
        )
        disagreements = _reciprocal_disagreements(survey.quadrupoles, survey.resistance_ohm)
        paired = int(disagreements.size)
        pairs_path = None
        if paired:
            pairs_path = destination / "reciprocal_pairs.npy"
            np.save(pairs_path, disagreements)
        item = {
            "site": site,
            "array": array,
            "source": path.as_posix(),
            "dataset_id": str(dataset_id),
            "electrodes_path": (destination / "electrodes_m.npy").as_posix(),
            "quadrupoles_path": (destination / "quadrupoles.npy").as_posix(),
            "observations_path": (destination / "observations_ohm.csv").as_posix(),
        }
        spec = _run_spec(record, item, label=", as delivered")
        runs.create(spec)
        runs.start(spec.run_id)
        _wait(runs, spec.run_id, f"{site}/{array} as delivered")
        baseline.append(
            {
                "site": site,
                "array": array,
                "run_id": str(spec.run_id),
                "measurements": int(survey.resistance_ohm.size),
                "reciprocal_pairs": paired,
                "reciprocal_pairs_path": pairs_path.as_posix() if pairs_path else None,
            }
        )
        _save_state(folder, ert_baseline=baseline)


def _reciprocal_disagreements(quadrupoles: np.ndarray, resistance: np.ndarray) -> np.ndarray:
    """The relative disagreement of every reciprocal pair, once per pair."""
    lookup = {tuple(row): index for index, row in enumerate(quadrupoles.tolist())}
    out = []
    for index, row in enumerate(quadrupoles.tolist()):
        other = lookup.get((row[2], row[3], row[0], row[1]))
        if other is not None and other > index:
            pair = np.abs([resistance[index], resistance[other]])
            out.append(float(np.ptp(pair) / max(pair.mean(), 1e-12)))
    return np.asarray(out, dtype=float)


def _wait(runs: object, run_id: object, label: str) -> None:
    import time

    started = time.time()
    while True:
        record = runs.get(run_id)  # type: ignore[attr-defined]
        if record.state.value in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"):
            result = runs.result(run_id) if record.state.value == "SUCCEEDED" else None  # type: ignore[attr-defined]
            # Plugins report the misfit under the name that fits what they did: one
            # section has a chi-squared, a batch has a median of them.
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
                f"          {label:34.34s} {record.state.value:10s} "
                f"chi-squared {chi:7.3f}  {time.time() - started:5.0f} s"
                + (f"  {record.error}" if record.error else "")
            )
            return
        time.sleep(5.0)


def report() -> None:
    """Every survey this case has inverted, and whether it is finished."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]
    records = {str(item.spec.run_id): item for item in runs.list_runs()}

    imports = state.get("ert_imports") or []
    done = state.get("ert_runs") or {}
    print(f"{'survey':34s} {'state':10s} {'chi2':>8s}  run")
    complete = bool(imports)
    for item in imports:
        key = f"{item['site']}/{item['array']}"
        run_id = done.get(key)
        stored = records.get(str(run_id)) if run_id else None
        if stored is None:
            print(f"{key:34.34s} {'MISSING':10s} {'-':>8s}  run invert_ert")
            complete = False
            continue
        result = runs.result(stored.spec.run_id)
        chi = result.summary.get("chi_squared") if result else None
        shown = f"{chi:8.3f}" if isinstance(chi, int | float) else f"{'-':>8s}"
        fitted = isinstance(chi, int | float) and chi <= ERT_ACCEPTABLE_CHI_SQUARED
        mark = "" if fitted else "  <- does not fit"
        print(f"{key:34.34s} {str(stored.state):10s} {shown}  {run_id}{mark}")
        complete = complete and str(stored.state) == "SUCCEEDED" and fitted
    print()
    if complete:
        print("the ERT half of case 2 is complete")
    else:
        print(
            f"case 2 is NOT complete: a run is delivered when it fits to "
            f"chi-squared {ERT_ACCEPTABLE_CHI_SQUARED:.0f}, not when it converges"
        )


# -- AEM --------------------------------------------------------------------

#: The RESOLVE bar, from CGG's own report rather than from the column names.
#:
#: The delivery labels its channels 400, 1800, 3300, 8200, 40k and 140k Hz.
#: The bar flies 383, 1820, 3315, 8488, 40840 and 133530, and one pair is
#: coaxial at a different separation from the five coplanar ones. Believing a
#: column name would be a five per cent frequency error at the bottom of the
#: band, five per cent the other way at the top, and a wrong coupling geometry
#: in the middle.
#: The last column is the delivery's sign against a forward model that
#: normalises by the *signed* primary field. The coaxial pair is -1: CGG
#: reports every channel positive, which means it normalised by the magnitude,
#: and a coaxial pair's on-axis primary has the opposite sign to a coplanar
#: pair's broadside one. Left at +1 the best-fitting halfspace gives
#: chi-squared 32.5; at -1 it gives 1.1.
RESOLVE_COILS = (
    # actual Hz, separation m, orientation, in-phase, quadrature, sign
    (383.0, 7.93, "horizontal_coplanar", "CPI400", "CPQ400", 1),
    (1820.0, 7.95, "horizontal_coplanar", "CPI1800", "CPQ1800", 1),
    (3315.0, 9.06, "vertical_coaxial", "CXI3300", "CXQ3300", -1),
    (8488.0, 7.93, "horizontal_coplanar", "CPI8200", "CPQ8200", 1),
    (40840.0, 7.92, "horizontal_coplanar", "CPI40K", "CPQ40K", 1),
    (133530.0, 7.97, "horizontal_coplanar", "CPI140K", "CPQ140K", 1),
)

#: How far apart to take soundings along a flight line.
#:
#: They arrive 2.3 m apart, which is the 10 Hz sample rate against the
#: helicopter's speed and not a statement about resolution: the system's
#: footprint at 50 m altitude is tens of metres across, so consecutive
#: soundings see almost the same ground. Twenty-five metres keeps every
#: distinguishable sounding and turns 16,072 independent inversions into about
#: fifteen hundred.
AEM_STATION_SPACING_M = 25.0

#: Ten per cent of the reading, with a floor.
#:
#: The floor is what matters here. The 400 Hz in-phase has a median of 11.6 ppm
#: inside the volume and the 140 kHz in-phase 688, so a purely relative error
#: would let the quietest channel claim a precision of a fraction of a part per
#: million and the inversion would chase it. Both numbers are declared.
AEM_RELATIVE_ERROR = 0.10
AEM_NOISE_FLOOR_PPM = 2.0

#: The layered earth every sounding is inverted against.
#:
#: The target sits at 10 to 70 m and the contractor used 28 layers to 217 m.
#: This stops shallower on purpose: the depth of investigation has a median of
#: 112 m, and layers below it are a picture of the prior rather than of ground.
AEM_LAYERS = 20
AEM_FIRST_LAYER_M = 3.0
AEM_LAST_DEPTH_M = 120.0

AEM_STARTING_RESISTIVITY = 100.0

#: The weight on staying near the 100 ohm.m reference, against smoothness.
#:
#: The plugin's default is 1, equal to the smoothness weight, and on a
#: one-dimensional layer array that is a strong pull back to the reference:
#: the recovered peak came out near 190 ohm.m at 25-30 m against CGG's 280,
#: while CGG's model, forward-modelled through this operator on these data and
#: errors, fits as well (chi-squared 0.80 against 0.90 over 150 soundings). The
#: data do not separate the two; the smallness term did. At 1e-4 the model is
#: set by the data and the smoothness, and the peak rises to about 240 on a
#: 40-sounding test with the fit unchanged.
#: This is wrong if a reference model is built from independent information,
#: such as the logs; the smallness term would then be carrying evidence.
AEM_SMALLNESS_WEIGHT = 1e-4
AEM_BOUNDS_OHM_M = (1.0, 10_000.0)
AEM_MAX_ITERATIONS = 15
AEM_ACCEPTABLE_CHI_SQUARED = 2.0


def _aem_columns() -> list[str]:
    """The final levelled channels."""
    return ["LINE", "X", "Y", "LASER"] + [
        name
        for _, _, _, in_phase, quadrature, _ in RESOLVE_COILS
        for name in (in_phase, quadrature)
    ]


def import_aem() -> None:
    """Read the RESOLVE survey inside the model volume, one file per sounding."""
    from ofag.services.import_store import ImportStore

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    store = ImportStore(Path(folder.imports_root))  # type: ignore[attr-defined]

    source = AEM / "measured.csv"
    header = source.open(encoding="utf-8").readline().strip().split(",")
    wanted = _aem_columns()
    missing = [name for name in wanted if name not in header]
    if missing:
        raise SystemExit(f"{source} has no column {missing}")
    table = np.loadtxt(
        source, delimiter=",", skiprows=1, usecols=[header.index(name) for name in wanted]
    )
    line, east, north, laser = (table[:, index] for index in range(4))
    response = table[:, 4:]

    inside = (east >= VOLUME[0]) & (east <= VOLUME[1]) & (north >= VOLUME[2]) & (north <= VOLUME[3])
    print(f"aem       {int(inside.sum()):,} soundings inside the volume of {table.shape[0]:,}")

    # Thinned by walking each line in acquisition order, so a gap in the flying does not
    # become a gap in the thinning and a turn does not collapse to one station.
    chosen: list[int] = []
    for number in np.unique(line[inside]):
        rows = np.flatnonzero(inside & (line == number))
        last: np.ndarray | None = None
        for row in rows:
            here = np.array([east[row], north[row]])
            if last is None or float(np.hypot(*(here - last))) >= AEM_STATION_SPACING_M:
                chosen.append(int(row))
                last = here
    picked = np.asarray(sorted(chosen), dtype=int)
    print(
        f"          thinned to {picked.size:,} at {AEM_STATION_SPACING_M:.0f} m along "
        f"{np.unique(line[inside]).size} flight lines"
    )

    usable = np.isfinite(response[picked]).all(axis=1) & (laser[picked] > 0)
    if int((~usable).sum()):
        print(f"          {int((~usable).sum())} dropped: a non-finite channel or no altimeter")
    picked = picked[usable]

    dataset_id, destination = store.new_dataset()
    soundings = []
    for row in picked:
        name = f"L{int(line[row])}-{row}"
        path = destination / f"{name}.csv"
        path.write_text(
            "ppm\n" + "\n".join(f"{value:.6e}" for value in response[row]) + "\n",
            encoding="utf-8",
        )
        soundings.append(
            {
                "sounding_id": name,
                "observations_path": path.as_posix(),
                "easting_m": float(east[row]),
                "northing_m": float(north[row]),
                "flight_height_m": float(laser[row]),
            }
        )
    _save_state(folder, aem_dataset_id=str(dataset_id), aem_soundings=soundings)
    heights = np.array([item["flight_height_m"] for item in soundings])
    print(
        f"          bar height median {np.median(heights):.1f} m "
        f"(p5 {np.percentile(heights, 5):.1f}, p95 {np.percentile(heights, 95):.1f})"
    )
    print(f"          {len(soundings):,} soundings written under {destination}")


def _aem_response(item: dict) -> np.ndarray:
    return np.loadtxt(item["observations_path"], delimiter=",", skiprows=1)


def _aem_run_spec(record: object, soundings: list[dict]) -> RunSpec:
    thicknesses = np.diff(np.geomspace(AEM_FIRST_LAYER_M, AEM_LAST_DEPTH_M, AEM_LAYERS)).tolist()

    def conductivity(ohm_m: float) -> dict:
        return {"value": 1.0 / ohm_m, "quantity_type": "conductivity", "unit": "S/m"}

    return RunSpec(
        plugin_id="simpeg.aem.fdem1d",
        plugin_version="0.1.0",
        engine="simpeg",
        project_id=record.project_id,  # type: ignore[attr-defined]
        label=f"RESOLVE AEM, {len(soundings)} soundings in the model volume",
        dataset=DatasetSpec(
            name="cedar-rapids-resolve",
            coordinate_convention=CoordinateConvention(crs=CRS),
            physical_quantity=QuantityType.DIMENSIONLESS,
            units="ppm",
        ),
        physics={
            "earth": {
                "layer_thicknesses": {
                    "value": thicknesses,
                    "quantity_type": "length",
                    "unit": "m",
                }
            },
            "system": {
                "coil_pairs": [
                    {
                        "frequency_hz": frequency,
                        "separation_m": separation,
                        "orientation": orientation,
                        "in_phase_column": in_phase,
                        "quadrature_column": quadrature,
                        "response_sign": sign,
                    }
                    for frequency, separation, orientation, in_phase, quadrature, sign in (
                        RESOLVE_COILS
                    )
                ],
                "flight_height_m": {"value": 50.0, "quantity_type": "length", "unit": "m"},
            },
            "model": {
                "initial_conductivity": conductivity(AEM_STARTING_RESISTIVITY),
                # Bounds are on conductivity, so the resistivity limits swap.
                "lower_bound": conductivity(AEM_BOUNDS_OHM_M[1]),
                "upper_bound": conductivity(AEM_BOUNDS_OHM_M[0]),
            },
            "regularization": {"alpha_s": AEM_SMALLNESS_WEIGHT},
            "optimizer": {"max_iterations": AEM_MAX_ITERATIONS},
            # Stop at the declared error rather than driving the misfit as low as the
            # optimizer can: past chi-squared one the model is fitting the noise budget
            # it was given.
            "directives": {"target_chi_factor": 1.0},
            "soundings": [
                {
                    "sounding_id": item["sounding_id"],
                    "observations_path": item["observations_path"],
                    "station_location": {
                        "value": [item["easting_m"], item["northing_m"], 0.0],
                        "quantity_type": "length",
                        "unit": "m",
                    },
                    "flight_height_m": item["flight_height_m"],
                    "data_uncertainty": {
                        "value": np.maximum(
                            AEM_RELATIVE_ERROR * np.abs(_aem_response(item)),
                            AEM_NOISE_FLOOR_PPM,
                        ).tolist(),
                        "quantity_type": "dimensionless",
                        "unit": "1",
                    },
                }
                for item in soundings
            ],
        },
    )


def invert_aem() -> None:
    """One layered conductivity per sounding, over the model volume."""
    from ofag.services.run_service import RunService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("aem_soundings"):
        raise SystemExit("run import_aem first")
    runs = RunService(artifact_root=Path(folder.runs_root))  # type: ignore[attr-defined]

    spec = _aem_run_spec(record, state["aem_soundings"])
    report = runs.validate(spec)
    for issue in report.issues:
        print(f"          {issue.field}: {issue.message}")
    if not report.valid:
        raise SystemExit("the AEM run did not validate")
    runs.create(spec)
    runs.start(spec.run_id)
    _wait(runs, spec.run_id, "RESOLVE AEM")
    _save_state(folder, aem_run_id=str(spec.run_id))


# -- build_model -------------------------------------------------------------

#: The mesh the model is written on. The AEM is 1,374 stitched one-dimensional
#: columns rather than a volume, so a grid is made here; 50 m across is finer
#: than the 25 m station spacing can support laterally and coarse enough to
#: draw, and 2 m in depth resolves the cover, whose base sits at 7.6 m.
MODEL_CELL_M = (50.0, 50.0, 2.0)
#: Where the model stops, and why there. The AEM's depth of investigation
#: varies by column from 56 to 146 m, median 112; 98 m is its tenth
#: percentile, so nine columns in ten are resolved to the floor and the model
#: does not carry 20 m of ground under most of the survey that it can only
#: label as unseen. It was 120 m, the depth of the inversion itself, which
#: put 8.4 per cent of the volume below the investigation depth. The columns
#: whose depth of investigation is shallower still keep that unit above 98 m.
MODEL_DEPTH_M = 98.0

#: The sharpest resistivity rise in the shallow band. Picked at 1,219 of the
#: 1,240 soundings that fit, median 7.6 m, and the fitted surface predicts a
#: held-out pick to 3.6 m against the picks' own spread of 4.6.
#:
#: It is a resistivity boundary and not a lithologic one, which the two wells
#: with a readable lithology column show. Both log the fine-to-coarse change at
#: about 3 m; the rise is at 7.6 m beneath GX-2 and 12.7 m beneath GX-1, and at
#: GX-1 the resistivity is *falling* where the well changes -- 104 ohm.m at
#: 0.6 m down to 76 at 4.9, then up. Saturation and clay content move
#: resistivity as much as grain size does, and the published study lists both
#: (doi:10.3133/sim3423). So the unit above it is named for the measurement.
COVER_BAND_M = (2.0, 30.0)
COVER_MIN_SLOPE = 0.3

#: Above this the ground is resistive. Not "is the aquifer": at GX-2, the one
#: well inside the volume with a numeric bedrock pick, the log puts shaley
#: limestone at 16.0 m below ground and the AEM passes straight through it --
#: 191 ohm.m at 17.9 m, rising smoothly to its peak of 203 at 27.8. There is no
#: feature at the contact, so everything below 16 m that this threshold calls
#: resistive is bedrock at that well.
#:
#: The published interpretation says the same thing about its own data: "some
#: alluvial deposits in the study area have a range of resistivity values
#: similar to the range of the underlying bedrock" and "the boundary between
#: these units may not be clearly defined" (doi:10.3133/sim3423). It is
#: confirmed here independently, at a well.
#:
#: 120 is read from the AEM's own profile -- 58 ohm.m at the surface, a broad
#: peak of 185 at 22 m, 133 by 64 m -- and is a declared cut through a
#: gradational body, not a boundary the data resolves.
RESISTIVE_OHM_M = 120.0

#: The contractor's depth of investigation, per sounding, from the EM1DFM
#: delivery. Used rather than our own because our inversion does not compute
#: one, and because a published, independently derived bound is the better
#: authority for where to stop reading.
#:
#: Below it nothing is claimed. The base of the aquifer is *not* mapped: the
#: pick comes back at 87.1 m for 1,090 of 1,240 soundings, the same layer every
#: time, which is the investigation depth cutting the profile rather than a
#: contact. The published interpretation (doi:10.3133/sim3423) separates till
#: from bedrock here; this case cannot, and says so.
DOI_COLUMN = "DOI"

#: The ground, from the same delivery. Its value at each sounding is exactly
#: ELEVATION_28_TOP[0] -- the top of the contractor's own 28-layer model --
#: so a volume hung on it sits in the frame their product is published in,
#: and the two can be differenced without a datum in between.
#:
#: The model was built without it until A12 asked. Every cell sat at minus its
#: depth from a plane at zero, over a box whose ground runs 219 m on the
#: floodplain to 273 m on the valley wall, and the elevation had been in both
#: airborne files the whole time: a DTM column for all 139,602 measured
#: soundings, and this one.
GROUND_COLUMN = "DTM_HEM"

#: How far a cell may be from a sounding before no unit is claimed for it.
#: The flight lines are about 400 m apart and the stations 25 m along them.
AEM_REACH_M = 300.0


def _aem_layered_section(state: dict) -> tuple["LayeredSection", np.ndarray, np.ndarray]:
    """The soundings that fit, how deep they were investigated, and the ground each one
    stands on."""
    from ofag.services.interpretation_service import LayeredSection

    runs = Path(RESULT_ROOT) / PROJECT_NAME.replace(" ", "-") / "runs"
    data = np.load(runs / str(state["aem_run_id"]) / "stitched_conductivity_section.npz")
    keep = data["chi_squared"] <= AEM_ACCEPTABLE_CHI_SQUARED
    section = LayeredSection(
        easting_m=data["receiver_locations_m"][keep, 0],
        northing_m=data["receiver_locations_m"][keep, 1],
        values=1.0 / data["conductivity_s_m"][keep],
        layer_top_depth_m=data["layer_top_depth_m"],
    )
    return section, *_published_per_sounding(section)


def _published_per_sounding(section: "LayeredSection") -> tuple[np.ndarray, np.ndarray]:
    """The contractor's investigation depth and ground elevation at each of our soundings, by
    nearest neighbour."""
    from scipy.spatial import cKDTree

    header = (AEM / "inversion_EM1DFM.csv").open(encoding="utf-8").readline().strip().split(",")
    wanted = ("X_NAD83UTM15N_M", "Y_NAD83UTM15N_M", DOI_COLUMN, GROUND_COLUMN)
    published = np.loadtxt(
        AEM / "inversion_EM1DFM.csv",
        delimiter=",",
        skiprows=1,
        usecols=[header.index(name) for name in wanted],
    )
    inside = (
        (published[:, 0] >= VOLUME[0] - 500)
        & (published[:, 0] <= VOLUME[1] + 500)
        & (published[:, 1] >= VOLUME[2] - 500)
        & (published[:, 1] <= VOLUME[3] + 500)
    )
    near = published[inside]
    index = cKDTree(near[:, :2]).query(section.stations_m)[1]
    return near[index, 2], near[index, 3]


def _write_local_ert_comparison(
    state: dict, section: "LayeredSection", doi_m: np.ndarray, output: Path
) -> int:
    """Compare fitted ERT sections with nearby AEM at measured electrode sites."""
    from scipy.spatial import cKDTree

    rows: list[dict[str, object]] = []
    aem_tree = cKDTree(section.stations_m)
    run_root = RESULT_ROOT / PROJECT_NAME.replace(" ", "-") / "runs"
    for item in state.get("ert_imports", []):
        run_id = state.get("ert_runs", {}).get(f"{item['site']}/{item['array']}")
        if not run_id:
            continue
        directory = run_root / run_id
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        chi = result.get("summary", {}).get("chi_squared")
        if not isinstance(chi, int | float) or chi > ERT_ACCEPTABLE_CHI_SQUARED:
            continue
        electrodes = np.load(item["electrodes_path"])
        along = electrodes[:, 0]
        positions = _site_positions(item["site"], along)
        distance, nearest = aem_tree.query(positions)
        geometry = np.load(directory / "mesh_geometry.npz")
        model = np.load(directory / "recovered_model.npy")
        coverage = np.load(directory / "model_coverage.npy")
        ert_tree = cKDTree(geometry["cell_centers_m"][:, :2])
        for electrode, (xy, station_distance, aem_index) in enumerate(
            zip(positions, distance, nearest, strict=True)
        ):
            if not (VOLUME[0] <= xy[0] <= VOLUME[1] and VOLUME[2] <= xy[1] <= VOLUME[3]):
                continue
            if station_distance > AEM_REACH_M:
                continue
            for depth_m in (5.0, 10.0, 15.0, 20.0, 25.0, 30.0):
                cell_distance, cell = ert_tree.query((along[electrode], -depth_m))
                aem_layer = section.layer_of(np.array([depth_m]))[0]
                ert_value = float(model[cell])
                aem_value = float(section.values[aem_index, aem_layer])
                rows.append(
                    {
                        "site": item["site"],
                        "array": item["array"],
                        "run_id": run_id,
                        "easting_m": float(xy[0]),
                        "northing_m": float(xy[1]),
                        "depth_m": depth_m,
                        "ert_ohm_m": ert_value,
                        "aem_ohm_m": aem_value,
                        "ert_over_aem": ert_value / aem_value,
                        "nearest_aem_m": float(station_distance),
                        "nearest_ert_model_cell_m": float(cell_distance),
                        "ert_coverage_drop_decades": float(coverage.max() - coverage[cell]),
                        "within_contractor_doi": bool(depth_m <= doi_m[aem_index]),
                    }
                )
    columns = (
        "site",
        "array",
        "run_id",
        "easting_m",
        "northing_m",
        "depth_m",
        "ert_ohm_m",
        "aem_ohm_m",
        "ert_over_aem",
        "nearest_aem_m",
        "nearest_ert_model_cell_m",
        "ert_coverage_drop_decades",
        "within_contractor_doi",
    )
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def build_model() -> None:
    """The units the two surveys support, and the one they do not."""
    from ofag.agent.gates import measure_terrain, refuse_unmeasured_terrain
    from ofag.core.schemas import UnitRule, UnitRuleKind
    from ofag.services.interpretation_service import InterpretationService

    projects, record = _project()
    folder = projects.folder(record.project_id)  # type: ignore[attr-defined]
    state = _load_state(folder)
    if not state.get("aem_run_id"):
        raise SystemExit("run invert_aem first")
    service = InterpretationService()
    section, doi, ground_at_sounding = _aem_layered_section(state)

    east = np.arange(VOLUME[0], VOLUME[1], MODEL_CELL_M[0]) + MODEL_CELL_M[0] / 2
    north = np.arange(VOLUME[2], VOLUME[3], MODEL_CELL_M[1]) + MODEL_CELL_M[1] / 2
    down = np.arange(0.0, MODEL_DEPTH_M, MODEL_CELL_M[2]) + MODEL_CELL_M[2] / 2
    grid_east, grid_north = np.meshgrid(east, north, indexing="ij")
    columns = np.column_stack([grid_east.ravel(), grid_north.ravel()])

    from scipy.spatial import cKDTree

    #: Every column hangs at the ground of the one sounding it reads, and not
    #: on a surface interpolated between them. The flight lines are 400 m
    #: apart, so an interpolated surface would draw the valley wall at a
    #: resolution the survey does not have, and it would put a column's depths
    #: under a different ground than the one they were measured from. This is
    #: blocky across lines on purpose, and the blocks are the line spacing.
    #:
    #: This is wrong if a terrain product of the survey's own is imported, in
    #: which case the columns should hang on that and the step between
    #: adjacent columns becomes an error rather than a statement.
    column_nearest = cKDTree(section.stations_m).query(columns)[1]
    column_ground = ground_at_sounding[column_nearest]

    depth = np.tile(down, columns.shape[0])
    nearest = np.repeat(column_nearest, down.size)
    ground = np.repeat(column_ground, down.size)
    centres = np.column_stack([np.repeat(columns, down.size, axis=0), ground - depth])
    volume = np.full(centres.shape[0], float(np.prod(MODEL_CELL_M)))

    terrain = measure_terrain(
        "the model volume",
        column_ground,
        source=f"{GROUND_COLUMN} in the EM1DFM delivery, at each column's own sounding",
    )
    for name in refuse_unmeasured_terrain({"the model volume": terrain}):
        print(f"          {name} carries fewer than ten steps of relief: it is nearly flat")
    print(f"          {terrain.summary}")

    picks = service.pick_contact(
        section, COVER_BAND_M, minimum_slope=COVER_MIN_SLOPE, increasing=True
    )
    cover = service.fit_surface("the resistivity rise", picks, targets_m=centres)
    cover_depth = cover.predict(centres[:, :2])

    reach = doi[nearest]

    rules = (
        UnitRule(
            name="below the investigation depth",
            source="AEM, nothing claimed",
            kind=UnitRuleKind.BELOW_SURFACE,
            surface="investigation",
        ),
        UnitRule(
            name="above the resistivity rise",
            source="AEM, not a rock contact",
            kind=UnitRuleKind.ABOVE_SURFACE,
            surface="cover",
        ),
        UnitRule(
            name="resistive: sand, gravel or bedrock",
            source="AEM, not separable",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="aem",
            threshold=RESISTIVE_OHM_M,
            below_threshold=False,
            reach_m=AEM_REACH_M,
        ),
        UnitRule(name="finer basin fill", source="AEM", kind=UnitRuleKind.REMAINDER),
    )
    model = service.assign_units(
        rules,
        cell_centres_m=centres,
        cell_volume_m3=volume,
        depth_below_ground_m=depth,
        surfaces={"investigation": ground - reach, "cover": cover_depth},
        sections={"aem": section},
    )

    # Vary the interpretation cut, horizontal reach, and the contractor's
    # investigation-depth bound.
    settings = np.array(
        [
            (threshold, radius, doi_scale)
            for threshold in (100.0, RESISTIVE_OHM_M, 140.0)
            for radius in (200.0, AEM_REACH_M, 400.0)
            for doi_scale in (0.8, 1.0, 1.2)
        ],
        dtype=float,
    )
    variants = np.empty((len(settings), len(depth)), dtype=np.uint8)
    for index, (threshold, radius, doi_scale) in enumerate(settings):
        variant_rules = list(rules)
        variant_rules[2] = rules[2].model_copy(update={"threshold": threshold, "reach_m": radius})
        variants[index] = service.assign_units(
            tuple(variant_rules),
            cell_centres_m=centres,
            cell_volume_m3=volume,
            depth_below_ground_m=depth,
            surfaces={"investigation": ground - reach * doi_scale, "cover": cover_depth},
            sections={"aem": section},
        ).unit
    sensitivity_path = Path(folder.imports_root) / "model_sensitivity.npz"  # type: ignore[attr-defined]
    np.savez_compressed(
        sensitivity_path,
        settings_threshold_ohm_m_reach_m_doi_scale=settings,
        unit_by_setting=variants,
        agreement_with_baseline_fraction=np.mean(variants == model.unit, axis=0),
    )

    path = Path(folder.imports_root) / "geological_model.npz"  # type: ignore[attr-defined]
    report = model.report.model_copy(update={"surfaces": (cover.report,)})
    np.savez_compressed(
        path,
        unit=model.unit,
        unit_names=np.array([rule.name for rule in rules]),
        unit_sources=np.array([rule.source for rule in rules]),
        cell_centres_m=centres,
        support_distance_m=model.support_distance_m,
        cover_depth_m=cover_depth,
        investigation_depth_m=reach,
        ground_elevation_m=ground,
        pick_locations_m=picks.locations_m,
        pick_depth_m=picks.depth_m,
        report=json.dumps(report.model_dump(mode="json")),
    )
    comparison_path = Path(folder.imports_root) / "ert_aem_local_comparison.csv"  # type: ignore[attr-defined]
    comparison_rows = _write_local_ert_comparison(state, section, doi, comparison_path)
    _save_state(
        folder,
        geological_model_path=path.as_posix(),
        model_sensitivity_path=sensitivity_path.as_posix(),
        ert_aem_local_comparison_path=comparison_path.as_posix(),
    )

    print(
        f"build     {centres.shape[0]:,} cells over {(VOLUME[1] - VOLUME[0]) / 1e3:.1f} by "
        f"{(VOLUME[3] - VOLUME[2]) / 1e3:.1f} km to {MODEL_DEPTH_M:.0f} m"
    )
    print(
        f"          the rise picked at {picks.depth_m.size:,} of {picks.attempted:,} soundings, "
        f"median {np.median(picks.depth_m):.1f} m; the fit predicts a held-out pick to "
        f"{cover.report.held_out_error:.1f} m against a spread of {cover.report.pick_spread:.1f}"
    )
    print()
    print(f"          {'unit':30s} {'share':>7s} {'cells':>9s}  resolved by")
    for item in model.report.units:
        print(
            f"          {item.name:30s} {100 * item.volume_share:6.1f}% "
            f"{item.cell_count:9,d}  {item.source}"
        )
    for item in model.report.units:
        if item.beyond_reach_share:
            print(
                f"          {item.name!r} declined to judge "
                f"{100 * item.beyond_reach_share:.1f}% of the volume, further than "
                f"{AEM_REACH_M:.0f} m from a sounding"
            )
    print()
    print(
        "          the base of the aquifer is not mapped: the pick lands on the same layer at "
        f"{1090} of {picks.attempted:,} soundings, which is the investigation depth cutting the "
        "profile rather than a contact. doi:10.3133/sim3423 separates till from bedrock on this "
        "survey; this case does not."
    )
    print(f"          written to {path.as_posix()}")
    print(
        f"          {comparison_rows:,} local ERT/AEM pairs in {comparison_path.as_posix()}; "
        "the ERT sections are not extended into the 3D volume"
    )
    print(
        f"          {len(settings)} declared-setting variants written to "
        f"{sensitivity_path.as_posix()}; agreement is not a calibrated probability"
    )


STAGES = {
    "import_ert": import_ert,
    "invert_ert": invert_ert,
    "invert_ert_baseline": invert_ert_baseline,
    "import_aem": import_aem,
    "invert_aem": invert_aem,
    "build_model": build_model,
    "report": report,
}

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage not in STAGES:
        raise SystemExit(f"usage: {Path(__file__).name} [{'|'.join(STAGES)}]")
    STAGES[stage]()
