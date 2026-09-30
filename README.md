# OFAG

One Framework for All Geophysics is a modular-monolith platform for geophysical
forward modelling and inversion. It keeps units, run specifications, execution
and artifacts in a shared application core, while numerical plugins delegate
the physics to established libraries such as SimPEG.

For the three field cases and Figure 1–8 in the TLE manuscript, begin with the
[reproduction guide](docs/reproducibility.md). It identifies source releases,
case stages, figure panels, and the steps that a fresh clone cannot yet run
without separately acquired data or manual figure assembly.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and use Python 3.11 or 3.12. From the
repository root, this offline fixture verifies the CLI, worker process, and
artifact output without downloading field data or installing a solver:

```powershell
uv sync
uv run ofag --json doctor
uv run ofag --json doctor --self-test
uv run ofag --json plugins
```

The self-test creates a temporary fixture, waits for its worker, verifies the
saved result and removes the temporary files. For your own run configuration,
use `ofag validate <run.yaml>` then `ofag run <run.yaml>`; `ofag status <run-id>`
and `ofag artifacts <run-id>` inspect the saved run later.
Run these commands from the repository root because the default
`Result/` and `artifacts/` paths are relative to the current directory.

Install only the extras needed for your work. For example, `uv sync --extra
desktop --extra simpeg` enables the Qt workbench and SimPEG methods, then
`uv run ofag workbench` opens it. Other extras are `pygimli`, `seismic`,
`ert-formats`, `tables`, `raster`, `gempy`, and `mcp`. `doctor` reports missing
optional modules; `--self-test` also runs an offline child process and reads
its artifact. It does not establish that a numerical solver can finish a
particular dataset. Run `uv run pytest` for the full local test suite.

To hand a wheel to another Windows user, run `uv build`. The resulting files
are in `dist/`; the recipient can create a Python 3.11 environment and install
the wheel with the desired extras:

```powershell
uv python install 3.11
uv venv OFAG --python 3.11
uv pip install --python OFAG/Scripts/python.exe 'dist/ofag-0.1.0-py3-none-any.whl[desktop,simpeg]'
OFAG/Scripts/ofag.exe --json doctor --self-test
OFAG/Scripts/ofag.exe workbench
```

Run those commands from the repository root. The repository also includes
`scripts/smoke_wheel.ps1`, which builds it, installs it into a
fresh temporary environment, and runs the same self-test. CI exercises that
script on Windows.

## Implemented numerical plugins

- `ofag.fixture.gravity3d`: offline execution fixture; not a field inversion.
- `simpeg.pf.gravity3d`: 3D gravity inversion on TensorMesh and TreeMesh.
- `simpeg.pf.magnetics3d`: 3D total-magnetic-intensity inversion for scalar
  induced susceptibility on TensorMesh and TreeMesh.
- `simpeg.joint.gravmag.cross_gradient`: shared-mesh gravity/TMI joint
  inversion with normalized cross-gradient coupling.
- `simpeg.aem.tdem1d`: single-sounding layered TDEM inversion.
- `simpeg.aem.batch_tdem1d`: sequential orchestration of independent 1D TDEM
  soundings with a stitched conductivity section.
- `simpeg.aem.tdem3d_forward`: 3D TDEM forward modelling on TensorMesh and
  TreeMesh, including paired survey geometry and time gates.
- `simpeg.aem.fdem1d`: layered frequency-domain EM inversion.
- `simpeg.nsem.mt1d_batch`: independent layered MT soundings.
- `simpeg.nsem.mt2d`: 2D MT profile inversion; profile distances and TE/TM mode
  must be specified by the user.
- `pygimli.ert.dcip`: resistivity and induced-polarization inversion.
- `pygimli.seismic.traveltime`: seismic traveltime inversion.
- `deepwave.fwi.elastic2d`: 2D elastic full-waveform inversion.

The registry lists 13 plugins, including the fixture. Numerical plugins need
their corresponding optional dependencies. `uv run ofag --json plugins` is the
authoritative list for the installed version.

Finished inversions are read into one labelled volume by
[the interpretation service](docs/interpretation.md) — not a joint inversion:
each unit is assigned by the single method that resolves its depth, and every
cell records which method that was and how far its nearest measurement lay.

