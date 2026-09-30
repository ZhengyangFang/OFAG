# Retrospective review of saved field-case runs

On 2026-09-29 (local time), three project-scoped Codex review contexts examined
the saved case evidence. The OFAG inversion role then called `ofag.adopt_run`
and `ofag.diagnose` for the current selected saved runs; the role-restricted
Audit Agent tool `ofag.audit` recorded pass or veto decisions using those
reviews and the saved run evidence. Codex supplied the model judgments because
the locally configured OFAG model provider was unavailable. This was three
project reviews, not 19 separately initialized model contexts. The calls and
responses are retained locally in
`Result/audit_reviews/2026-09-29_ofag_audit_calls.jsonl`; the project ledgers
are under the ignored `Result/` tree.

**Review scope.** These verdicts were recorded after the case scripts completed their runs through application services. They do not certify that the original execution used the agent audit gate. A pass supports only the bounded use in the evidence column; it does not establish a unique geological unit or boundary. A veto excludes the run from the agent-mediated model gate. This review did not rebuild earlier scripted models.

The source datasets, full run artifacts and append-only ledgers are not distributed with the code repository. The run IDs and measured summaries below permit comparison with an exported project, but a fresh clone cannot independently verify these verdicts without those artifacts and external data.

A [machine-readable extract](case_audit_ledger.jsonl) contains the adoption,
diagnosis and audit entries for these 19 runs, with actor, time, specification
fingerprint and evidence. It omits unrelated historical entries and raw data.
Its `at` timestamps are UTC, which falls on 2026-09-30 for this local review.

