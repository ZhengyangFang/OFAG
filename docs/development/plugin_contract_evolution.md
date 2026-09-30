# Plugin Contract Evolution for ERT and Seismic

This document plans how the OFAG core contracts must change before ERT and
seismic inversion can be registered as plugins, and how to sequence those
changes so the six existing plugins keep working unmodified.

It follows the phase-1 rule that new physics arrives through a versioned plugin
ID rather than by changing core contracts. That rule currently cannot be
honoured: several core types name individual methods, so today a new method
*must* edit the core. The goal here is to remove that need.

## 1. Where the current contracts stop scaling

### 1.1 `RunSpec` names every method

```python
class RunSpec(StrictModel):
    gravity_inversion: GravityInversionSpec | None = None
    magnetics_inversion: MagneticsInversionSpec | None = None
    gravmag_joint_inversion: GravMagJointInversionSpec | None = None
    tdem_inversion: TDEMInversionSpec | None = None
    tdem_batch_inversion: TDEMBatchInversionSpec | None = None
    tdem3d_forward: TDEM3DForwardSpec | None = None
```

`ofag.core.schemas` therefore imports and owns the configuration of every
physics method. Adding DC resistivity, induced polarization, 2D and 3D ERT,
traveltime tomography and full-waveform inversion would add six or more fields
and several thousand lines of method-specific validation to the core module
that is supposed to be method-agnostic. The dependency points the wrong way:
core knows plugins, instead of plugins knowing core.

The same coupling appears in `RunSpec.tiled_gravity_requires_treemesh`, a core
validator that encodes a gravity-plugin rule, and in `ProjectMethod`, a core
enum of `gravity | magnetics | aem` that the browser keys its navigation from.

### 1.2 One dataset per run

`RunSpec.dataset: DatasetSpec` is a single required dataset with a single
`physical_quantity` and `units`. Real ERT and seismic runs are multi-channel:

| Method | Channels in one run |
| --- | --- |
| DC + IP | transfer resistance (ohm) and chargeability, inverted together |
| Elastic FWI | pressure and/or multi-component particle velocity, per shot |
| Traveltime tomography | first-break picks, often P and S |

The joint gravity/TMI plugin already hit this and worked around it with
`JointObservationSpec` inside its own payload, while the mandatory top-level
`RunSpec.dataset` still has to be filled with one arbitrarily chosen channel.
That workaround should be promoted into the core rather than re-invented by
each new multi-channel method.

### 1.3 The declared event channel is dead

`InversionPlugin.execute` receives `emit_event: Callable[[RunEvent], None]`,
but `run_service.execute_registered_plugin` dispatches the child process with

```python
return plugin.execute(context, spec, lambda _event: None)
```

so every event passed to it is discarded. The channel that actually reaches the
interface is a `progress.jsonl` file that each plugin opens for itself and that
`RunService._ingest_progress_events` polls. That convention is not in the
protocol, is not typed, and is not documented.

The consequence is already visible: the gravity, magnetics and 1D TDEM plugins
write `progress.jsonl`, whereas `simpeg_gravmag_joint` routes its per-iteration
callback through `emit_event`. The cross-gradient joint inversion therefore
reports no iterations at all in the workbench. ERT and FWI would inherit the
same trap, and FWI runs are long enough that a silent progress channel is not a
cosmetic problem.

### 1.4 `RunEvent` assumes one misfit triple

```python
iteration, phi_total, phi_data, phi_model
```

That shape cannot express:

- **DC+IP**, which has two data misfits that must be readable separately.
- **FWI frequency continuation**, which is a sequence of stages, each with its
  own iteration counter restarting at zero. A flat `iteration` field makes the
  monitor plot a sawtooth with no way to label the bands.
- The **existing joint inversion**, which already has two data misfit terms and
  currently has to sum them into `phi_data`.

### 1.5 `supports_restart` is a flag with no method behind it

`CapabilityManifest.supports_restart: bool` exists; `InversionPlugin` has no
checkpoint or resume method. Nothing verifies the flag. For gravity and 1D TDEM
that is tolerable. An FWI run is hours to days, so restart is a requirement,
not a capability advertisement.

This interacts with a live defect in `RunService`: job handles live only in
memory, so a run that was `RUNNING` when the service restarted is reloaded from
disk in `RUNNING` and never reconciled, because `_refresh_locked` returns early
when `handle is None`. At gravity runtimes that is an annoyance. At FWI
runtimes it makes the service unusable.

### 1.6 `execute` returns one terminal result

