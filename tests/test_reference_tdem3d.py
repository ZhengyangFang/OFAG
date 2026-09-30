from pathlib import Path

import yaml

from ofag.core.schemas import RunSpec
from ofag.reference_data import SIMPEG_TDEM3D_TUTORIAL_URL, prepare_tdem3d_tutorial_run


def test_prepare_tdem3d_tutorial_profile_is_loadable(tmp_path: Path) -> None:
    prepared = prepare_tdem3d_tutorial_run(tmp_path)
    spec = RunSpec.model_validate(
        yaml.safe_load(Path(prepared.run_spec_path).read_text(encoding="utf-8"))
    )

    assert prepared.source_url == SIMPEG_TDEM3D_TUTORIAL_URL
    assert prepared.sounding_count == 121
    assert spec.tdem3d_forward is not None
    assert spec.tdem3d_forward.system.source_kind == "magnetic_dipole"
    assert len(spec.tdem3d_forward.system.time_gates) == 0
    assert spec.tdem3d_forward.initial_time.value == -0.002
    assert spec.tdem3d_forward.model.conductivity_blocks
