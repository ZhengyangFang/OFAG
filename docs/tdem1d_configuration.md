# SimPEG single-sounding TDEM 1D inversion

`simpeg.aem.tdem1d` connects OFAG's immutable run contract to SimPEG's
`Simulation1DLayered`. It supports a circular transmitter loop and a central
(or offset) receiver measuring one component of magnetic flux density `B` or
its time derivative `dB/dt` at explicit time channels. All values at the OFAG
boundary are SI: locations/layers in m, times in s, current in A, `B` in T,
`dB/dt` in T/s and conductivity in S/m.

The input CSV must contain precisely these columns in
strictly increasing channel order:

```text
time_s,magnetic_flux_density_t
1.0e-5,9.0e-11
...
```

The CSV times must equal `tdem_inversion.system.times` after unit conversion;
this prevents a sounding from being inverted with mismatched gates.

Set `receiver_quantity: magnetic_flux_density_time_derivative` to use the
`time_s,magnetic_flux_density_time_derivative_t_s` CSV column and declare the
dataset/uncertainty in T/s. `waveform: piecewise_linear` accepts
`waveform_times` (which may include negative on-time values) and an equal-length
`waveform_current_fractions` sequence. These fractions are multiplied by the
explicit `source_current`; `step_off` remains the default.

```yaml
plugin_id: simpeg.aem.tdem1d
engine: simpeg
dataset:
  name: aem-sounding
  coordinate_convention: {crs: LOCAL_CARTESIAN_METRIC}
  physical_quantity: magnetic_flux_density
  units: T
tdem_inversion:
  system:
    times: {value: [1.0e-5, 2.0e-5, 5.0e-5], quantity_type: time, unit: s}
    source_location: {value: [0, 0, 20], quantity_type: length, unit: m}
    receiver_location: {value: [0, 0, 20], quantity_type: length, unit: m}
    source_radius: {value: 6, quantity_type: length, unit: m}
    source_current: {value: 1, quantity_type: electric_current, unit: A}
    source_turns: 1
    source_orientation: z
    receiver_orientation: z
    waveform: step_off
  earth:
    layer_thicknesses: {value: [5, 10, 20], quantity_type: length, unit: m}
  model:
    initial_conductivity: {value: 0.03, quantity_type: conductivity, unit: S/m}
    lower_bound: {value: 1.0e-4, quantity_type: conductivity, unit: S/m}
    upper_bound: {value: 1.0, quantity_type: conductivity, unit: S/m}
  regularization: {alpha_s: 1.0, alpha_z: 1.0}
  optimizer: {max_iterations: 10, cg_max_iterations: 20}
  beta: {estimation: by_eig, beta0_ratio: 1.0}
parameters:
  observations_path: /path/to/your/observations.csv
  # Scalar uncertainty is applied to every channel. A same-length list is also valid.
  data_uncertainty: {value: 5.0e-12, quantity_type: magnetic_flux_density, unit: T}
```

SimPEG operates on the dimensionless model `ln(σ / 1 S/m)` internally. OFAG
does not expose it as the primary result: `recovered_conductivity_s_m.npy` is
the SI model; `recovered_log_conductivity.npy` is included only for numerical
provenance. Other artifacts are layer-top depth, predicted/residual B data,
normalized residual, SimPEG log and per-iteration objective metrics.

## Official regression data

The optional `simpeg.tdem1d` reference source is SimPEG's official single
sounding tutorial archive. Fetching is explicit:

```powershell
uv run ofag --json reference-data fetch simpeg.tdem1d
uv run --extra simpeg ofag --json reference-data prepare-tdem1d
uv run --extra simpeg ofag run data/reference-cache/ofag_profiles/simpeg_tdem1d/run.yaml
```

The derived profile carries one 5%-of-observed-B uncertainty per channel, as in
the tutorial. It is an OFAG L2 regression profile, rather than a claim of
bit-identical equivalence to the tutorial's sparse-IRLS settings.
