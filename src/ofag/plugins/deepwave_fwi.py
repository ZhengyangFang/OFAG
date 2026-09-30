"""2D elastic full-waveform inversion of a land line, through Deepwave."""

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ofag.core.constants import QuantityType
from ofag.core.conventions import UNVERIFIED, _Unverified
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    ParameterSensitivity,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    StrictModel,
    ValidationIssue,
    ValidationReport,
)
from ofag.engines.deepwave.elastic import grid_indices, propagate, to_lame
from ofag.plugins.protocol import PluginContext
from ofag.services.seismic_preprocess import (
    MuteSpec,
    SeismicPreprocessingSpec,
    band_window,
    mute_weights,
)


class FwiGridSpec(StrictModel):
    """The model grid, in metres, with depth increasing downwards."""

    #: (depth cells, along-line cells).
    shape: tuple[int, int]
    cell_size: QuantitySpec
    #: Along-line distance and depth of the grid's top-left cell centre.
    origin_m: tuple[float, float] = (0.0, 0.0)

    @model_validator(mode="after")
    def grid_is_usable(self) -> "FwiGridSpec":
        if any(size < 8 for size in self.shape):
            raise ValueError("each grid axis needs at least eight cells to hold a wavefield")
        if self.cell_size.quantity_type is not QuantityType.LENGTH:
            raise ValueError("cell_size must be a length")
        return self


class FwiGeometrySpec(StrictModel):
    """Where the shots and the receivers were, along the line."""

    #: Paths to (n, 2) arrays of along-line distance and depth, in metres.
    sources_path: str
    receivers_path: str
    #: Observed vertical particle velocity, (shots, receivers, samples).
    observations_path: str
    #: Digest of that array, from the preparation step.
    observations_sha256: str | None = None
    time_step: QuantitySpec
    #: Absorbing cells on the sides and bottom; the top is always free, because a land
    #: record is dominated by the free surface.
    pml_cells: int = Field(default=20, ge=4, le=200)

    @model_validator(mode="after")
    def time_step_is_a_time(self) -> "FwiGeometrySpec":
        if self.time_step.quantity_type is not QuantityType.TIME:
            raise ValueError("time_step must be a time")
        return self


class FwiWaveletSpec(StrictModel):
    """The source signature, and whether the inversion solves for it."""

    peak_frequency: QuantitySpec
    #: A recorded or estimated wavelet, which overrides the Ricker.
    source_path: str | None = None
    #: Solve for the wavelet alongside the model.
    inverted: bool = False

    @model_validator(mode="after")
    def frequency_is_a_frequency(self) -> "FwiWaveletSpec":
        if self.peak_frequency.quantity_type is not QuantityType.FREQUENCY:
            raise ValueError("peak_frequency must be a frequency")
        return self


#: What a residual is measured with.
MisfitKind = Literal["l2", "envelope"]


class FwiStageSpec(StrictModel):
    """One band of a multi-scale solve."""

    #: Both observed and predicted data are low-passed to this before the misfit is
    #: taken.
    corner_frequency: QuantitySpec | None = None
    iterations: int = Field(default=8, ge=1, le=5_000)
    #: Which residual this stage is measured by, overriding the run's own.
    misfit: MisfitKind | None = None

    @model_validator(mode="after")
    def corner_is_a_frequency(self) -> "FwiStageSpec":
        if (
            self.corner_frequency is not None
            and self.corner_frequency.quantity_type is not QuantityType.FREQUENCY
        ):
            raise ValueError("corner_frequency must be a frequency")
        return self


#: An explicit elastic solve diverges above this Courant number, and a cell coarser than
#: this many per shear wavelength returns numerical dispersion rather than a wavefield.
MAXIMUM_COURANT = 0.6
MINIMUM_CELLS_PER_WAVELENGTH = 5.0
#: Slightly above sqrt(2).
MINIMUM_VP_OVER_VS = 1.4143


