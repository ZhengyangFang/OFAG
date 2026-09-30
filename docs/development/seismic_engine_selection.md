# Seismic Engine Selection

This document records the engine survey behind phase F of
[plugin_contract_evolution.md](plugin_contract_evolution.md), and the
corrections that land field data forces on the contract design.

Scope assumption: **land acquisition, real field data**. That assumption drives
almost every conclusion here, so revisit this document if the target changes to
marine.

## 1. The propagator is the small part

For field data the wave propagator is roughly a fifth of the work. The rest is
SEG-Y geometry from trace headers, trace editing, muting, gain, bandpass,
denoising, **source wavelet estimation**, robust misfit functions to survive
cycle skipping, multi-scale frequency continuation, anisotropy, attenuation,
and checkpointing at scale.

Most of that layer is what OFAG already owns: `services/data_import.py`, the
unit policy, QC, and the `RunService` state machine. So the selection rule is:

> Choose a library that is **only a propagator with gradients** and a clean
> API. Do not choose a framework that owns the workflow.

A framework with its own orchestration, checkpointing and scheduler
integration would duplicate and fight `Executor` and `RunRecord`. That rule
alone decides several candidates.

## 2. What land specifically requires

| Requirement | Why |
| --- | --- |
| **Elastic** | Ground roll is a Rayleigh wave. Acoustic FWI cannot represent it, so on land it is unusable for shallow targets whether the surface waves are the signal or the thing being muted. |
| **Free surface** | Land records are dominated by the free-surface interaction. |
| **Irregular free surface** | Real land lines have topography. |
| **Vs as a target** | Surface waves constrain Vs; that is usually the point of near-surface land work. |
| **Anisotropy (at least VTI)** | Normal for real data. |
| **Attenuation (Q)** | The weathering layer is strongly attenuative. |
| **Vibroseis handling** | Correlated sweeps need different source treatment than dynamite. |

Marine-oriented acoustic-only tooling fails the first two rows, which removes
most of the easy options.

## 3. Candidates