FWI frequency continuation and IRLS-style staged ERT produce a meaningful model
at the end of *each* stage. The current contract can only return a single
`RunResult` at the very end, and `ArtifactManifest` has no field to say which
stage an artifact came from, so intermediate models cannot be distinguished.

### 1.7 Mesh contracts are 3D-only

`TensorMeshSpec.shape: tuple[int, int, int]`. 2D FWI and 2.5D ERT are the normal
production cases for both methods. There is also no way to state that the
simulation grid differs from the inversion grid, which FWI always needs: the
propagation grid is set by dispersion and CFL stability, the model grid by
resolution and regularization.

### 1.8 `QuantityType` has no electrical or elastic quantities

Missing for ERT: electric potential, transfer resistance, apparent resistivity,
resistivity, chargeability. Missing for seismic: P- and S-wave velocity, bulk
density, pressure, particle velocity, traveltime, frequency.

One trap deserves naming. `DENSITY_CONTRAST` is canonicalised to `g/cm^3`
because that is what potential-field inversion uses. Seismic needs *absolute*
bulk density, conventionally `kg/m^3`. These must be two distinct
`QuantityType` members, not one type with two units. Reusing `DENSITY_CONTRAST`
for seismic density would be the same class of error as the workbench aliasing
`tmi_min_nt` into a field named `gravity_min_mgal`, except in the numerical
core where nothing downstream could catch it.

## 2. Design rules for the evolution

1. The four-method plugin protocol stays: `manifest`, `validate`,
   `estimate_resources`, `execute`. Anything new is an optional, separately
   declared capability.
2. `ofag.core` must stop importing plugin configuration types. After this work,
   adding a method means adding a plugin module and one registry line.
3. Every change is additive and versioned. The six existing plugins and every
   persisted `run_spec.yaml` keep validating without edits.
4. Units stay explicit and quantity-typed at every new boundary. A new physical
   quantity gets a new `QuantityType` member, never a reused one.

## 3. Proposed changes

### 3.1 Move the physics payload out of the core

Introduce `schema_version: "1.1"` alongside the existing `"1.0"`.

```python
class RunSpec(StrictModel):
    schema_version: Literal["1.0", "1.1"] = "1.0"
    ...
    # 1.1: opaque to the core, validated by the selected plugin.
    physics: dict[str, JsonValue] | None = None

    # 1.0: retained, deprecated, still validated as today.
    gravity_inversion: GravityInversionSpec | None = None
    ...
```

The protocol gains one method that returns the plugin's own Pydantic model:

```python
class InversionPlugin(Protocol):
    def physics_model(self) -> type[BaseModel] | None: ...
```

`RunService.validate` then does the second validation pass:

```python
plugin = registry.get(spec.plugin_id)
model = plugin.physics_model()
if model is not None and spec.physics is not None:
    typed = model.model_validate(spec.physics)
```

Typing is not lost, it moves to where the physics lives. The core keeps
ownership of units, CRS, mesh, executor, state machine and artifacts. An ERT
plugin defines `ERTInversionSpec` in its own module and the core never imports
it.

Migration is mechanical and can be done one plugin at a time: a plugin that
returns `None` from `physics_model` keeps reading its typed 1.0 field. The 1.0
fields are removed only once every plugin and every stored spec has moved,
which is a `schema_version: "2.0"` decision, not part of this work.

The gravity-specific `RunSpec` validator moves into the gravity plugin's
`validate`, where the same rule can be reported as a proper `ValidationIssue`
with a remediation instead of a Pydantic exception.

### 3.2 Promote multi-channel data into the core

Generalise `JointObservationSpec` into a core type:

```python
class DataChannelSpec(StrictModel):
    channel_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    dataset: DatasetSpec
    observations_path: str = Field(min_length=1)
    data_uncertainty: QuantitySpec


class RunSpec(StrictModel):
    datasets: tuple[DataChannelSpec, ...] = ()
    dataset: DatasetSpec  # 1.0 compatibility; equals datasets[0] under 1.1
```

DC+IP declares two channels; FWI declares one channel per component and
references a shot manifest inside its physics payload rather than inlining
thousands of shots the way `TDEMBatchInversionSpec` inlines soundings.

That distinction matters. `TDEMBatchInversionSpec.soundings` inlines up to
10,000 independent problems because each sounding is genuinely a separate
inversion sharing only its configuration. Seismic shots are the opposite: they
are thousands of sources contributing to *one* shared model, so they belong in
a manifest file referenced by path, not in the `RunSpec` body.

### 3.3 Make the event channel real

Move the sink into `PluginContext` and have the executor implement it as the
`progress.jsonl` writer that already exists:

```python
class PluginContext:
    def __init__(self, artifact_root: Path, run_dir: Path,
                 emit: Callable[[RunEvent], None]) -> None: ...
```

`emit_event` on `execute` is then either removed or made an alias of
`context.emit`. Either way there is exactly one progress channel, it is typed,
it is in the contract, and the joint inversion starts reporting iterations
without any change to the plugin.

This is the single highest-value item on the list, it is independent of
everything else here, and it fixes a current defect.

### 3.4 Generalise `RunEvent`

```python
class RunEvent(StrictModel):
    ...
    stage: str | None = None          # "band_2.5hz", "irls", "dc", "ip"
    stage_index: int | None = None
    stage_total: int | None = None
    misfits: dict[str, float] = {}    # {"dc": ..., "ip": ...}
```

`phi_total`, `phi_data` and `phi_model` stay for compatibility and keep meaning
the aggregate. `misfits` carries the per-term breakdown, which the existing
joint inversion can start populating immediately.

### 3.5 Restart as an opt-in protocol

```python
@runtime_checkable
class RestartablePlugin(Protocol):
    def checkpoint_interval(self) -> int | None: ...
    def resume(self, context: PluginContext, spec: RunSpec,
               checkpoint: Path) -> RunResult: ...
```

Existing plugins are unaffected because they simply do not satisfy it. The
registry can then assert that `manifest().supports_restart` matches
`isinstance(plugin, RestartablePlugin)`, which turns an unverified boolean into
a checked one.

Before this is useful, `RunService` must reconcile orphaned `RUNNING` records
on startup. That is a prerequisite, not a follow-up.

### 3.6 Stage-tagged artifacts

```python
class ArtifactManifest(StrictModel):
    ...
    stage: str | None = None
```

One field is enough to let a run emit a recovered model per frequency band and
let the workbench group them. Prefer this over parent/child runs whenever the
stages share model state; reserve the batch-TDEM parent/child pattern for
genuinely independent sub-problems.

### 3.7 Mesh dimensionality — done, pulled forward from phase E

`TensorMeshSpec` accepts two or three axes; `origin`, `cell_size` and
`cell_widths` must agree with `shape`, and `dimension` reports which it is.

The axis semantics are fixed and documented on the type. Three dimensions are
Easting, Northing, Elevation. **Two dimensions are Easting and Elevation**: the
section lies in x-z and Northing is the invariant strike direction, which is
what 2.5D resistivity assumes. A 2D mesh therefore never carries a Northing
extent. The four volume methods reject one explicitly instead of guessing, and
the shared width builder is now arity-generic.

This was brought forward because ERT is 2.5D/3D from its first version rather
than 3D-only.

`TreeMeshSpec` stays three-dimensional. A 2D quadtree is possible in discretize
and is worth having for electrode-following refinement, but nothing needs it
yet.

The simulation grid stays out of the core: it is engine detail in the same
sense as SimPEG's `mesh_builder_xyz`, so it belongs in the plugin's physics
payload, and only the model/inversion mesh stays in `RunSpec.mesh`.

### 3.8 New quantity types

Additive, with canonical SI units consistent with the existing policy:

| Member | Canonical unit | Used by |
| --- | --- | --- |
| `ELECTRIC_POTENTIAL` | `volt` | ERT |
| `TRANSFER_RESISTANCE` | `ohm` | ERT (V/I) |
| `APPARENT_RESISTIVITY` | `ohm * meter` | ERT |
| `RESISTIVITY` | `ohm * meter` | ERT model |
| `CHARGEABILITY` | `dimensionless` | IP |
| `P_WAVE_VELOCITY` | `meter / second` | seismic |
| `S_WAVE_VELOCITY` | `meter / second` | seismic |
| `BULK_DENSITY` | `kilogram / meter ** 3` | seismic |
| `PRESSURE` | `pascal` | seismic |
| `PARTICLE_VELOCITY` | `meter / second` | seismic |
| `TRAVELTIME` | `second` | tomography |
| `FREQUENCY` | `hertz` | FWI |
| `QUALITY_FACTOR` | `dimensionless` | attenuation (Q) |
| `THOMSEN_PARAMETER` | `dimensionless` | anisotropy ε, δ, γ |

The last two exist because the seismic target is **land field data**. See
[seismic_engine_selection.md](seismic_engine_selection.md) §6 for the other
corrections that forces, in particular that the source wavelet is an inverted
quantity rather than only an input, and that the misfit function has to be part
of the spec rather than a plugin implementation detail.

