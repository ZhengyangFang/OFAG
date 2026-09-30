"""Explicit acquisition of official SimPEG tutorial data."""

import json
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import yaml


@dataclass(frozen=True)
class ReferenceDataset:
    dataset_id: str
    source_url: str
    archive_name: str
    extracted_directory: str
    required_files: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceDatasetReceipt:
    dataset_id: str
    source_url: str
    archive_path: str
    extracted_path: str
    downloaded: bool


@dataclass(frozen=True)
class PreparedGravityReference:
    dataset_id: str
    observations_path: str
    topography_path: str
    run_spec_path: str
    observation_count: int


@dataclass(frozen=True)
class PreparedGravMagJointReference:
    """A full gravity/TMI profile derived from SimPEG's cross-gradient tutorial."""

    dataset_id: str
    gravity_observations_path: str
    magnetic_observations_path: str
    topography_path: str
    run_spec_path: str
    observation_count: int


@dataclass(frozen=True)
class PreparedTDEMReference:
    dataset_id: str
    observations_path: str
    run_spec_path: str
    observation_count: int


@dataclass(frozen=True)
class PreparedTDEM3DTutorialReference:
    """Locally materialized profile derived from an official SimPEG tutorial."""

    source_url: str
    topography_path: str
    source_locations_path: str
    receiver_locations_path: str
    run_spec_path: str
    sounding_count: int


SIMPEG_TDEM3D_TUTORIAL_URL = (
    "https://docs.simpeg.xyz/dev/content/user-guide/tutorials/08-tdem/plot_fwd_3_tem_3d.html"
)


SIMPEG_CROSS_GRADIENT = ReferenceDataset(
    dataset_id="simpeg.cross-gradient",
    source_url="https://storage.googleapis.com/simpeg/doc-assets/cross_gradient_data.tar.gz",
    archive_name="cross_gradient_data.tar.gz",
    extracted_directory="cross_gradient_data",
    required_files=("gravity_data.obs", "magnetic_data.obs", "topo.txt"),
)

SIMPEG_TDEM1D = ReferenceDataset(
    dataset_id="simpeg.tdem1d",
    source_url="https://storage.googleapis.com/simpeg/doc-assets/em1dtm.tar.gz",
    archive_name="em1dtm.tar.gz",
    extracted_directory="em1dtm",
    required_files=("em1dtm_data.txt",),
)


def available_reference_datasets() -> tuple[ReferenceDataset, ...]:
    return (SIMPEG_CROSS_GRADIENT, SIMPEG_TDEM1D)


def fetch_reference_dataset(dataset_id: str, cache_root: Path) -> ReferenceDatasetReceipt:
    """Download a known source only when its extracted local data is unavailable."""
    dataset = _get_dataset(dataset_id)
    cache_root.mkdir(parents=True, exist_ok=True)
    archive_path = cache_root / dataset.archive_name
    extracted_path = cache_root / dataset.extracted_directory
    downloaded = False
    if not archive_path.is_file() and not _is_extracted_dataset_valid(extracted_path, dataset):
        with urlopen(dataset.source_url, timeout=60) as response, archive_path.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        downloaded = True
    if not _is_extracted_dataset_valid(extracted_path, dataset):
        _safe_extract_tar(archive_path, cache_root)
    receipt = ReferenceDatasetReceipt(
        dataset_id=dataset.dataset_id,
        source_url=dataset.source_url,
        archive_path=str(archive_path),
        extracted_path=str(extracted_path),
        downloaded=downloaded,
    )
    (cache_root / f"{dataset.dataset_id}.json").write_text(
        json.dumps({"dataset": asdict(dataset), "receipt": asdict(receipt)}, indent=2),
        encoding="utf-8",
    )
    return receipt


def verify_reference_dataset(dataset_id: str, cache_root: Path) -> ReferenceDatasetReceipt:
    """Check a cached official reference without using the network."""
    dataset = _get_dataset(dataset_id)
    archive_path = cache_root / dataset.archive_name
    extracted_path = cache_root / dataset.extracted_directory
    if not _is_extracted_dataset_valid(extracted_path, dataset):
        raise ValueError(f"missing or incomplete extraction for {dataset.dataset_id}")
    return ReferenceDatasetReceipt(
        dataset_id=dataset.dataset_id,
        source_url=dataset.source_url,
        archive_path=str(archive_path),
        extracted_path=str(extracted_path),
        downloaded=False,
    )