The three field cases use different combinations of these capabilities on
published data. Their records document both the reported results and the
limits of the supporting observations:
[Utah FORGE](docs/case1_forge.md) — gravity, TEM and magnetotellurics over a
geothermal test bed — [Cedar Rapids](docs/case2_cedar_rapids.md) — ground
resistivity and airborne EM over an alluvial aquifer — and
[the Llano Uplift](docs/case3_llano.md) — resistivity and seismic refraction
crossing at two points over weathered granite.

## Reproducing the manuscript cases

Start with the [reproduction guide](docs/reproducibility.md). It maps the
source releases for the three cases, the required local paths, the case stages,
and the current Figure 1–8 sources. Field data and generated runs are not included in
this repository. The figure notebooks currently export panels rather than the
assembled manuscript figures; the guide identifies that remaining step.

The case scripts (`scripts/case*.py`) write into `Result/<project>/` through
the services. After running one, `uv run python scripts/register_case_datasets.py`
puts the data its runs inverted on the project's register, so the Data,
Results and Lineage stages and the agents see it without importing it again.
It reads the runs, is safe to run twice, and never touches a dataset imported
by hand.

See [architecture](docs/architecture.md), [unit policy](docs/unit_policy.md),
[validation and audit](docs/validation.md), and the
[run-specific case audit register](docs/case_audit.md) for the current mechanism.
A plugin's configuration is its own
`physics_model` schema, which `ofag.describe_plugin` returns to an agent, so it
is not restated in prose.

## Desktop workbench

See [the workbench guide](docs/workbench.md) for automatic project updates,
background calculations, editable parameter tables, result comparison and Agent history.

```powershell
uv sync --extra desktop
uv run ofag workbench
```

A Qt application over the same service layer the HTTP API adapts. There is one
implementation of every operation -- `ProjectService`, `RunService`, the
importers, the preparation services -- and two adapters onto it: FastAPI for
anything driving OFAG over a wire, and the desktop for a person sitting in
front of it. The desktop holds no physics and no file formats of its own.

It is divided into six stages rather than by method:

| Stage | What it is for |
| --- | --- |
| Data | Bring surveys in and see what the project holds. Every importer states the unit its file is in, because no format reliably says. |
| Setup | What the inversion will solve over: the part of a survey to use, and the starting model. |
| Inversion | Configure a run, ask what the data can see before spending an hour on it, then start it. |
| Results | Every run, what it produced, and how much data produced it. |
| Interpretation | Named units, logged boreholes, and the surfaces between them. |
| Lineage | What came from what, read from the runs themselves. |

The method is chosen inside the stage that needs one, so a seventh method adds
no page. The inversion form is generated from the plugin's own
`physics_model()`, so it exists the moment a plugin is registered.

PySide6 rather than PyQt6: it is Qt's own binding and LGPL, where PyQt6 is GPL
and would decide the licence of everything importing it. It is an optional
extra, because a headless machine running inversions should not need a GUI
toolkit -- the CLI and `uv run ofag serve` work without it.

## Where a project keeps its work

Everything one project produces lives under a single directory named after it:

```
Result/<project>/
    project.json     the record: name, CRS, elevation reference, methods
    workspace.json   the datasets, meshes, site models and geology
    imports/         canonical SI copies, one directory per dataset
    runs/            one directory per run: artifacts, progress, checkpoint
```

The path is shown in the window, and `--result-root` puts it elsewhere. A
project used to be spread across three roots tied together only by
identifiers, which meant it could not be copied, archived or sent to a
colleague without knowing all three conventions.

SimPEG and pyGIMLi produce authoritative observation-map and model-slice
artifacts; the desktop draws sections and survey geometry with matplotlib,
which is already a dependency of both.

The CLI puts a run with a valid `project_id` in that project's `runs/` folder;
an unknown project ID is rejected. Runs without a project ID use the shared
`artifacts/` root. `status`, `cancel` and `artifacts` locate runs by ID across
those folders.

HTTP import routes accept `?project_id=<uuid>` and register imported datasets
in that project's `workspace.json`; run routes use the `project_id` in the
`RunSpec`. Existing requests without a project ID still use the shared roots.
Specify the project ID when building a project so its imports and runs stay
together. The MT EDI directory importer is available at `/datasets/mt-edi`.