`RESISTIVITY` and `CONDUCTIVITY` are reciprocals, not alternative units of one
quantity, so `validate_unit_dimension` must keep them distinct and any
conversion between them stays an explicit, adapter-level operation.

### 3.9 Method identity comes from the registry

Replace the `ProjectMethod` enum with a declared field:

```python
class CapabilityManifest(StrictModel):
    ...
    method: str          # "gravity", "magnetics", "aem", "ert", "seismic"
    dimensionality: tuple[Literal[1, 2, 3], ...]
```

`GET /plugins` then tells a caller which methods exist, and enabling ERT in a
project stops requiring an edit to a core enum. The desktop went further in the
same direction: its inversion form is generated from the plugin's own
`physics_model()`, so a registered method is configurable without a page, a
form or a union type being written for it.

## 4. Sequencing

Each phase leaves the tree green: ruff, ruff format, mypy and the full pytest
suite, which since the desktop replaced the browser workbench is the whole
gate.

**Phase A — no new physics, fixes current defects. Done.** The event sink moved
into `PluginContext` and the discardable `emit_event` parameter is gone from the
protocol, so the joint inversion reports iterations for the first time.
`RunEvent` gained `stage`/`stage_index`/`stage_total`/`misfits`,
`ArtifactManifest` gained `stage`, orphaned `RUNNING` records are reconciled on
adoption, and the ERT and seismic quantity types are registered.

**Phase B — multi-channel data. Done.** `DataChannelSpec` and `RunSpec.datasets`
are in the core, and `simpeg.joint.gravmag.cross_gradient` was migrated onto
them as the proving case: it now declares its gravity and TMI observations as
channels and refers to them by `channel_id` instead of carrying its own copies.

Two invariants moved out of that plugin and into the core, where every future
method gets them: a channel's uncertainty must match its own observed quantity,
and all channels in a run must share one coordinate convention. Resolution
failures — a dangling `channel_id`, or a channel carrying the wrong quantity —
are reported by the plugin as `ValidationIssue`s with remediations rather than
as schema exceptions.

`RunSpec.dataset` is unchanged and still required. Retiring it in favour of
`datasets` belongs with the `schema_version` bump in phase C.

**Phase C — physics payload. Done.** `RunSpec` gained `schema_version: "1.1"`,
an opaque `physics` payload and a typed `physics_as()` reader;
`InversionPlugin` gained `physics_model()`. `RunService.validate` checks the
payload against the model the plugin declares and turns each Pydantic error
into a `ValidationIssue` with a dotted field path, so a malformed payload is
reported rather than reaching a solver.

`simpeg.aem.tdem1d` is the proving case and reads its configuration from either
form. A test round-trips one inversion through both and asserts the summaries
match, so the 1.1 path is exercised end to end while every stored 1.0 spec
keeps working. A run may not state both forms at once.

**A new method no longer needs a field in `ofag.core.schemas`.**

**Phase C completed — every method declares its model.** The five plugins left
on 1.0 were migrated together, so `physics_model()` now returns a model for
every registered method except `ofag.fixture.gravity3d`, which has no physics
configuration at all rather than an undeclared one.

Each reads through one resolver, `spec.physics_as(X) or spec.<typed_field>`,
and the typed fields stay until `schema_version: "2.0"`. Validation issues name
the form the run actually used, through `configuration_field`: a caller told
its problem is at `physics.simulation.engine` when it wrote
`magnetics_inversion.simulation.engine` has been pointed at a field it did not
write, which is a nuisance to a person and an impasse to anything acting on the
report.

Two forms for one thing is how a discrepancy grows, so
`tests/test_physics_payload_equivalence.py` pins the property that makes it
safe: both forms resolve to the same object and validate to the same report,
down to the field paths. The typed fields can then be retired by deleting them
rather than by finding out which behaviour depended on which form.

This was done because it is what the agent layer stands on. A method whose
parameters cannot be enumerated cannot be tuned by anything that did not
already know them, and six of nine could not be. It also finished the desktop:
those six had no generated form and fell back to hand-edited JSON.

Extending the generator to every model then exposed four defects in it, all of
the same shape — the form could not express something the model could, and
reported the gap as the person's error. `field.default` is pydantic's sentinel
for anything with a `default_factory`, so an untouched gravity form reported
ten errors against a model that constructs with no arguments. A spin box at six
decimals turned a 1e-08 threshold into zero, which the model refuses. An
optional sub-model was a group of blank fields rather than an absence. A
`QuantitySpec` default never reached its editor. The invariant is now a test
over every registered model: an untouched form is valid exactly when the model
needs no input.