class VelocityBoundsSpec(StrictModel):
    """Where the solve may take a velocity, beyond what the grid allows."""

    minimum: QuantitySpec
    maximum: QuantitySpec

    @model_validator(mode="after")
    def bounds_are_velocities_in_order(self) -> "VelocityBoundsSpec":
        for name, spec in (("minimum", self.minimum), ("maximum", self.maximum)):
            if spec.quantity_type not in (
                QuantityType.P_WAVE_VELOCITY,
                QuantityType.S_WAVE_VELOCITY,
            ):
                raise ValueError(f"the {name} bound must be a velocity")
        if float(np.asarray(self.minimum.value)) >= float(np.asarray(self.maximum.value)):
            raise ValueError("the minimum bound is at or above the maximum")
        return self


class ElasticFwiSpec(StrictModel):
    """Everything the Deepwave plugin needs, owned by the plugin."""

    grid: FwiGridSpec
    geometry: FwiGeometrySpec
    #: What was done to the observed data before it reached this run, so the same can be
    #: done to the predicted data before the misfit.
    observed_preprocessing: SeismicPreprocessingSpec = Field(
        default_factory=SeismicPreprocessingSpec
    )
    wavelet: FwiWaveletSpec
    stages: tuple[FwiStageSpec, ...] = Field(min_length=1)
    misfit: MisfitKind = "l2"
    #: Starting models, as (depth, along-line) arrays matching the grid.
    initial_vp_path: str
    initial_vs_path: str
    density_path: str
    #: Which parameters the solve updates.
    invert_vp: bool = True
    invert_vs: bool = True
    invert_density: bool = False
    #: Narrower limits than the grid's own, when the site is known.
    vp_bounds: VelocityBoundsSpec | None = None
    vs_bounds: VelocityBoundsSpec | None = None
    learning_rate: float = Field(default=20.0, gt=0)

    @model_validator(mode="after")
    def something_is_inverted(self) -> "ElasticFwiSpec":
        if not (self.invert_vp or self.invert_vs or self.invert_density or self.wavelet.inverted):
            raise ValueError("nothing is being inverted for; enable at least one parameter")
        return self


def _highest_frequency(config: "ElasticFwiSpec") -> float:
    """The top of the band the solve will reach."""
    return max(
        (
            float(_scalar(stage.corner_frequency.value))
            for stage in config.stages
            if stage.corner_frequency is not None
        ),
        default=float(_scalar(config.wavelet.peak_frequency.value)) * 2.5,
    )


