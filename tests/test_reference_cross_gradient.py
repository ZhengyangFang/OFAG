from pathlib import Path

import numpy as np
import yaml

from ofag.core.schemas import RunSpec
from ofag.reference_data import prepare_cross_gradient_joint_run


def test_prepare_cross_gradient_joint_profile_preserves_tutorial_controls(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "reference-cache" / "cross_gradient_data"
    source.mkdir(parents=True)
    gravity = np.array([[-10.0, -10.0, 5.0, -2.0], [10.0, 10.0, 5.0, 4.0]], dtype=float)
    magnetic = np.array([[-10.0, -10.0, 5.0, -100.0], [10.0, 10.0, 5.0, 250.0]], dtype=float)
    np.savetxt(source / "gravity_data.obs", gravity)
    np.savetxt(source / "magnetic_data.obs", magnetic)
    np.savetxt(source / "topo.txt", np.array([[-20.0, -20.0, 0.0], [20.0, 20.0, 0.0]]))
    monkeypatch.chdir(tmp_path)

    prepared = prepare_cross_gradient_joint_run(tmp_path / "reference-cache")

    spec = RunSpec.model_validate(yaml.safe_load(Path(prepared.run_spec_path).read_text()))
    assert spec.plugin_id == "simpeg.joint.gravmag.cross_gradient"
    assert spec.gravmag_joint_inversion is not None
    config = spec.gravmag_joint_inversion
    assert config.coupling.weight == 2e12
    assert config.coupling.normalize_models is False
    assert config.directive_strategy == "simpeg_cross_gradient_tutorial"
    assert config.gravity.simulation.engine == "choclo"
    assert config.magnetics.simulation.engine == "geoana"
    assert config.optimizer.cg_max_iterations == 100
    assert config.beta.cooling_factor == 5.0
    gravity_channel = spec.channel(config.gravity_channel)
    magnetics_channel = spec.channel(config.magnetics_channel)
    assert gravity_channel is not None and magnetics_channel is not None
    assert gravity_channel.data_uncertainty.value == 0.04
    assert magnetics_channel.data_uncertainty.value == 2.5
    tmi = np.genfromtxt(prepared.magnetic_observations_path, delimiter=",", names=True)
    assert np.allclose(tmi["tmi_nt"], [-100.0, 250.0])