def prepare_cross_gradient_gravity_run(cache_root: Path) -> PreparedGravityReference:
    """Derive a gravity-only profile from the official cross-gradient fixture."""
    receipt = verify_reference_dataset(SIMPEG_CROSS_GRADIENT.dataset_id, cache_root)
    source_path = Path(receipt.extracted_path) / "gravity_data.obs"
    source_values = np.loadtxt(source_path, dtype=float)
    if (
        source_values.ndim != 2
        or source_values.shape[1] != 4
        or not np.isfinite(source_values).all()
    ):
        raise ValueError("official gravity_data.obs must contain finite x, y, z, gravity values")
    observations = np.c_[source_values[:, :3], source_values[:, 3]]
    profile_directory = Path("data/samples/Gravity/simpeg_cross_gradient")
    profile_directory.mkdir(parents=True, exist_ok=True)
    observations_path = profile_directory / "observations_mgal.csv"
    np.savetxt(
        observations_path,
        observations,
        delimiter=",",
        header="x_m,y_m,z_m,gravity_mgal",
        comments="",
        fmt="%.12e",
    )
    topography_source = np.loadtxt(Path(receipt.extracted_path) / "topo.txt", dtype=float)
    if (
        topography_source.ndim != 2
        or topography_source.shape[1] != 3
        or not np.isfinite(topography_source).all()
    ):
        raise ValueError("official topo.txt must contain finite x, y, z values")
    topography_path = profile_directory / "topography_si.csv"
    np.savetxt(
        topography_path,
        topography_source,
        delimiter=",",
        header="x_m,y_m,z_m",
        comments="",
        fmt="%.12e",
    )
    uncertainty = float(np.max(np.abs(observations[:, 3])) * 0.01)
    hx = _tutorial_padding_widths(core_cells=40)
    hy = _tutorial_padding_widths(core_cells=40)
    hz = _tutorial_padding_widths(core_cells=15, right_padding_cells=0)
    run_spec_path = profile_directory / "run.yaml"
    run_spec = {
        "plugin_id": "simpeg.pf.gravity3d",
        "plugin_version": "0.1.0",
        "engine": "simpeg",
        "seed": 0,
        "dataset": {
            "name": "simpeg-cross-gradient-gravity-only",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "physical_quantity": "gravity_acceleration",
            "units": "mGal",
        },
        "mesh": {
            "cell_size": {"value": [5.0, 5.0, 5.0], "quantity_type": "length", "unit": "m"},
            "shape": [len(hx), len(hy), len(hz)],
            "origin": [-sum(hx) / 2, -sum(hy) / 2, -sum(hz)],
            "cell_widths": [
                {"value": hx, "quantity_type": "length", "unit": "m"},
                {"value": hy, "quantity_type": "length", "unit": "m"},
                {"value": hz, "quantity_type": "length", "unit": "m"},
            ],
        },
        "gravity_inversion": {
            "simulation": {
                "engine": "geoana",
                "n_processes": 1,
                "sensitivity_dtype": "float32",
            },
            "model": {
                "initial_density_contrast": {
                    "value": 1e-6,
                    "quantity_type": "density_contrast",
                    "unit": "g/cm^3",
                },
                "lower_bound": {
                    "value": -2.0,
                    "quantity_type": "density_contrast",
                    "unit": "g/cm^3",
                },
                "upper_bound": {
                    "value": 2.0,
                    "quantity_type": "density_contrast",
                    "unit": "g/cm^3",
                },
            },
            "regularization": {
                "kind": "l2",
                "alpha_s": 1.0,
                "alpha_x": 1.0,
                "alpha_y": 1.0,
                "alpha_z": 1.0,
            },
            "optimizer": {
                "kind": "projected_gncg",
                "max_iterations": 10,
                "max_line_search_iterations": 20,
                "cg_max_iterations": 100,
                "cg_relative_tolerance": 0.001,
                "cg_absolute_tolerance": 0.001,
            },
            "beta": {
                "estimation": "by_eig",
                "beta0_ratio": 1.0,
                "cooling_factor": 5.0,
                "cooling_rate": 1,
            },
            "directives": {
                "sensitivity_weighting": {"enabled": True},
                "update_preconditioner": True,
                "save_iteration_metrics": True,
            },
        },
        "parameters": {
            "observations_path": observations_path.as_posix(),
            "topography_path": topography_path.as_posix(),
            "initial_density_contrast": {
                "value": 1e-6,
                "quantity_type": "density_contrast",
                "unit": "g/cm^3",
            },
            "data_uncertainty": {
                "value": uncertainty,
                "quantity_type": "gravity_acceleration",
                "unit": "mGal",
            },
            "max_iterations": 10,
            "reference_dataset": SIMPEG_CROSS_GRADIENT.dataset_id,
        },
    }
    run_spec_path.write_text(yaml.safe_dump(run_spec, sort_keys=False), encoding="utf-8")
    return PreparedGravityReference(
        dataset_id=SIMPEG_CROSS_GRADIENT.dataset_id,
        observations_path=observations_path.as_posix(),
        topography_path=topography_path.as_posix(),
        run_spec_path=run_spec_path.as_posix(),
        observation_count=int(observations.shape[0]),
    )