| Case | Selected result | Run ID | Audit | Saved fit | Evidence and use boundary |
| --- | --- | --- | --- | --- | --- |
| Utah-FORGE | `run_id` | `895508ac-14bf-477d-a9bd-38e0d52ba722` | Pass | χ² 0.754 | 323 gravity observations; chi2 0.754 and RMS 0.02605 mGal support numerical fit. Seismic basement is a prior; gravity mass and depth are nonunique. |
| Utah-FORGE | `pgi_run_id` | `f6118041-f748-49b2-9324-9fd584380f1b` | Pass | χ² 0.890 | 323 observations; chi2 0.890 and current RMS 0.02831 mGal support the fitted density model, conditional on published density priors; basement depth is not independently validated. |
| Utah-FORGE | `tem_run_id` | `c65babb6-866a-4a28-a4a7-901d01a0dfb8` | Pass | χ² 0.497 | 66 layered TEM soundings; median chi2 0.497, 53 meet target and 13 do not. Only fitted, shallow and depth-supported portions may inform interpretation. |
| Utah-FORGE | `mt_run_id` | `4dcfd549-0c77-4dcc-aa7f-a1c324f340a5` | Pass | χ² 0.757 | 82 independent 1D MT sites; median chi2 0.757, 76 meet target. Use within resolved depths; 2D behaviour limits regional inference. |
| Utah-FORGE | `mt2d_run_id` | `df02ab3b-99bf-46d8-94b8-ce13185ffd09` | Veto | χ² 0.316 | MT2D profile is excluded from the integrated model after poor comparison with the published 3D model; a low median fit alone does not validate geological use. |
| Utah-FORGE | `doi_run_ids/weighted/0` | `19a2ce29-3a75-41a4-9d04-94ea7c93940d` | Pass | χ² 0.762 | Gravity depth-sensitivity reference run, chi2 0.762; use only in the declared comparative DOI calculation, not as a unique geology model. |
| Utah-FORGE | `doi_run_ids/weighted/1` | `a77874a9-1fcf-4f1e-b2bf-378f640c7c34` | Pass | χ² 0.817 | Gravity depth-sensitivity reference run, chi2 0.817; use only in the declared comparative DOI calculation, not as a unique geology model. |
| Utah-FORGE | `doi_run_ids/unweighted/0` | `be088a5c-7228-4f04-8fff-307b2168b12b` | Pass | χ² 0.995 | Gravity depth-sensitivity reference run, chi2 0.995; use only in the declared comparative DOI calculation, not as a unique geology model. |
| Utah-FORGE | `doi_run_ids/unweighted/1` | `7e8a375e-11f6-49a6-a0d9-1c01c006f9b7` | Pass | χ² 0.487 | Gravity depth-sensitivity reference run, chi2 0.487; use only in the declared comparative DOI calculation, not as a unique geology model. |
| Cedar-Rapids | `ert_runs/Edwd_CW3/dipole-dipole` | `fcf12d91-ec5f-438b-b6ca-3ce03786c50f` | Veto | χ² 2.156 | Selected ERT run chi2 2.156 exceeds the stated target of 2; Edwd line is outside the model volume and must not justify an in-volume geological label. |
| Cedar-Rapids | `ert_runs/Ellis_CW1/dipole-dipole` | `059ccdb2-2ea8-45df-a2c7-be6266e66101` | Veto | χ² 3.017 | Selected Ellis ERT run chi2 3.017 exceeds target of 2; coverage masking does not repair the data fit. Show as a limited comparison, not an accepted input to geological labelling. |
| Cedar-Rapids | `ert_runs/SVPDemo-Day/dipole-dipole` | `f28aac20-a839-449f-beb7-79a5cc8f5628` | Pass | χ² 0.928 | Selected ERT run chi2 0.928 meets target; use only within its measured line and coverage depth, without extrapolating across the AEM volume. |
| Cedar-Rapids | `ert_runs/SVP_CW6/dipole-dipole` | `54945129-29c4-41e0-ba50-086c46f2a40a` | Pass | χ² 0.994 | Selected ERT run chi2 0.994 meets target; use only within its measured line and coverage depth, without extrapolating across the AEM volume. |
| Cedar-Rapids | `ert_runs/SVP_S10/dipole-dipole` | `208ef57a-403d-4599-8271-f3d72bee7eba` | Pass | χ² 0.883 | Selected ERT run chi2 0.883 meets target; use only within its measured line and coverage depth, without extrapolating across the AEM volume. |
| Cedar-Rapids | `aem_run_id` | `750150b4-992d-4651-a752-83db24def96b` | Pass | χ² 0.818 | 1374 AEM soundings; median chi2 0.818 and 1234 meet target. Exclude the remaining 140 and apply the contractor investigation-depth bound; resistivity class is not unique lithology. |
| Llano-Uplift | `ert_runs/ERT1` | `8a6f9410-8e15-4b68-9461-855c07b12af0` | Veto | χ² 3.079 | ERT1 chi2 3.079 and 17 of 243 readings exceed 15 percent residual; not an accepted quantitative input to geological labelling without a revised fit or stronger justification. |
| Llano-Uplift | `ert_runs/ERT2` | `c23c0e02-658b-44ce-9006-3af66743689a` | Pass | χ² 0.760 | ERT2 chi2 0.760 supports the local resistivity section, only within measured line and coverage depth; it does not resolve a regional 3D boundary. |
| Llano-Uplift | `srt_runs/SRT2` | `e4d22769-db5f-4ef3-8151-0a44d97e71b8` | Pass | χ² 0.254 | SRT2 chi2 0.254 from 80 retained picks and five valid reciprocal pairs; rays touch 382 of 514 cells, so interpretation is limited to ray-supported ground. |
| Llano-Uplift | `tdem_run` | `a72a37e5-3f33-45ef-916e-e5a9cec17f57` | Veto | χ² 10.158 | One TEM sounding has chi2 10.158 and 22 of 67 normalized residuals above 3 sigma; its 800 ohm-m crossing cannot establish a sharp regional contact. |

The median χ² shown for a batch is not the fit of every sounding. The FORGE TEM batch fits 53/66 soundings to target; FORGE MT 1D fits 76/82; Cedar AEM fits 1,234/1,374. Failed individual soundings or sites are not approved by a passing batch verdict.

The case scripts and notebooks computed the FORGE gravity assessment and the Cedar and Llano 27-setting sensitivity analyses. The retrospective audit evaluated saved inversion runs; it did not generate those calculations. Llano ERT1 and TEM were vetoed as quantitative model inputs. The existing scripted geological model is therefore a conditional interpretation rather than an Audit Agent-approved model.
