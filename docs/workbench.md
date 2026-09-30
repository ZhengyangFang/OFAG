# Working in OFAG

## From data to a result

1. Open or create a project. The header shows its folder; **Open folder** opens it.
2. Import a survey in **Data**, stating its coordinate system and units. The other
   pages update their catalogues when data is registered.
3. Use **Setup** for survey previews and any required preparation, then follow
   **Next: Inversion**. The selected dataset follows into the inversion page.
4. In **Inversion**, choose a method by its readable name. Its status reports
   missing dependencies or missing data kinds; **Ready to configure** is not a
   claim that a solver has validated the configuration.
5. Edit the basic settings. A successful historical run on the selected dataset
   supplies its full configuration, including mesh, units, errors and executor.
   Expand **Mesh and run inputs** or **Advanced parameters** for additional controls.
   Common arrays have editable rows and an **Edit as JSON** option. Units travel
   with physical values. **Check** remains the authority on valid parameters.
6. Choose a completed smaller trial when required, then **Create and start**.
   OFAG opens **Results**, where execution state and progress update automatically.

Automatic catalogue refresh preserves the active inversion draft, run selection
and completed model slice. Geological editing tables are not overwritten by
progress updates: **Reload saved edits** explicitly replaces their unsaved edits.
Changing a parameter, method, dataset or project invalidates the previous check.

## Calculations and cancellation

Parameter sensitivity and geological surface interpolation run in isolated
background processes. Their cancel buttons terminate only those calculations.
Changing project or closing the window also stops these background calculations.
Numerical inversion runs keep their existing RunService execution and cancellation.

An Agent stop request cancels the numerical run currently owned by that conversation.
An in-progress provider request must return before its thread can stop. The panel
distinguishes a stop request from a completed stop.

## Comparing and choosing results

Select two rows in **Results** using Ctrl or Shift and click **Compare**.
The dialog shows summaries and configuration differences. Compatible cell
models use the same colour limits. Different quantities have separate scales;
explicit reference positions align profile distances. This does not establish a
shared coordinate system or geological equivalence. Runs without cell geometry have summary/configuration
comparison. Layered or other specialised artifacts remain available in each run's
normal result view.

**Use for this dataset** stores one user-selected run per method and dataset group in
`runs/preferred_results.json`. The choice survives reopening and a portable copy.
It is shown in Interpretation and in the Agent's project summary. A user preference
does not grant a scientific audit; execution state, preference and audit status
are separate. Vetoed results cannot be selected as preferred.

Batch sections have line, depth and measured chi-squared controls. Unknown or
above-limit soundings are marked; filtering is disabled without per-site fit data.

**Interpretation → Survey map** shows stations with available project map
coordinates. Missing profile alignment is listed beside the map. Coverage alone
does not establish resolution or justify extrapolation between methods.

## Building and revising models

**Interpretation → Build model** edits a saved recipe or creates a new one.
Create a grid with measured ground, load selected results, and specify rules and
spatial support. A build requires diagnosed and independently audited source runs.
Every build saves a new model and its recipe; earlier versions remain available.
Legacy case models without recipes are identified explicitly.

The recipe reader supports layered batches, individual TDEM soundings and recovered
mesh models. Single soundings need a surveyed location. 2D profiles need an origin,
azimuth and elevation offset. Mesh threshold rules need an explicit support radius.
Use measured resolution depth limits; low misfit alone does not establish resolution.
**Export report** saves a Markdown project review under `runs/reports/`.

## Working with the agents

The **Agents** dock has task suggestions, a current-action line and a **History**
viewer for this project's saved conversations. Viewing history never re-executes
tools and does not resume the previous model context.

**Review project changes** shows recorded before/after configuration changes for
mutating tool calls. Long values are abbreviated; the saved project records hold
the full values. Related run, dataset and model identifiers have a **Locate** action that
selects the corresponding item in the workbench. The final answer and the
collapsible tool details remain in the conversation. Details start collapsed;
failures expand them automatically. Internal UI selection metadata is kept out
of the question bubble.

Agents can inspect runs, prepare complete historical drafts, validate/estimate/sample/
execute those drafts by id, select results, read model recipes and export reports.
Large site arrays remain in the saved draft instead of depending on truncated chat
output. `ofag.describe_model` describes grid, rule and source requirements.

## Distribution and maintenance

Agent knowledge files are included under `ofag/_resources/docs` in the wheel.
Source checkouts read `docs/`; installed packages use `importlib.resources` to
locate the packaged copy, independently of the launch directory. Rebuild the wheel
after changing code or knowledge files. `scripts/smoke_wheel.ps1` checks both the
worker self-test and Agent knowledge from a consumer installation.

Generated test/checker caches can be regenerated. Keep `Result/`, field data,
paper figures and local `.claude/skills/` resources when cleaning a checkout.
Office lock files and paper PowerPoint files are excluded from source releases.