def prepare_cross_gradient_joint_run(cache_root: Path) -> PreparedGravMagJointReference:
    """Materialize SimPEG's published gravity/TMI cross-gradient configuration."""
    receipt = verify_reference_dataset(SIMPEG_CROSS_GRADIENT.dataset_id, cache_root)
    source_directory = Path(receipt.extracted_path)
    gravity_source = np.loadtxt(source_directory / "gravity_data.obs", dtype=float)
    magnetic_source = np.loadtxt(source_directory / "magnetic_data.obs", dtype=float)
    topography_source = np.loadtxt(source_directory / "topo.txt", dtype=float)
    for values, label in (
        (gravity_source, "gravity_data.obs"),
        (magnetic_source, "magnetic_data.obs"),
    ):
        if values.ndim != 2 or values.shape[1] != 4 or not np.isfinite(values).all():
            raise ValueError(f"official {label} must contain finite x, y, z, data values")
    if (
        topography_source.ndim != 2
        or topography_source.shape[1] != 3
        or not np.isfinite(topography_source).all()
    ):
        raise ValueError("official topo.txt must contain finite x, y, z values")
    if gravity_source.shape[0] != magnetic_source.shape[0]:
        raise ValueError(
            "official gravity and magnetic observations must have matching station counts"
        )

    gravity_directory = Path("data/samples/Gravity/simpeg_cross_gradient")
    magnetic_directory = Path("data/samples/Magnetic/simpeg_cross_gradient")
    profile_directory = Path("data/samples/Joint/simpeg_cross_gradient")
    gravity_directory.mkdir(parents=True, exist_ok=True)
    magnetic_directory.mkdir(parents=True, exist_ok=True)
    profile_directory.mkdir(parents=True, exist_ok=True)
    gravity_path = gravity_directory / "observations_mgal.csv"
    magnetic_path = magnetic_directory / "observations_tmi_nt.csv"
    topography_path = gravity_directory / "topography_si.csv"
    np.savetxt(
        gravity_path,
        gravity_source,
        delimiter=",",
        header="x_m,y_m,z_m,gravity_mgal",
        comments="",
        fmt="%.12e",
    )
    np.savetxt(
        magnetic_path,
        magnetic_source,
        delimiter=",",
        header="x_m,y_m,z_m,tmi_nt",
        comments="",
        fmt="%.12e",
    )
    np.savetxt(
        topography_path,
        topography_source,
        delimiter=",",
        header="x_m,y_m,z_m",
        comments="",
        fmt="%.12e",
    )
    hx = _tutorial_padding_widths(core_cells=40)
    hy = _tutorial_padding_widths(core_cells=40)
    hz = _tutorial_padding_widths(core_cells=15, right_padding_cells=0)
    gravity_uncertainty = float(np.max(np.abs(gravity_source[:, 3])) * 0.01)
    magnetic_uncertainty_nt = float(np.max(np.abs(magnetic_source[:, 3])) * 0.01)
    dataset = {
        "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
        "physical_quantity": "gravity_acceleration",
        "units": "mGal",
    }
    run_spec = {
        "plugin_id": "simpeg.joint.gravmag.cross_gradient",
        "plugin_version": "0.1.0",
        "engine": "simpeg",
        "seed": 0,
        "dataset": {"name": "simpeg-cross-gradient-joint", **dataset},
        "datasets": [
            {
                "channel_id": "gravity",
                "dataset": {"name": "simpeg-cross-gradient-gravity", **dataset},
                "observations_path": gravity_path.as_posix(),
                "data_uncertainty": {
                    "value": gravity_uncertainty,
                    "quantity_type": "gravity_acceleration",
                    "unit": "mGal",
                },
            },
            {
                "channel_id": "tmi",
                "dataset": {
                    "name": "simpeg-cross-gradient-tmi",
                    "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
                    "physical_quantity": "magnetic_anomaly",
                    "units": "nT",
                },
                "observations_path": magnetic_path.as_posix(),
                "data_uncertainty": {
                    "value": magnetic_uncertainty_nt,
                    "quantity_type": "magnetic_anomaly",
                    "unit": "nT",
                },
            },
        ],
        "mesh": {
            "cell_size": {"value": [5.0, 5.0, 5.0], "quantity_type": "length", "unit": "m"},
            "shape": [len(hx), len(hy), len(hz)],
            "origin": [-sum(hx) / 2, -sum(hy) / 2, -sum(hz)],
            "cell_widths": [
                {"value": hx, "quantity_type": "length", "unit": "m"},
                {"value": hy, "quantity_type": "length", "unit": "m"},
                {"value": hz, "quantity_type": "length", "unit": "m"},
            ],
        },
        "gravmag_joint_inversion": {
            "gravity_channel": "gravity",
            "magnetics_channel": "tmi",
            "gravity": {
                "simulation": {"engine": "choclo", "sensitivity_dtype": "float32"},
                "model": _tutorial_density_model(),
                "regularization": _tutorial_l2_regularization(),
            },
            "magnetics": {
                "inducing_field": {
                    "amplitude": {
                        "value": 50000.0,
                        "quantity_type": "magnetic_flux_density",
                        "unit": "nT",
                    },
                    "inclination": {"value": 90.0, "quantity_type": "angle", "unit": "degree"},
                    "declination": {"value": 0.0, "quantity_type": "angle", "unit": "degree"},
                },
                "simulation": {"engine": "geoana", "sensitivity_dtype": "float32"},
                "model": {
                    "initial_susceptibility": {
                        "value": 1e-6,
                        "quantity_type": "susceptibility",
                        "unit": "dimensionless",
                    },
                    "lower_bound": {
                        "value": -2.0,
                        "quantity_type": "susceptibility",
                        "unit": "dimensionless",
                    },
                    "upper_bound": {
                        "value": 2.0,
                        "quantity_type": "susceptibility",
                        "unit": "dimensionless",
                    },
                },
                "regularization": _tutorial_l2_regularization(),
            },
            "coupling": {
                "weight": 2e12,
                "normalize_models": False,
                "approximate_hessian": True,
            },
            "optimizer": {
                "kind": "projected_gncg",
                "max_iterations": 10,
                "max_line_search_iterations": 20,
                "cg_max_iterations": 100,
                "cg_relative_tolerance": 0.001,
                "tolerance_x": 0.001,
            },
            "beta": {
                "estimation": "by_eig",
                "beta0_ratio": 1.0,
                "cooling_factor": 5.0,
                "cooling_rate": 1,
            },
            "directives": {
                "sensitivity_weighting": {"enabled": True, "every_iteration": False},
                "update_preconditioner": True,
                "save_iteration_metrics": False,
            },
            "directive_strategy": "simpeg_cross_gradient_tutorial",
            "topography_path": topography_path.as_posix(),
        },
        "parameters": {"reference_dataset": SIMPEG_CROSS_GRADIENT.dataset_id},
    }
    run_spec_path = profile_directory / "run.yaml"
    run_spec_path.write_text(yaml.safe_dump(run_spec, sort_keys=False), encoding="utf-8")
    return PreparedGravMagJointReference(
        dataset_id=SIMPEG_CROSS_GRADIENT.dataset_id,
        gravity_observations_path=gravity_path.as_posix(),
        magnetic_observations_path=magnetic_path.as_posix(),
        topography_path=topography_path.as_posix(),
        run_spec_path=run_spec_path.as_posix(),
        observation_count=int(gravity_source.shape[0]),
    )


