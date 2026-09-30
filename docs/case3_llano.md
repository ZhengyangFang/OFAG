# Llano Uplift field case

This paper-facing record covers the Granite Gravel Aquifer study area. The
[reproduction guide](reproducibility.md) maps the external data, script stages,
and figures. The full [development history](development/case3_llano_history.md)
preserves diagnostic details and earlier decisions.

## The data

| Input | Source | Local path |
| --- | --- | --- |
| Two ERT profiles, two refraction profiles, one transient EM sounding, boreholes, and self-potential survey | USGS DOI 10.5066/F72Z14G6 | `data/case3_Llano/` |
| Bare-earth terrain | USGS 3DEP 1 m, ScienceBase item 619c3717d34eb622f6931b2b | `data/case3_Llano/` after `scripts/fetch_llano_dem.py` |

The [source manifest](data_sources/llano.tsv) maps local files to the
release. The 3DEP terrain is a separate input; no DOI is asserted for that
specific tile. Input data and generated results are not in Git.

## Processing and inversion

`scripts/case3_llano.py` imports two resistivity profiles, the refraction
picks, the transient EM sounding, and available borehole information. The
final sections use a common 3DEP lidar elevation frame. The release's two
electrode-elevation lists disagree, and the lidar changes section position
more than ERT misfit; the terrain is kept for consistent spatial comparison.

ERT1 and ERT2 use the same declared inversion settings. Their χ² values
are 3.079 and 0.760, respectively. ERT1's poorer fit is concentrated in
17 of 243 readings and remains reported. The SRT2 refraction inversion keeps
80 of 96 first arrivals after removing zero-offset and repeated default
picks. Its current 5.385 ms error estimate comes from five valid reciprocal
pairs; χ² is 0.254, and rays reach 382 of 514 mesh cells (74%). The older
3.69 ms / χ² 0.499 values belong to a previous run in the development record.

The TEM sounding needs its stated current, column names, waveform turn-off,
and error treatment handled explicitly. With an error floor supported by
overlapping sweeps, its χ² is about 10.2. This result is retained as a
limited fit, not adjusted to a target by changing an unsupported error model.
The final run records and case script determine the precise value to report.

## Model and checks

The interpretation combines ERT coverage, the local TEM sounding, and
refraction only where their measurements reach. In the 195 × 195 m,
40 m deep model volume, 68.4% is not assigned a geological unit because
observational support is insufficient. The 800 Ω·m granite cut is a declared
interpretive threshold applied near one sounding, not a measured sharp
bedrock contact. Refraction and ERT do not independently resolve that deep
surface.

At the ERT–TEM overlap, both methods place the ground on the same side of
the 800 Ω·m threshold at twelve sampled depths, while resistivity magnitudes
differ by a median factor of 1.88. The 27-setting sensitivity calculation
varies the granite threshold, sounding reach, and ERT coverage cutoff.
Across these choices, 26,836 of 64,000 cells change label at least once;
agreement is sensitivity to declared settings, not a calibrated probability.
The unassigned volume is kept visible.

The relevant panels are exported by `examples/Fig2.ipynb`,
`examples/Fig7.ipynb`, and `examples/Fig8.ipynb`; see the [figure mapping](reproducibility.md#manuscript-figure-provenance).
The selected saved runs were adopted and reviewed retrospectively through the
Audit Agent role on 2026-09-29. The [audit register](case_audit.md) records the
run-specific verdicts: ERT2 and SRT2 passed within their coverage; ERT1 and
the single TEM sounding were vetoed as quantitative inputs to geological
labelling because of their misfit. The existing scripted model predates this
review and is not an audited model. This was not an agent-mediated audit during
the original case-script execution.

## Limits

- ERT1 misses the target fit and the crossing seismic profile does not
  sample the two short line segments carrying its largest residuals.
- The TEM sounding misses a nominal unit-misfit target, and only one sounding
  reaches the deeper resistivity rise.
- The survey geometry constrains lines and a local sounding, not a uniformly
  resolved 3D aquifer boundary.
- The borehole refusal horizon is inside the aquifer material; it is not
  evidence for the regional base of weathering.
- The granite threshold and spatial reach affect assigned volume. Cells
  without adequate coverage remain unassigned.

Run `uv run python scripts/case3_llano.py report` after the stages in the
[reproduction guide](reproducibility.md).