| Library | Install | Elastic | 3D elastic | Free surface | License | Owns workflow |
| --- | --- | --- | --- | --- | --- | --- |
| [Deepwave](https://github.com/ar4/deepwave) | `pip install deepwave` | yes | **no, 2D only** | yes (vacuum method) | MIT | no |
| [SWEEP](https://github.com/DeepWave-KAUST/sweep) | `pip install sweepx` | yes | **yes** (`Elastic3D`, `ElasticTTISG3D`) | yes, incl. irregular | MIT | no |
| [Devito](https://github.com/devitocodes/devito) | pip + C compiler | you write it | you write it | you write it | MIT | no |
| [JUDI.jl](https://github.com/slimgroup/JUDI.jl) | Julia + Devito | limited | acoustic/TTI focus | — | MIT | partly |
| [SPECFEM2D/3D](https://github.com/SPECFEM) | compile Fortran + mesher | yes | yes | **yes, rigorous** | GPL-3.0 | no (SeisFlows does) |
| [SeisFlows](https://github.com/adjtomo/seisflows) | pip + SPECFEM | via SPECFEM | via SPECFEM | via SPECFEM | BSD-2 | **yes** |
| [Stride](https://github.com/trustimaging/stride) | conda | acoustic focus | — | — | **AGPL-3.0** | **yes** |
| [PyFWI](https://github.com/AmirMardan/PyFWI) | `pip install PyFWI` | yes | no | — | **GPL-3.0** | no |

### Ruled out

- **Stride** is medical ultrasound only, with no geophysics examples, and is
  AGPL-3.0. A copyleft-network licence is not acceptable for a platform that
  may be distributed or hosted.
- **SeisFlows** explicitly owns workflow orchestration, checkpointing and
  scheduler interaction. That is the same job as `RunService` and `Executor`.
  Note this rules out *SeisFlows*, not *SPECFEM*: OFAG can adapt SPECFEM
  directly as an engine and keep its own orchestration.
- **PyFWI** is 2D only, GPL-3.0, and research-grade activity.
- **JUDI.jl** is technically strong with demonstrated marine field-data FWI,
  but it is Julia over Devito. From a Python plugin that is a language and
  process boundary, and its elastic/land story is weaker than its acoustic
  marine story. If Devito is chosen, reimplement JUDI's layer in Python rather
  than adopting Julia.

### Deepwave

2D elastic on a staggered grid with Lamé parameterisation and a free surface
via the improved vacuum method. Excellent API: pure PyTorch tensors in and out,
`pip install deepwave`, MIT, no build step. Multi-GPU is shot batching over
`DataParallel`; there is no domain decomposition, so the model must fit in one
device's memory.

**The elastic solver is 2D only.** For land that caps it at 2D lines. It cannot
be the production engine for a 3D land survey.

### SWEEP

A KAUST framework, MIT, `pip install sweepx`, PyTorch and JAX backends with a
native CUDA path, and a published description in
[arXiv:2604.14189](https://arxiv.org/abs/2604.14189). Its solver list is the
only pip-installable set covering the full land requirement matrix:
`Elastic3D`, `ElasticTTISG3D`, and documented irregular free-surface
(topography) handling.

Two caveats:

- **No viscoelastic solver.** Attenuation exists only as 2D `ViscoAcoustic`.
  Near-surface Q on land is real, so this is a genuine gap.
- **Young and small** (tens of GitHub stars). Physics coverage is right;
  production hardening is unproven. Test it against a real dataset early
  rather than discovering its limits in phase F2.

### SPECFEM

Spectral elements handle topography and the free surface more rigorously than
any finite-difference option here, which is precisely why earthquake seismology
standardised on it. It is the technical gold standard for the land topography
problem.

The cost is high: Fortran plus MPI, a compile step, and for 3D a separate
meshing subsystem (CUBIT/Trelis). It is also GPL-3.0. It is the fallback if
SWEEP's accuracy on topography proves insufficient, not the starting point.

## 4. Recommendation

**Phase F1 — Deepwave, to validate the contract, not to produce results.**

`pip install deepwave` and a 2D elastic land line with a free surface. The
value is not the science output; it is proving the three contracts from
`plugin_contract_evolution.md` against a genuinely long-running, staged
inversion: the plugin-owned physics payload, staged `RunEvent`s, and restart.
Once those hold, changing engine is an adapter change.

**Phase F2 — SWEEP for production, Devito as the conservative fallback.**

SWEEP is the only option that reaches 3D elastic with anisotropy and
topography without a build system. Because it is unproven at scale, run a real
dataset through it **during F1**, in parallel, so the F2 decision is made on
evidence. If it does not hold up, fall back to Devito and write the FWI layer
in Python, which is the path JUDI already proved can reach industrial scale.

Do not adopt SWEEP and Deepwave as alternatives to each other in the same
phase: use Deepwave to shape the OFAG-side contract while SWEEP is being
evaluated on data.

## 5. Field-data layer OFAG must build

SEG-Y has a natural fit here.
[segysak](https://segysak.readthedocs.io/en/latest/) loads SEG-Y directly into
`xarray.Dataset`, and OFAG already depends on `xarray` and `zarr`. That places
SEG-Y ingestion cleanly inside the existing `services/data_import.py` boundary
with no new stack. Its underlying [segyio](https://github.com/equinor/segyio)
(Equinor, LGPL) is stable, though 2.0 development is currently paused.

The importer built on it is exercised against a public field file rather than
only against SEG-Y that OFAG wrote itself; the dataset and what reading it
changed are in [seismic_field_data.md](seismic_field_data.md).

## 6. Corrections this forces on the contract design

Real land data invalidates parts of §3.8 of
[plugin_contract_evolution.md](plugin_contract_evolution.md):

1. **The source wavelet is an inverted quantity, not only an input.** Get it
   wrong on field data and the inversion is worthless. `RunSpec` must express
   whether the wavelet is jointly inverted, and the recovered wavelet must be a
   first-class artifact. Vibroseis versus dynamite changes this materially.
2. **Missing quantity types**: `QUALITY_FACTOR` (Q, dimensionless) and the
   Thomsen anisotropy parameters ε, δ, γ (dimensionless). Elastic land work
   also needs Vs as a distinct type from Vp, which §3.8 already has.
3. **The misfit function must be in the spec**, not buried in the plugin:
   L2, envelope, optimal transport, adaptive waveform inversion. On field data
   this switch decides success or failure, so it is configuration, not an
   implementation detail.
4. **Preprocessing must be reproducible.** Mute, bandpass and gain parameters
   belong either in `RunSpec` or in a hashed artifact. Phase-1 principle 6
   requires recording input hashes; synthetic work can ignore this, land field
   data cannot. *Done*: `services/seismic_preprocess.py` holds the declared
   sequence — demean, zero-phase bandpass, a mute at each end of an
   offset-following window, `t**n` gain, RMS trace normalisation — all of it off unless asked for, since each
   step changes the data the misfit is measured on. The whole specification is
   written beside the arrays it produced as `fwi_preparation.json`, and the
   observation array is hashed; `FwiGeometrySpec.observations_sha256` carries
   that digest into the run and `validate` refuses data that no longer matches
   it. A path says which file was read, and that is not the same claim.
   The clause understates the requirement, though: reproducing the sequence is
   not enough, it has to be *applied to both sides*. Soda Lake showed why. With
   the observations RMS-normalised and the synthetic left alone, the two differ
   by 5 x 10^6 in amplitude, the relative misfit sits at exactly 1.0000000, and
   thirty iterations move the model by nothing at all. `ElasticFwiSpec` now
   carries the same `SeismicPreprocessingSpec` the observations were prepared
   with and the plugin applies it to the predicted data before the misfit,
   exactly as its stage filter already low-passed both sides.
6. **A land record is multi-component, and says so nowhere.** A 3C station's
   three traces carry no header that distinguishes them; only the trace order
   does, in either of two layouts. Which component a 2D elastic run explains is
   a physical choice and belongs in the request, exactly as the misfit does.
5. **Topography is already a core concept** in OFAG for gravity and TMI active
   cells. Seismic needs it as a *simulation* boundary, not only a masking
   surface. That is a second, different use of the same input and should reuse
   `ImportedTopographyDataset` rather than introduce a parallel one.