def _tutorial_density_model() -> dict[str, dict[str, float | str]]:
    return {
        "initial_density_contrast": {
            "value": 1e-6,
            "quantity_type": "density_contrast",
            "unit": "g/cm^3",
        },
        "lower_bound": {"value": -2.0, "quantity_type": "density_contrast", "unit": "g/cm^3"},
        "upper_bound": {"value": 2.0, "quantity_type": "density_contrast", "unit": "g/cm^3"},
    }


def _tutorial_l2_regularization() -> dict[str, float | str]:
    return {"kind": "l2", "alpha_s": 1.0, "alpha_x": 1.0, "alpha_y": 1.0, "alpha_z": 1.0}


def prepare_tdem1d_run(cache_root: Path) -> PreparedTDEMReference:
    """Derive a canonical-SI TDEM 1D profile from SimPEG's official sounding."""
    receipt = verify_reference_dataset(SIMPEG_TDEM1D.dataset_id, cache_root)
    source_values = np.loadtxt(Path(receipt.extracted_path) / "em1dtm_data.txt", skiprows=1)
    if (
        source_values.ndim != 2
        or source_values.shape[1] < 2
        or not np.isfinite(source_values).all()
        or np.any(source_values[:, 0] <= 0)
        or np.any(np.diff(source_values[:, 0]) <= 0)
    ):
        raise ValueError("official em1dtm_data.txt must contain finite, increasing time and B data")
    times = source_values[:, 0]
    observations = source_values[:, [0, -1]]
    profile_directory = Path("data/samples/AEM/simpeg_tdem1d")
    profile_directory.mkdir(parents=True, exist_ok=True)
    observations_path = profile_directory / "observations_si.csv"
    np.savetxt(
        observations_path,
        observations,
        delimiter=",",
        header="time_s,magnetic_flux_density_t",
        comments="",
        fmt="%.12e",
    )
    layer_thicknesses = np.logspace(0.0, 1.5, 25).tolist()
    run_spec = {
        "plugin_id": "simpeg.aem.tdem1d",
        "plugin_version": "0.1.0",
        "engine": "simpeg",
        "seed": 0,
        "dataset": {
            "name": "simpeg-tdem1d-derived-si",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "physical_quantity": "magnetic_flux_density",
            "units": "T",
        },
        "tdem_inversion": {
            "system": {
                "times": {"value": times.tolist(), "quantity_type": "time", "unit": "s"},
                "source_location": {
                    "value": [0.0, 0.0, 20.0],
                    "quantity_type": "length",
                    "unit": "m",
                },
                "receiver_location": {
                    "value": [0.0, 0.0, 20.0],
                    "quantity_type": "length",
                    "unit": "m",
                },
                "source_radius": {"value": 6.0, "quantity_type": "length", "unit": "m"},
                "source_current": {"value": 1.0, "quantity_type": "electric_current", "unit": "A"},
            },
            "earth": {
                "layer_thicknesses": {
                    "value": layer_thicknesses,
                    "quantity_type": "length",
                    "unit": "m",
                }
            },
            "model": {
                "initial_conductivity": {
                    "value": 0.1,
                    "quantity_type": "conductivity",
                    "unit": "S/m",
                },
                "lower_bound": {"value": 0.001, "quantity_type": "conductivity", "unit": "S/m"},
                "upper_bound": {"value": 10.0, "quantity_type": "conductivity", "unit": "S/m"},
            },
            "regularization": {"alpha_s": 0.01, "alpha_z": 1.0},
            "optimizer": {"max_iterations": 10, "cg_max_iterations": 30},
            "beta": {"estimation": "by_eig", "beta0_ratio": 100.0},
            "directives": {"save_iteration_metrics": True},
        },
        "parameters": {
            "observations_path": observations_path.as_posix(),
            "data_uncertainty": {
                "value": (0.05 * np.abs(observations[:, 1])).tolist(),
                "quantity_type": "magnetic_flux_density",
                "unit": "T",
            },
            "reference_dataset": SIMPEG_TDEM1D.dataset_id,
        },
    }
    run_spec_path = profile_directory / "run.yaml"
    run_spec_path.write_text(yaml.safe_dump(run_spec, sort_keys=False), encoding="utf-8")
    return PreparedTDEMReference(
        dataset_id=SIMPEG_TDEM1D.dataset_id,
        observations_path=observations_path.as_posix(),
        run_spec_path=run_spec_path.as_posix(),
        observation_count=int(observations.shape[0]),
    )