When a whole project folder is copied, OFAG rebases references to files in its
own `imports/` and `runs/` folders on the next open. Original external sources,
such as a SEG-Y file kept outside the project, remain external in a plain copy.
Use the desktop's **Export portable copy** button or
`ofag project-pack <project-id> --destination <folder>` to copy every referenced
external input and rewrite run records, results and checkpoints. Export refuses
missing sources and active runs; large field files make the copy large.
Resource estimates are rough heuristics and
have not been calibrated to the user's machine. CLI, desktop and HTTP starts
require a completed smaller run of the same method when the estimate exceeds
60 seconds. A person can explicitly waive that check; the choice and estimate
are saved as `preflight.json` beside the run. CLI options are
`--sample-run-id` and `--allow-unchecked-large-run`; the HTTP start endpoint
accepts the same names as query parameters. The agent obligation ledger keeps
its stricter sample requirement.

The HTTP server is local by default (`127.0.0.1`). For network deployment,
set `OFAG_ENV=production`, `OFAG_API_TOKEN`, and `OFAG_ALLOWED_HOSTS` to a
comma-separated list of public hostnames. `ofag serve --host 0.0.0.0` refuses
to start without production mode and a token. Deployment still needs its own
network access controls and operational setup.

**Talking to the agents.** The desktop's **Agents** button opens a panel beside
the stages where you talk to the lead agent about the open project; it
delegates to the data, inversion, modelling, audit and literature roles, each
starting from a fresh context with its own tools, and asks you before any call
that removes something. `ofag agent-chat --artifact-root <runs folder>` is the
same conversation in a terminal. The model is yours to choose under
**Model…**, over any of three protocols -- Anthropic Messages, OpenAI chat
completions, the OpenAI Responses API -- with presets for Anthropic, OpenAI,
Gemini, DeepSeek, Qwen (Alibaba Cloud Model Studio), Kimi, GLM (Zhipu AI),
Doubao (Volcano Engine Ark), MiniMax,
SiliconFlow, OpenRouter, OpenCode Go and Zen, xAI, Mistral, Groq, Together, a
relay of either protocol, and local servers (Ollama, LM Studio, vLLM)
for data that must not leave the machine. A base URL can be pasted with or
without `/v1`, or as the full endpoint. **Test connection**, or
`ofag agent-test`, sends one small request and shows the server's own answer. The key is read from the environment variable you name
(`ANTHROPIC_API_KEY` by default) or typed for the session; it is never written
to disk, and the settings live in `~/.ofag/`, not in the project. With a cloud
model, what the tools return about your data is sent to that provider; the
panel says which host. Every conversation is kept in the project's
`conversations/` folder.

An external agent reaches OFAG over MCP (needs the `mcp` extra).
`ofag agent-tools` serves the whole tool surface; `ofag agent-tools --role audit`
serves one role's tools only (`lead`, `data`, `inversion`, `modelling`,
`audit`, `literature`, `developer`), acting under that role's name in the
ledger, and offers the role's brief as an MCP prompt. `ofag agent-brief audit
--task "..."` prints that brief, retrieved passages included. A run is read
into a model only after a role other than the one that ran it has audited it.

## Current limits when sharing this software

- A wheel can be shared and installed as above; there is no signed, clickable
  desktop installer yet.
- Published field-case data are fetched separately. The small fixture does not
  establish that every numerical engine works with a new user's survey.
- A second process can request cancellation of a live run. It reports
  `CANCELLED` only after the owner process has stopped its worker; if the owner
  cannot acknowledge immediately, it still reports `RUNNING`.
- The source code is [MIT licensed](LICENSE). Published datasets and external
  figures described in the case notes keep their original source terms.

## Development and evaluation records

The [procedure](docs/agent_validation_and_debugging.md) and
[lesson corpus](docs/lessons/) are part of the agent's runtime knowledge and
record which findings came from development and which were reported by agents.
The [legacy case and design records](docs/development/) support that history.
The [exploratory benchmark](docs/development/benchmark/) records its own leakage and
scoring limits; it does not establish better answer quality than an agent
without these obligations.
The [release scope](docs/release_scope.md) distinguishes public source records,
runtime wheel resources, external data and local-only material.
