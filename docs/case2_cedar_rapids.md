# Cedar Rapids field case

This paper-facing record covers the Cedar River alluvial aquifer case. The
[reproduction guide](reproducibility.md) maps data, script stages, and figures.
The full [development history](development/case2_cedar_rapids_history.md)
preserves the decisions and diagnostic evidence.

## The data

| Input | Source | Local path |
| --- | --- | --- |
| Raw ERT surveys and borehole geophysics | USGS DOI 10.5066/P9YXJDHX | `data/case2_Cedarrapids/ert/`, `wells/` |
| RESOLVE airborne EM observations and contractor inversion | USGS DOI 10.5066/P9BS882S | `data/case2_Cedarrapids/aem/` |
| Published geological interpretation for comparison | USGS DOI 10.3133/sim3423 | External publication |

The tracked [source manifest](data_sources/cedar_rapids.tsv) maps local and
original filenames. The releases include thirteen ERT surveys at five sites,
four logged wells inside the model volume, and airborne EM observations.
Input data and generated results are not distributed in this Git repository.

## Processing and inversion

`scripts/case2_cedar_rapids.py` imports ERT, checks electrode geometry,
performs reciprocal and contact-resistance quality control, constructs an
error model, and runs thirteen baseline 2D ERT inversions. Six meet their
target fit and seven do not. The manuscript figure uses selected later ERT
runs; their fit must be read from those run records. The poorer fits remain
reported; a completed solver run
is not counted as a good fit solely because it returned a model.

The AEM stage inverts the airborne observations as layered soundings and
compares them with the contractor's released inversion. A local depth-profile
comparison shows that ERT and AEM give similar median resistivity through the
shared shallow interval, with a peak near 25 m. The apparent agreement weakens
below the ERT coverage limit. The ERT lines are not extended between their
measured positions to create a 3D model.

## Model and checks

The interpreted volume is based on AEM coverage and the contractor's
investigation-depth bound. It uses measurement-oriented labels: a shallow
zone above the resistivity rise, finer basin fill, and a resistive zone that
could contain sand, gravel, or bedrock. The resistive zone is not labelled as a
mapped aquifer or bedrock contact. The model covers 88,200 cells to 98 m depth;
1.7% falls below the investigation-depth bound. The median contractor
investigation depth is 112 m, with spatial variation.

A shallow resistivity-rise surface is selected at 1,219 of 1,240 fitted
soundings and has 3.6 m held-out prediction error. Boreholes show that this
resistivity feature is not consistently the fine-to-coarse lithologic
boundary. At GX-2, a logged bedrock contact occurs within a smoothly rising
AEM resistivity profile, so the data do not isolate a bedrock surface.

The 27-setting model sensitivity calculation varies resistivity cutoff,
horizontal reach, and investigation-depth scaling. Across those settings,
23.9% of model cells change label at least once (76.1% retain their label).
This measures sensitivity
to interpretation choices, not a probability of each geological class.

The relevant figure panels are exported by `examples/Fig2.ipynb`,
`examples/Fig5.ipynb`, and `examples/Fig6.ipynb`; see the [figure mapping](reproducibility.md#manuscript-figure-provenance).
The selected saved runs were adopted and reviewed retrospectively through the
Audit Agent role on 2026-09-29. The [audit register](case_audit.md) records the
run-specific verdicts: three selected ERT lines and the AEM batch passed for
their bounded uses; Edwards CW3 and Ellis CW1 were vetoed as quantitative
inputs to geological labelling because they missed the declared fit target.
This was not an agent-mediated audit during the original case-script execution.

## Limits

- Seven of thirteen ERT sections miss the target fit, including several
  high-misfit lines. They remain visible in the case record.
- ERT is local to five lines; it does not constrain the entire 4.5 km² volume.
- The AEM model uses the contractor's investigation-depth estimate rather than
  an independently calculated depth of investigation for this inversion.
- The four wells are too sparse and shallow to place a regional bedrock
  surface from this case alone.
- Resistivity classes do not uniquely identify lithology, and the
  sensitivity calculation shows dependence on declared thresholds.

Run `uv run python scripts/case2_cedar_rapids.py report` after the stages
listed in the [reproduction guide](reproducibility.md).