def prepare_tdem3d_tutorial_run(cache_root: Path) -> PreparedTDEM3DTutorialReference:
    """Materialize the geometry, waveform and model described by SimPEG's 3D tutorial."""
    profile_directory = Path("data/samples/AEM/simpeg_tdem3d_airborne")
    profile_directory.mkdir(parents=True, exist_ok=True)
    topography_path = profile_directory / "topography_si.csv"
    source_locations_path = profile_directory / "source_locations_m.npy"
    receiver_locations_path = profile_directory / "receiver_locations_m.npy"

    topo_axis = np.linspace(-3000.0, 3000.0, 101)
    topo_x, topo_y = np.meshgrid(topo_axis, topo_axis)
    topography = np.c_[topo_x.reshape(-1), topo_y.reshape(-1), np.zeros(topo_x.size)]
    np.savetxt(
        topography_path,
        topography,
        delimiter=",",
        header="x_m,y_m,z_m",
        comments="",
        fmt="%.12e",
    )
    survey_axis = np.linspace(-200.0, 200.0, 11)
    source_x, source_y = np.meshgrid(survey_axis, survey_axis)
    source_locations = np.c_[
        source_x.reshape(-1), source_y.reshape(-1), np.full(source_x.size, 50.0)
    ]
    receiver_x, receiver_y = np.meshgrid(survey_axis, np.linspace(-190.0, 190.0, 11))
    receiver_locations = np.c_[
        receiver_x.reshape(-1), receiver_y.reshape(-1), np.full(receiver_x.size, 30.0)
    ]
    np.save(source_locations_path, source_locations)
    np.save(receiver_locations_path, receiver_locations)
    run_spec = {
        "plugin_id": "simpeg.aem.tdem3d_forward",
        "plugin_version": "0.1.0",
        "engine": "simpeg",
        "seed": 0,
        "dataset": {
            "name": "simpeg-tdem3d-airborne-tutorial-profile",
            "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
            "physical_quantity": "magnetic_flux_density_time_derivative",
            "units": "T/s",
        },
        "mesh": {
            "cell_size": {"value": [25.0, 25.0, 25.0], "quantity_type": "length", "unit": "m"},
            "padding_distance": [
                {"value": [800.0, 800.0], "quantity_type": "length", "unit": "m"},
                {"value": [800.0, 800.0], "quantity_type": "length", "unit": "m"},
                {"value": [800.0, 800.0], "quantity_type": "length", "unit": "m"},
            ],
            "depth_core": {"value": 800.0, "quantity_type": "length", "unit": "m"},
            "surface_padding_cells": [0, 0, 0, 1],
            "receiver_padding_cells": [2, 4],
        },
        "tdem3d_forward": {
            "initial_time": {"value": -0.002, "quantity_type": "time", "unit": "s"},
            "system": {
                "times": {
                    "value": [0.0001, 0.000316227766, 0.001],
                    "quantity_type": "time",
                    "unit": "s",
                },
                "source_location": {
                    "value": [-200.0, -200.0, 50.0],
                    "quantity_type": "length",
                    "unit": "m",
                },
                "receiver_location": {
                    "value": [-200.0, -190.0, 30.0],
                    "quantity_type": "length",
                    "unit": "m",
                },
                "source_radius": {"value": 1.0, "quantity_type": "length", "unit": "m"},
                "source_current": {"value": 1.0, "quantity_type": "electric_current", "unit": "A"},
                "source_kind": "magnetic_dipole",
                "source_moment": {
                    "value": 1.0,
                    "quantity_type": "magnetic_dipole_moment",
                    "unit": "A*m^2",
                },
                "receiver_quantity": "magnetic_flux_density_time_derivative",
                "waveform": "piecewise_linear",
                "waveform_times": {
                    "value": [-0.002, -0.001, 0.0],
                    "quantity_type": "time",
                    "unit": "s",
                },
                "waveform_current_fractions": [0.0, 1.0, 0.0],
                "source_locations": {
                    "path": source_locations_path.as_posix(),
                    "quantity_type": "length",
                    "unit": "m",
                },
                "receiver_locations": {
                    "path": receiver_locations_path.as_posix(),
                    "quantity_type": "length",
                    "unit": "m",
                },
            },
            "model": {
                "conductivity": {"value": 0.002, "quantity_type": "conductivity", "unit": "S/m"},
                "conductivity_blocks": [
                    {
                        "minimum": {
                            "value": [-100.0, -100.0, -200.0],
                            "quantity_type": "length",
                            "unit": "m",
                        },
                        "maximum": {
                            "value": [100.0, 100.0, -50.0],
                            "quantity_type": "length",
                            "unit": "m",
                        },
                        "conductivity": {
                            "value": 2.0,
                            "quantity_type": "conductivity",
                            "unit": "S/m",
                        },
                    }
                ],
            },
            "time_steps": [
                {"step": {"value": 0.0001, "quantity_type": "time", "unit": "s"}, "count": 20},
                {"step": {"value": 0.00001, "quantity_type": "time", "unit": "s"}, "count": 10},
                {"step": {"value": 0.0001, "quantity_type": "time", "unit": "s"}, "count": 10},
            ],
        },
        "parameters": {
            "topography_path": topography_path.as_posix(),
            "reference_source_url": SIMPEG_TDEM3D_TUTORIAL_URL,
        },
    }
    run_spec_path = profile_directory / "run.yaml"
    run_spec_path.write_text(yaml.safe_dump(run_spec, sort_keys=False), encoding="utf-8")
    return PreparedTDEM3DTutorialReference(
        source_url=SIMPEG_TDEM3D_TUTORIAL_URL,
        topography_path=topography_path.as_posix(),
        source_locations_path=source_locations_path.as_posix(),
        receiver_locations_path=receiver_locations_path.as_posix(),
        run_spec_path=run_spec_path.as_posix(),
        sounding_count=int(source_locations.shape[0]),
    )


def _get_dataset(dataset_id: str) -> ReferenceDataset:
    for dataset in available_reference_datasets():
        if dataset.dataset_id == dataset_id:
            return dataset
    raise ValueError(f"unknown reference dataset {dataset_id!r}")


def _is_extracted_dataset_valid(path: Path, dataset: ReferenceDataset) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in dataset.required_files)


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = (destination / member.name).resolve()
            if not member_path.is_relative_to(root) or member.issym() or member.islnk():
                raise ValueError(f"unsafe path in reference archive: {member.name!r}")
        archive.extractall(destination, members=members, filter="data")


def _tutorial_padding_widths(
    *, core_cells: int, right_padding_cells: int = 5, cell_size: float = 5.0, factor: float = 1.3
) -> list[float]:
    """Materialize SimPEG's compact `(h, n, factor)` tutorial mesh notation."""
    left = [cell_size * factor**power for power in range(5, 0, -1)]
    core = [cell_size] * core_cells
    right = [cell_size * factor**power for power in range(1, right_padding_cells + 1)]
    return left + core + right