class DeepwaveElasticFwiPlugin:
    """Invert a land line for Vp and Vs, staged over frequency."""

    plugin_id = "deepwave.fwi.elastic2d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return ElasticFwiSpec

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(
                QuantityType.P_WAVE_VELOCITY,
                QuantityType.S_WAVE_VELOCITY,
                QuantityType.BULK_DENSITY,
                QuantityType.PARTICLE_VELOCITY,
            ),
            supported_meshes=("DeepwaveRegular2D",),
            supports_parallel=False,
            supports_restart=True,
            limitations=(
                "2D elastic only: Deepwave's elastic solver has no 3D mode, so a "
                "three-dimensional land survey needs a different engine.",
                "No attenuation. The weathering layer is strongly attenuative and "
                "this solver has no Q, so shallow amplitudes are not trustworthy.",
                "No anisotropy. VTI is normal in real land data and is not modelled.",
                "The whole model must fit in one device's memory; there is no domain "
                "decomposition.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if spec.engine != "deepwave":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message=f"{self.plugin_id} requires engine='deepwave'",
                    remediation="set engine to 'deepwave'",
                )
            )
        if spec.mesh is not None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="this plugin owns its own regular grid",
                    remediation="declare the grid in physics.grid and leave RunSpec.mesh unset",
                )
            )
        config = spec.physics_as(ElasticFwiSpec)
        if config is None:
            issues.append(
                ValidationIssue(
                    field="physics",
                    message="an elastic FWI configuration is required",
                    remediation="set schema_version to 1.1 and provide physics",
                )
            )
            return ValidationReport(valid=not issues, issues=tuple(issues))

        for field, path in (
            ("physics.initial_vp_path", config.initial_vp_path),
            ("physics.initial_vs_path", config.initial_vs_path),
            ("physics.density_path", config.density_path),
            ("physics.geometry.sources_path", config.geometry.sources_path),
            ("physics.geometry.receivers_path", config.geometry.receivers_path),
            ("physics.geometry.observations_path", config.geometry.observations_path),
        ):
            if not Path(path).is_file():
                issues.append(
                    ValidationIssue(
                        field=field,
                        message=f"{path} does not exist",
                        remediation="import or prepare the input before validating the run",
                    )
                )
        digest = config.geometry.observations_sha256
        observations = Path(config.geometry.observations_path)
        if digest is not None and observations.is_file():
            import hashlib

            import numpy as np

            actual = hashlib.sha256(
                np.ascontiguousarray(np.load(observations, allow_pickle=False)).tobytes()
            ).hexdigest()
            if actual != digest:
                issues.append(
                    ValidationIssue(
                        field="physics.geometry.observations_sha256",
                        message=(
                            "the observation array does not match the digest this run was "
                            "configured against; it has been re-prepared or overwritten"
                        ),
                        remediation=(
                            "prepare the line again and start a run from the result, so the "
                            "section says which data produced it"
                        ),
                    )
                )

        if (
            config.wavelet.source_path is not None
            and not Path(config.wavelet.source_path).is_file()
        ):
            issues.append(
                ValidationIssue(
                    field="physics.wavelet.source_path",
                    message=f"{config.wavelet.source_path} does not exist",
                    remediation="supply a recorded wavelet or drop the path to use a Ricker",
                )
            )
        if issues:
            return ValidationReport(valid=False, issues=tuple(issues))

        issues.extend(self._stability_issues(config))
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def _stability_issues(self, config: ElasticFwiSpec) -> list[ValidationIssue]:
        """Check the grid against the model before an hour is spent diverging."""
        issues: list[ValidationIssue] = []
        try:
            vp = np.load(config.initial_vp_path, allow_pickle=False)
            vs = np.load(config.initial_vs_path, allow_pickle=False)
        except (OSError, ValueError) as error:
            return [
                ValidationIssue(
                    field="physics.initial_vp_path",
                    message=f"starting models are not readable: {error}",
                    remediation="write them with numpy.save as (depth, along-line) arrays",
                )
            ]
        spacing = float(_scalar(config.grid.cell_size.value))
        step = float(_scalar(config.geometry.time_step.value))
        if tuple(np.shape(vp)) != config.grid.shape:
            issues.append(
                ValidationIssue(
                    field="physics.initial_vp_path",
                    message=f"vp is {np.shape(vp)} but the grid is {config.grid.shape}",
                    remediation="write the starting model on the declared grid",
                )
            )
            return issues

        courant = float(np.max(vp)) * step / spacing
        if courant > MAXIMUM_COURANT:
            issues.append(
                ValidationIssue(
                    field="physics.geometry.time_step",
                    message=(
                        f"a time step of {step:g} s with {spacing:g} m cells and a maximum "
                        f"velocity of {float(np.max(vp)):g} m/s gives a Courant number of "
                        f"{courant:.2f}; an explicit elastic solve diverges above about 0.6"
                    ),
                    remediation=(
                        f"use a time step below "
                        f"{MAXIMUM_COURANT * spacing / float(np.max(vp)):.2e} s"
                    ),
                )
            )
        highest = _highest_frequency(config)
        slowest = float(np.min(vs))
        cells_per_wavelength = slowest / (highest * spacing) if highest > 0 else float("inf")
        if cells_per_wavelength < MINIMUM_CELLS_PER_WAVELENGTH:
            issues.append(
                ValidationIssue(
                    field="physics.grid.cell_size",
                    message=(
                        f"{spacing:g} m cells give {cells_per_wavelength:.1f} cells per shear "
                        f"wavelength at {highest:g} Hz and {slowest:g} m/s; below about five "
                        "the wavefield is numerical dispersion rather than physics"
                    ),
                    remediation=(
                        f"use cells below "
                        f"{slowest / (MINIMUM_CELLS_PER_WAVELENGTH * highest):.2f} m, "
                        "or lower the "
                        "highest stage frequency"
                    ),
                )
            )
        return issues

    def conventions(self) -> _Unverified:
        """Report missing convention verification."""
        return UNVERIFIED

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = spec.physics_as(ElasticFwiSpec)
        if config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=512, estimated_seconds=60)
        cells = config.grid.shape[0] * config.grid.shape[1]
        iterations = sum(stage.iterations for stage in config.stages)
        sources = int(np.load(config.geometry.sources_path, allow_pickle=False).shape[0])
        # Every iteration is a forward and an adjoint pass per shot, and the wavefield
        # state for the adjoint is what dominates the memory.
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(512, int(cells * sources * 8 * 12 / 1e6)),
            estimated_seconds=max(60, int(cells * sources * iterations / 2e5)),
        )

    def _setup(self, config: ElasticFwiSpec) -> dict[str, Any]:
        """Everything a pass through this configuration needs, loaded once."""
        import torch

        spacing = float(_scalar(config.grid.cell_size.value))
        step = float(_scalar(config.geometry.time_step.value))
        peak = float(_scalar(config.wavelet.peak_frequency.value))
        observed = torch.tensor(
            np.load(config.geometry.observations_path, allow_pickle=False), dtype=torch.float64
        )
        sources_m = np.load(config.geometry.sources_path, allow_pickle=False)
        receivers_m = np.load(config.geometry.receivers_path, allow_pickle=False)
        shots, samples = int(observed.shape[0]), int(observed.shape[-1])
        return {
            "spacing": spacing,
            "step": step,
            "peak": peak,
            "observed": observed,
            "sources_m": sources_m,
            "receivers_m": receivers_m,
            "shots": shots,
            "samples": samples,
            "source_indices": torch.tensor(
                grid_indices(
                    np.asarray(sources_m, dtype=float),
                    config.grid.origin_m,
                    spacing,
                    config.grid.shape,
                )
            ).reshape(shots, 1, 2),
            "receiver_indices": torch.tensor(
                grid_indices(
                    np.asarray(receivers_m, dtype=float),
                    config.grid.origin_m,
                    spacing,
                    config.grid.shape,
                )
            ).repeat(shots, 1, 1),
            "vp": torch.tensor(
                np.load(config.initial_vp_path, allow_pickle=False), dtype=torch.float64
            ),
            "vs": torch.tensor(
                np.load(config.initial_vs_path, allow_pickle=False), dtype=torch.float64
            ),
            "density": torch.tensor(
                np.load(config.density_path, allow_pickle=False), dtype=torch.float64
            ),
            "wavelet": self._wavelet(config, samples, step, peak),
        }

    def parameter_sensitivity(self, context: PluginContext, spec: RunSpec) -> ParameterSensitivity:
        """What the data sees, before an hour is spent inverting for what it does not."""
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = spec.physics_as(ElasticFwiSpec)
        assert config is not None

        setup = self._setup(config)
        parameters = {
            "vp": setup["vp"].clone().requires_grad_(True),
            "vs": setup["vs"].clone().requires_grad_(True),
            "density": setup["density"].clone().requires_grad_(True),
        }
        mu = parameters["density"] * parameters["vs"] ** 2
        predicted = propagate(
            parameters["density"] * parameters["vp"] ** 2 - 2.0 * mu,
            mu,
            1.0 / parameters["density"],
            spacing_m=setup["spacing"],
            time_step_s=setup["step"],
            wavelet=setup["wavelet"].reshape(1, 1, setup["samples"]).repeat(setup["shots"], 1, 1),
            source_indices=setup["source_indices"],
            receiver_indices=setup["receiver_indices"],
            peak_frequency_hz=setup["peak"],
            pml_cells=config.geometry.pml_cells,
        )
        first = config.stages[0]
        corner = (
            None if first.corner_frequency is None else float(_scalar(first.corner_frequency.value))
        )
        kind = first.misfit or config.misfit
        offsets_m = np.abs(
            np.asarray(setup["sources_m"], dtype=float)[:, None, 0]
            - np.asarray(setup["receivers_m"], dtype=float)[None, :, 0]
        )
        constants = self._preprocessing_constants(
            config.observed_preprocessing, tuple(setup["observed"].shape), offsets_m, setup["step"]
        )
        loss = self._misfit(
            self._filtered(
                self._preprocessed(predicted, config.observed_preprocessing, constants),
                corner,
                setup["step"],
            ),
            self._filtered(setup["observed"], corner, setup["step"]),
            kind,
        )
        loss.backward()

        sensitivity = {
            name: float(tensor.grad.abs().mean() * tensor.detach().abs().mean())
            if tensor.grad is not None
            else 0.0
            for name, tensor in parameters.items()
        }
        inverted = tuple(
            name
            for name, wanted in (
                ("vp", config.invert_vp),
                ("vs", config.invert_vs),
                ("density", config.invert_density),
            )
            if wanted
        )
        return ParameterSensitivity(sensitivity=sensitivity, inverted=inverted)

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = spec.physics_as(ElasticFwiSpec)
        assert config is not None

        import torch

        setup = self._setup(config)
        spacing, step, peak = setup["spacing"], setup["step"], setup["peak"]
        observed = setup["observed"]
        sources_m, receivers_m = setup["sources_m"], setup["receivers_m"]
        shots, samples = setup["shots"], setup["samples"]
        source_indices, receiver_indices = setup["source_indices"], setup["receiver_indices"]
        vp, vs, density, wavelet = setup["vp"], setup["vs"], setup["density"], setup["wavelet"]

        # Restart: the parameters, the wavelet and where the staged solve had got to.
        checkpoint = context.resume_from(spec)
        first_stage, first_iteration = 0, 0
        if checkpoint is not None:
            saved = checkpoint.state.get("path")
            if isinstance(saved, str) and Path(saved).is_file():
                with np.load(saved, allow_pickle=False) as stored:
                    if tuple(stored["vp"].shape) == tuple(vp.shape):
                        vp = torch.tensor(stored["vp"], dtype=torch.float64)
                        vs = torch.tensor(stored["vs"], dtype=torch.float64)
                        density = torch.tensor(stored["density"], dtype=torch.float64)
                        wavelet = torch.tensor(stored["wavelet"], dtype=torch.float64)
                        first_stage = int(stored["stage"])
                        first_iteration = int(stored["iteration"])
                context.emit(
                    RunEvent(
                        run_id=spec.run_id,
                        event_type="state",
                        stage=f"stage-{first_stage + 1}",
                        iteration=first_iteration,
                        message=(
                            f"resumed in stage {first_stage + 1} at iteration {first_iteration}"
                        ),
                    )
                )

        for parameter, wanted in (
            (vp, config.invert_vp),
            (vs, config.invert_vs),
            (density, config.invert_density),
        ):
            parameter.requires_grad_(wanted)
        wavelet.requires_grad_(config.wavelet.inverted)
        updating = [tensor for tensor in (vp, vs, density, wavelet) if tensor.requires_grad]
        optimiser = torch.optim.Adam(updating, lr=config.learning_rate)

        # Validate the starting model parameters.
        to_lame(vp.detach().numpy(), vs.detach().numpy(), density.detach().numpy())

        # The offsets a mute follows, on the line the run is modelled along.
        offsets_m = np.abs(
            np.asarray(sources_m, dtype=float)[:, None, 0]
            - np.asarray(receivers_m, dtype=float)[None, :, 0]
        )
        preprocessing = self._preprocessing_constants(
            config.observed_preprocessing, tuple(observed.shape), offsets_m, step
        )

        bounds = self._bounds(config)

        history: list[float] = []
        run_dir = context.run_dir(spec.run_id)
        total_stages = len(config.stages)
        for stage_index in range(first_stage, total_stages):
            stage = config.stages[stage_index]
            stage_name = f"stage-{stage_index + 1}"
            corner = (
                None
                if stage.corner_frequency is None
                else float(_scalar(stage.corner_frequency.value))
            )
            kind = stage.misfit or config.misfit
            target = self._filtered(observed, corner, step)
            # Normalised by the band's own data energy, so the misfit is a relative
            # number starting near one whatever the recording's absolute amplitude.
            scale = float(self._misfit(torch.zeros_like(target), target, kind).detach())
            if scale <= 0.0:
                raise ValueError(
                    f"the observed data has no energy in the {stage_name} band; "
                    "its corner frequency is below anything that was recorded"
                )
            start = first_iteration if stage_index == first_stage else 0
            for iteration in range(start, stage.iterations):
                optimiser.zero_grad()
                # The same conversion as `to_lame`, in tensors so autograd reaches the
                # velocities the solve is updating.
                mu = density * vs**2
                lamb = density * vp**2 - 2.0 * mu
                predicted = propagate(
                    lamb,
                    mu,
                    1.0 / density,
                    spacing_m=spacing,
                    time_step_s=step,
                    # One signature shared by every shot: repeated, not reshaped, so an
                    # inverted wavelet accumulates the gradient of all the shots that
                    # used it.
                    wavelet=wavelet.reshape(1, 1, samples).repeat(shots, 1, 1),
                    source_indices=source_indices,
                    receiver_indices=receiver_indices,
                    peak_frequency_hz=peak,
                    pml_cells=config.geometry.pml_cells,
                )
                # Prepared the same way the observation was, then band-limited to the
                # stage exactly as the observation is above.
                loss = (
                    self._misfit(
                        self._filtered(
                            self._preprocessed(
                                predicted, config.observed_preprocessing, preprocessing
                            ),
                            corner,
                            step,
                        ),
                        target,
                        kind,
                    )
                    / scale
                )
                loss.backward()
                optimiser.step()
                with torch.no_grad():
                    vs.clamp_(bounds["vs_low"], bounds["vs_high"])
                    vp.clamp_(bounds["vp_low"], bounds["vp_high"])
                    # Elementwise, after both: a cell whose vp fell under sqrt(2) times
                    # its own vs is a fluid, and the free-surface vacuum method is
                    # unstable in one.
                    torch.maximum(vp, MINIMUM_VP_OVER_VS * vs, out=vp)
                value = float(loss.detach())
                history.append(value)
                context.emit(
                    RunEvent(
                        run_id=spec.run_id,
                        event_type="iteration",
                        iteration=iteration + 1,
                        stage=stage_name,
                        stage_index=stage_index + 1,
                        stage_total=total_stages,
                        phi_data=value,
                        misfits={kind: value},
                        message="iteration completed",
                    )
                )
                self._save_checkpoint(
                    context, spec, run_dir, vp, vs, density, wavelet, stage_index, iteration + 1
                )
            first_iteration = 0

        return self._publish(
            context,
            spec,
            run_dir,
            config,
            vp,
            vs,
            density,
            wavelet,
            history,
            (int(observed.shape[0]), int(observed.shape[1]), int(observed.shape[-1])),
        )

    @staticmethod
    def _wavelet(config: ElasticFwiSpec, samples: int, step: float, peak: float) -> Any:
        import torch
        from deepwave.wavelets import ricker  # type: ignore[import-untyped]

        if config.wavelet.source_path is not None:
            values = np.load(config.wavelet.source_path, allow_pickle=False)
            if values.size != samples:
                raise ValueError(
                    f"the wavelet has {values.size} samples but the records have {samples}"
                )
            return torch.tensor(np.asarray(values, dtype=float), dtype=torch.float64)
        # 1.3 / f delays the Ricker enough that it starts at zero, which an explicit
        # solver needs: a wavelet that begins mid-swing injects a step.
        return ricker(peak, samples, step, 1.3 / peak).to(torch.float64)

    @staticmethod
    def _bounds(config: "ElasticFwiSpec") -> dict[str, float]:
        """What the solve may not take the model outside of."""
        spacing = float(_scalar(config.grid.cell_size.value))
        step = float(_scalar(config.geometry.time_step.value))
        floor = MINIMUM_CELLS_PER_WAVELENGTH * spacing * _highest_frequency(config)
        ceiling = MAXIMUM_COURANT * spacing / step
        limits = {
            "vs_low": floor,
            "vs_high": ceiling / MINIMUM_VP_OVER_VS,
            "vp_low": floor * MINIMUM_VP_OVER_VS,
            "vp_high": ceiling,
        }
        for name, stated in (("vp", config.vp_bounds), ("vs", config.vs_bounds)):
            if stated is None:
                continue
            limits[f"{name}_low"] = max(limits[f"{name}_low"], float(_scalar(stated.minimum.value)))
            limits[f"{name}_high"] = min(
                limits[f"{name}_high"], float(_scalar(stated.maximum.value))
            )
        return limits

    @staticmethod
    def _preprocessing_constants(
        spec: SeismicPreprocessingSpec, shape: tuple[int, ...], offsets_m: Any, step: float
    ) -> dict[str, Any]:
        """The parts of the sequence that do not depend on the data."""
        import numpy as np
        import torch

        samples = int(shape[-1])
        constants: dict[str, Any] = {}
        if spec.bandpass is not None:
            constants["band"] = torch.tensor(
                band_window(samples, step, spec.bandpass), dtype=torch.float64
            )
        sides: tuple[tuple[str, MuteSpec | None, Literal["after", "before"]], ...] = (
            ("mute", spec.top_mute, "after"),
            ("bottom_mute", spec.bottom_mute, "before"),
        )
        for name, mute, keep in sides:
            if mute is not None:
                constants[name] = torch.tensor(
                    mute_weights(offsets_m, samples, step, mute, keep=keep),
                    dtype=torch.float64,
                )
        if spec.time_gain_power:
            constants["gain"] = torch.tensor(
                (np.arange(samples) * step) ** spec.time_gain_power, dtype=torch.float64
            )
        return constants

    @staticmethod
    def _preprocessed(data: Any, spec: SeismicPreprocessingSpec, constants: dict[str, Any]) -> Any:
        """The operations the observed data was prepared with, on this side too."""
        import torch

        if spec.remove_mean:
            data = data - data.mean(dim=-1, keepdim=True)
        if spec.bandpass is not None:
            samples = int(data.shape[-1])
            data = torch.fft.irfft(
                torch.fft.rfft(data, dim=-1) * constants["band"], n=samples, dim=-1
            )
        if spec.top_mute is not None:
            data = data * constants["mute"]
        if spec.bottom_mute is not None:
            data = data * constants["bottom_mute"]
        if spec.time_gain_power:
            data = data * constants["gain"]
        if spec.trace_normalisation == "rms":
            rms = torch.sqrt(torch.mean(data**2, dim=-1, keepdim=True))
            # A dead trace stays dead rather than dividing by zero, matching the numpy
            # side.
            data = data / torch.clamp(rms, min=1e-30)
        return data

    @staticmethod
    def _filtered(data: Any, corner_hz: float | None, step: float) -> Any:
        """Low-pass both observed and predicted to a stage's band."""
        import torch

        if corner_hz is None:
            return data
        spectrum = torch.fft.rfft(data, dim=-1)
        frequencies = torch.fft.rfftfreq(int(data.shape[-1]), step)
        # A cosine taper over the last octave rather than a brick wall, which would ring
        # in time and be fitted as structure.
        transition = torch.clamp((corner_hz - frequencies) / (0.5 * corner_hz), 0.0, 1.0)
        window = 0.5 - 0.5 * torch.cos(np.pi * transition)
        return torch.fft.irfft(spectrum * window, n=int(data.shape[-1]), dim=-1)

    @staticmethod
    def _misfit(predicted: Any, observed: Any, kind: MisfitKind) -> Any:
        import torch

        if kind == "l2":
            return ((predicted - observed) ** 2).sum()

        # Envelope: compare instantaneous amplitude only, which is blind to phase and so
        # does not cycle-skip when the starting model is more than half a period out.
        def envelope(signal: Any) -> Any:
            spectrum = torch.fft.fft(signal, dim=-1)
            samples = int(signal.shape[-1])
            mask = torch.zeros(samples, dtype=spectrum.dtype)
            half = samples // 2
            mask[0] = 1.0
            mask[1:half] = 2.0
            if samples % 2 == 0:
                mask[half] = 1.0
            analytic = torch.fft.ifft(spectrum * mask, dim=-1)
            return torch.abs(analytic)

        return ((envelope(predicted) - envelope(observed)) ** 2).sum()

    def _save_checkpoint(
        self,
        context: PluginContext,
        spec: RunSpec,
        run_dir: Path,
        vp: Any,
        vs: Any,
        density: Any,
        wavelet: Any,
        stage_index: int,
        iteration: int,
    ) -> None:
        path = run_dir / "checkpoint_state.npz"
        np.savez(
            path,
            vp=vp.detach().numpy(),
            vs=vs.detach().numpy(),
            density=density.detach().numpy(),
            wavelet=wavelet.detach().numpy(),
            stage=stage_index,
            iteration=iteration,
        )
        context.checkpoint(
            spec,
            {"path": str(path), "stage": stage_index, "iteration": iteration},
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            iteration=iteration,
        )

    def _publish(
        self,
        context: PluginContext,
        spec: RunSpec,
        run_dir: Path,
        config: ElasticFwiSpec,
        vp: Any,
        vs: Any,
        density: Any,
        wavelet: Any,
        history: list[float],
        fitted: tuple[int, int, int],
    ) -> RunResult:
        artifacts = [
            self._save(
                run_dir, spec.run_id, "recovered_model", vp, QuantityType.P_WAVE_VELOCITY, "m/s"
            ),
            self._save(
                run_dir, spec.run_id, "recovered_vs", vs, QuantityType.S_WAVE_VELOCITY, "m/s"
            ),
            self._save(
                run_dir,
                spec.run_id,
                "recovered_density",
                density,
                QuantityType.BULK_DENSITY,
                "kg/m^3",
            ),
            # Published whether or not it was inverted: a result read a year later must
            # say what source it assumed, not only what it solved.
            self._save(
                run_dir,
                spec.run_id,
                "source_wavelet",
                wavelet,
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
        ]
        del context
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "deepwave",
                "solver": "elastic2d_fwi",
                "misfit": ", ".join(stage.misfit or config.misfit for stage in config.stages),
                "stages": len(config.stages),
                "iterations": len(history),
                # Relative to the observed data's own energy, so a value near one means
                # "as wrong as predicting silence" and a comparison between two surveys
                # means something.
                "misfit_initial": history[0] if history else 0.0,
                "misfit_final": history[-1] if history else 0.0,
                "misfit_is_relative": True,
                "wavelet_inverted": config.wavelet.inverted,
                "inverted_vp": config.invert_vp,
                "inverted_vs": config.invert_vs,
                "inverted_density": config.invert_density,
                # What was fitted, not only what it was fitted with.
                "shots": fitted[0],
                "channels": fitted[1],
                "samples": fitted[2],
                "observations_sha256": config.geometry.observations_sha256 or "not pinned",
                "grid_cells": config.grid.shape[0] * config.grid.shape[1],
                "model_unit": "m/s",
                "data_unit": "m/s",
            },
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _save(
        run_dir: Path, run_id: UUID, name: str, tensor: Any, quantity: QuantityType, unit: str
    ) -> ArtifactManifest:
        path = run_dir / f"{name}.npy"
        np.save(path, np.asarray(tensor.detach().numpy(), dtype=float))
        return ArtifactManifest(
            artifact_type=name,
            physical_quantity=quantity,
            units=unit,
            source_run_id=run_id,
            relative_path=f"{run_id}/{name}.npy",
        )


def _scalar(value: float | list[float] | np.ndarray) -> float:
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError("expected a single value")
        return float(value[0])
    return float(np.asarray(value).reshape(-1)[0])
