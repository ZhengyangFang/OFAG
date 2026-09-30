# Reproducing the OFAG manuscript cases

This guide maps the TLE manuscript's three field cases to the public source
records, code, and figure assets in this repository. Run all commands from the
repository root with Python 3.11 or 3.12. Numerical stages require the relevant
optional dependencies and can take substantially longer than the offline
`ofag --json doctor --self-test` fixture. Source datasets and generated results
are not distributed in this repository.

## Data and local layout

| Case | Source records used by the case | Local input directory | Detailed account |
| --- | --- | --- | --- |
| Utah FORGE | Gravity and model `10.15121/1542061`; gravity and TEM `10.15121/1452733`; MT `10.15121/1776598`; seismic interpretation `10.34191/MP-169-H`; additional well and terrain sources | `data/case1_Utah FORGE/` | [Utah FORGE](case1_forge.md#the-data) |
| Cedar Rapids | ERT `10.5066/P9YXJDHX`; AEM `10.5066/P9BS882S` | `data/case2_Cedarrapids/` | [Cedar Rapids](case2_cedar_rapids.md#the-data) |
| Llano | Geophysical and borehole release `10.5066/F72Z14G6`; 3DEP terrain separately | `data/case3_Llano/` | [Llano](case3_llano.md#the-data) |

The case notes record source identifiers, conventions, exclusions, and reported
results. The tracked [source manifests](data_sources/) map renamed Cedar Rapids
and Llano inputs to delivered files and list the local FORGE gravity, seismic,
well, TEM, MT, and terrain inputs. The FORGE terrain raster and cropped MT
model are derived local files, not original release files. A reader starting
from a fresh clone must still fetch and prepare the source data. The repository
does not offer a one-command download of all three cases, an automated recipe
for every derived input, or checksums for every downloaded file.

## Case stages

The commands below name the stages implemented by the case scripts; they do
not substitute for acquiring and placing the source files first. Run each stage
only after its inputs and prior stage outputs are available. `report` reads the
stored results and states what the case did and did not complete.

| Case | Main stages in execution order | Output directory |
| --- | --- | --- |
| Utah FORGE | `prepare`, `invert`, `import_tem`, `invert_tem`, `import_mt`, `invert_mt`, `doi`, `build_model`, `compare`, `report` in `scripts/case1_forge.py` | `Result/Utah-FORGE/` |
| Cedar Rapids | `import_ert`, `invert_ert`, `import_aem`, `invert_aem`, `build_model`, `report` in `scripts/case2_cedar_rapids.py` | `Result/Cedar-Rapids/` |
| Llano | `import_ert`, `invert_ert`, `import_srt`, `invert_srt`, `import_tdem`, `invert_tdem`, `build_model`, `report` in `scripts/case3_llano.py` | `Result/Llano-Uplift/` |

For example, `uv run python scripts/case3_llano.py report` checks the saved
Llano state without rerunning an inversion. The source scripts define additional
comparison and diagnostic stages. To make run outputs visible in the workbench
project register, use `uv run python scripts/register_case_datasets.py` after
the corresponding case stages.

## Manuscript figure provenance

The manuscript currently numbers its figures 1–8. Seven tracked notebooks,
`examples/Fig2.ipynb` through `examples/Fig8.ipynb`, each correspond to one
manuscript figure and export panels to ignored `examples/Figure/fig2/` through
`examples/Figure/fig8/` directories. They do not assemble the final manuscript
figure files. Cached cell output and execution timestamps are cleared from the
tracked notebooks; run the cells with the external datasets and saved case
results to regenerate their panels. The final figure deck and manuscript files
are local, ignored assets.

| Manuscript figure | Subject | Tracked computational source |
| --- | --- | --- |
| 1 | Agent architecture | No dedicated figure script in the repository |
| 2 | Three sites and survey layouts | `examples/Fig2.ipynb` |
| 3 | FORGE gravity workflow and inversion | `examples/Fig3.ipynb` and `scripts/case1_forge.py` |
| 4 | FORGE modelling and conditional gravity assessment | `examples/Fig4.ipynb` |
| 5 | Cedar Rapids ERT processing and inversion | `examples/Fig5.ipynb` and `scripts/case2_cedar_rapids.py` |
| 6 | Cedar Rapids modelling and sensitivity | `examples/Fig6.ipynb` |
| 7 | Llano diagnosis and reinversion | `examples/Fig7.ipynb` and `scripts/case3_llano.py` |
| 8 | Llano model and sensitivity | `examples/Fig8.ipynb` |

The notebooks produce individual panels, so the eight assembled figures cannot
be regenerated from a clean checkout. Figure 1 has no editable source here;
the Figure 3 workflow schematic and Figure 5 workflow ribbon were assembled
manually. Final panel assembly for Figures 2–8 also remains outside this
repository. Keep the source data and result paths used by every panel explicit.

The existing panel filenames help locate the source calculations:

| Manuscript figure | Notebook panels used for the main data views |
| --- | --- |
| 2 | `Fig2a_locator`, `Fig2b_utah_forge`, `Fig2c_cedar_rapids`, `Fig2d_llano_uplift`, `Fig2e_method_legend` |
| 3 | `Fig3b_gravity_data_residual`, `Fig3c_seismic_basement`, `Fig3d_density_cutaway_3D`, `Fig3e_density_section_EW`, `Fig3e_density_section_NS`; the workflow schematic has no notebook source |
| 4 | `Fig4a_seismic_basement`, `Fig4b_TEM_resistivity_section`, `Fig4c_MT_resistivity_models`, `Fig4d_density_cutaway_3D`, `Fig4e_geological_model_3D`, `Fig4f_gravity_assessment` |
| 5 | `Fig5a_reciprocal_schematic`, `Fig5b_data_retained`, `Fig5c_error_model`, `Fig5d_misfit_lambda`, `Fig5e_ERT_sections`, `Fig5f_ERT_AEM_depth_profiles`; the workflow ribbon has no notebook source |
| 6 | `Fig6a_AEM_quasi3D`, `Fig6b_ERT_sections`, `Fig6c_well_GX2`, `Fig6d_interpreted_model_3D`, `Fig6e_section_L20031`, `Fig6e_label_stability` |
| 7 | `Fig7a_ERT2_section`, `Fig7a_SRT2_section`, `Fig7b_TEM_current`, `Fig7c_SRT2_picks` |
| 8 | `Fig8a_model_3D`, `Fig8b_model_depth_maps`, `Fig8c_composite_log` |

These are stems of PNGs exported by the notebooks, not final manuscript panel
letters. Verify the final assembly against each caption before release.

The [run-specific audit register](case_audit.md) records the later review of
saved inversions. The case scripts and notebooks computed the gravity
assessment and 27-setting sensitivity panels. Figure 8 uses the saved Llano
model built before the retrospective review of ERT1 and TEM, both of which
received vetoes for quantitative geological use. It is a conditional model.

## Reported limits to retain

The case reports and manuscript should continue to show the ERT runs that did
not meet their target misfit, the investigation-depth and survey-coverage
limits, the unassigned volume at Llano, and the sensitivity of interpreted
classes to the declared settings. These limits define which parts of each
model the observations support.
