# OFAG Architecture

OFAG is a modular monolith. The application core owns canonical schemas, units,
coordinate conventions, run state transitions, artifacts, and plugin discovery.
Physics plugins own only validation and numerical work; adapters isolate engine
details such as SimPEG meshes, directives, and engine units.

```text
CLI / API / UI / Agent Gateway
            |
     application services
            |
 core schemas + units + registry + run store
      |                    |
 plugins  <--- engine adapters / executors ---> artifacts + events
```

Each run has its own `RunSpec` and `RunRecord`. The service validates the spec
through the selected plugin and dispatches it through an executor. Project
records, workspaces, run records, events, and portable artifacts are persisted
on disk independently of numerical engine objects. The service also keeps
in-memory state while coordinating active jobs.

The deterministic synthetic gravity fixture validates the fast contract path
without a numerical dependency. The plugin registry currently contains 13
plugins: the fixture, nine SimPEG adapters for potential fields and
electromagnetics, two pyGIMLi adapters for ERT and traveltime, and one
Deepwave elastic FWI adapter. The registry in `src/ofag/plugins/registry.py`
is the authoritative list. Numerical work runs in local child processes;
adapters handle engine-specific units and write portable SI artifacts. The
numerical engines remain optional dependencies.

The services have two adapters onto them and neither is privileged. FastAPI
serves anything driving OFAG over a wire, which is what an agent does. The Qt
desktop in `ofag/desktop/` calls the same services in-process, which is what a
person does. Both own interaction state only; neither reimplements a solver or
a unit conversion, and an operation that exists for one of them exists for the
other because it exists in the service beneath.

That is also the rule for deciding where something belongs. A desktop widget
tempted to read a file format, convert a unit or compute a physical judgement
is describing a service that has not been written yet: writing it there would
put the capability out of reach of everything driving OFAG remotely, which for
this project is the case that matters most.

Visualization has the same adapter boundary as numerical work. SimPEG's
`plot2Ddata` and Discretize mesh slice plotting generate portable PNG
observation-map and model-slice artifacts in the backend. Neither adapter
reproduces those engine-aware figures; the desktop draws what a bounded API
returns -- sections, survey geometry and misfit histories -- with matplotlib,
which SimPEG and pyGIMLi already depend on. The API model-view endpoint
consumes persisted TreeMesh geometry rather than
numerical engine objects. It bounds the active-cell response for a browser
client without claiming to turn an irregular mesh into a voxel volume.

Run comparison is likewise an application-layer adapter. It reads completed
run summaries and only pairs one-dimensional `.npy` artifacts with matching
artifact type, physical quantity, unit, and shape. It reports candidate-minus-
baseline mean, RMS, and maximum absolute differences without entering any
numerical engine.