**Phase D — ERT.** SimPEG already provides
`simpeg.electromagnetics.static.resistivity` and `induced_polarization`, so
this reuses the existing engine adapter and is mostly a matter of electrode
geometry and a DC+IP two-channel spec. It is the right first customer of
phases B and C precisely because it is low-risk.

**Phase E — restart and mesh dimensionality.** 3.5 and 3.7, driven by what
Phase D actually needed.

**Phase F — seismic.** See below, and
[seismic_engine_selection.md](seismic_engine_selection.md) for the engine
survey and its two sub-phases.

**Phase E — restart. Done.** `RunState.INTERRUPTED` distinguishes a run whose
process was lost from one that went wrong, `PluginContext.checkpoint` and
`resume_from` give a plugin somewhere to save and find its own progress, and
`RunService.resume` dispatches the same spec again. What a checkpoint holds is
opaque to the core, exactly as `RunSpec.physics` is: only the plugin knows what
a half-finished solve of its method looks like. The spec it was written against
is fingerprinted, so a configuration edited between the interruption and the
resume cannot silently continue somebody else's solve. `simpeg.pf.gravity3d`
implements it through the directive it already used for progress, which is what
proves the contract on a real solver rather than only on a fixture.

The 2D mesh half of this phase was pulled forward into phase D for resistivity.

**Phase F1 — elastic FWI, contract validated.** `deepwave.fwi.elastic2d` is a
2D elastic land-line inversion through Deepwave, and its value is the three
contracts it exercises rather than its science output. The physics payload
carries the grid, geometry, wavelet, stages and misfit with no field added to
`ofag.core.schemas`. Every iteration reports which band of the frequency ladder
it is in, so a staged solve's restarting iteration count is readable. A
checkpoint records the parameters, the wavelet *and the stage index*, without
which a resumed run would repeat the whole ladder from the bottom.

The three corrections §5 of
[seismic_engine_selection.md](seismic_engine_selection.md) said land field data
forces are all in the spec rather than in the plugin: the wavelet is optionally
an inverted quantity and is published as an artifact either way, the misfit
function is configuration, and frequency continuation is explicit.

Real data moved the misfit one level further down, from the run to the stage.
The envelope is phase-blind by construction, which is what lets it survive a
starting model more than half a cycle out, and is exactly why it cannot finish
a land record: a surface wave's velocity *is* a phase. On the Soda Lake line an
envelope-only ladder left the recovered Vs implying a 404 m/s Rayleigh wave
against the 335 m/s the gather plainly shows. `FwiStageSpec.misfit` overrides
the run's, so envelope down the ladder and L2 at the top — the usual sequence —
is expressible. Each stage is normalised by its own functional's baseline,
because the envelope baseline of a narrowband record is twice the L2 one and
mixing them would step the reported misfit at a stage boundary for a reason
that is not in the model. Attenuation
and anisotropy are not modelled and the manifest says so.

Phase F2 -- 3D elastic with anisotropy and topography -- needs a different
engine; SWEEP is the candidate.

## 5. What seismic will additionally force

The target is **land field data**, which makes an elastic solver with a free
surface mandatory rather than a later refinement; acoustic FWI cannot represent
ground roll. The engine comparison is in
[seismic_engine_selection.md](seismic_engine_selection.md).

SimPEG does not provide full-waveform inversion. Seismic therefore means a
**second engine**, not a second SimPEG plugin — Deepwave, SWEEP, Devito or
SPECFEM behind `ofag.engines.<name>`. Everything in `docs/architecture.md` about
the engine adapter boundary has so far been validated against exactly one
engine, `ofag.engines.simpeg`. Seismic is the first real test of whether that
boundary holds, and it is worth expecting to discover that some things
currently assumed to be core are in fact SimPEG-shaped.

Two consequences are worth planning for now rather than later:

- `ExecutorSpec.max_workers` is capped at 64 and `LocalProcessExecutor` runs one
  child process. FWI needs domain decomposition across MPI ranks. The `DASK`
  and `SLURM` executor kinds are already declared; seismic is what makes them
  mandatory.
- Wavefield checkpointing for the adjoint state is engine-internal and must not
  leak into `ArtifactManifest`. Only the per-stage model, gradient norm and
  misfit history are portable artifacts.

## 6. What this does not change

The plugin registration path is unchanged: implement `manifest`, `validate`,
`estimate_resources` and `execute`, then add one `registry.register(...)` line
in `default_registry()`. `PluginContext` stays narrow — no API handles, no
store handles. SimPEG or any other engine object still never enters a schema or
an artifact. Runs stay immutable.
