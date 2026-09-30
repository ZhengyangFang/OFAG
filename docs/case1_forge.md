# Utah FORGE field case

This is the paper-facing record for the Utah FORGE gravity, TEM, and MT case.
The [reproduction guide](reproducibility.md) maps the case scripts and figure
panels. The full [development history](development/case1_forge_history.md)
remains available for tracing decisions; its failure entries are not evidence
that an agent independently discovered those problems during the final run.

## The data

| Input | Public source | Local path |
| --- | --- | --- |
| 3D gravity data, models, and report | DOI 10.15121/1542061 | `data/case1_Utah FORGE/gravity/` |
| Gravity stations and 68 TEM soundings | DOI 10.15121/1452733 | `data/case1_Utah FORGE/gravity/`, `tem/` |
| Phase 3 MT sites and published model | DOI 10.15121/1776598 | `data/case1_Utah FORGE/mt/` |
| Reflection interpretation and survey geometry | DOI 10.34191/MP-169-H | `data/case1_Utah FORGE/seismic/` |
| Well and pad locations | DOI 10.15121/1838418 | `data/case1_Utah FORGE/wells/` |
| Terrain | USGS 3DEP 1 arc-second | `data/case1_Utah FORGE/dem/` |

The tracked [file manifests](data_sources/) map local names to their releases.
The terrain raster is clipped and reprojected to EPSG:26912; the MT model is a
local spatial crop. Raw inputs and generated results are outside Git.

## Processing and inversion

`scripts/case1_forge.py` imports the Phase 2C gravity survey, matches 323
stations to the published inversion, converts the Bouguer anomaly from its
2.67 g/cm³ reduction density to the 2.55 g/cm³ modelling convention, and
uses the original seismic top-of-granite surface from the released workspace.
The modified surface is kept as a comparison, not silently substituted as the
reference surface.

Two 3D gravity inversions start from the same two-layer reference. The smooth
model reports χ² 0.754 and residual RMS 0.026 mGal; the current petrophysical
run reports χ² 0.890 and 0.0283 mGal. The smooth model correlates +0.773 with the
published model; the petrophysical model correlates +0.613. These are
comparisons under different regularization, not proof that one density model is
the unique ground truth.

The case also inverts 66 selected TEM soundings as independent layered models
(median χ² 0.497; 53 meet the fit target) and 82 MT sites as layered models
(median χ² 0.757; 76 meet the fit target). A 2D MT profile was
built but is not used for the final interpretation because its comparison with
the published 3D model was poor. The case script's `report` stage reads these
states from saved runs.

## Interpretation and checks

The density classes are prior values drawn from the published report and
associated well information, not new bulk-density measurements. The recovered
petrophysical class shares are volume-weighted within the declared model box.
The gravity result provides a conditional mass comparison around the adopted
basement geometry and is compared with the published density model. It does
not independently determine the basement depth. The electrical methods are
interpreted only over the depth ranges their observations support.

The paper figures draw from `examples/Fig2.ipynb`,
`examples/Fig3.ipynb`, and `examples/Fig4.ipynb`. The notebooks export panels, and final
figure assembly is documented in the [reproduction guide](reproducibility.md).
The selected saved runs were adopted and reviewed retrospectively through the
Audit Agent role on 2026-09-29. The [audit register](case_audit.md) records the
run-specific verdicts: the two main gravity fits and the bounded TEM/MT 1D
results passed for their stated uses; the MT 2D result was vetoed for the
integrated interpretation. This was not an agent-mediated audit during the
original case-script execution.

## Limits

- Gravity has 323 observations for a much larger 3D mesh. Cell-by-cell
  geological claims are not warranted by the fit statistic.
- The published and OFAG inversions differ in filtering and regularization.
  The 20 m upward continuation used by the published work is not reproduced.
- The TEM interpretation is shallow: below a median 226 m, the layered
  profiles return to their starting halfspace.
- The MT result consists of independent 1D fits in ground with measured
  two-dimensional behaviour. The TEM and MT surveys do not overlap closely
  enough to establish a jointly constrained basement depth.
- The petrophysical class densities are not independently measured in this
  case. The petrophysical fit is less similar to the published density model
  than the smooth fit.

Run `uv run python scripts/case1_forge.py report` after preparing the
external inputs and completing the stages listed in the
[reproduction guide](reproducibility.md).
