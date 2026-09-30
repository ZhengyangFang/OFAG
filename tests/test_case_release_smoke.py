"""A small Cedar case configuration through the production FDEM adapter."""

import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from ofag.core.schemas import RunSpec
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_fdem1d import SimPEGFDEM1DPlugin


def test_cedar_aem_case_builder_executes_one_small_sounding(tmp_path: Path) -> None:
    pytest.importorskip("simpeg")
    case_script = Path(__file__).resolve().parents[1] / "scripts/case2_cedar_rapids.py"
    case = runpy.run_path(str(case_script))
    observations = tmp_path / "response.csv"
    observations.write_text("response_ppm\n" + "100\n" * 12, encoding="utf-8")
    spec = case["_aem_run_spec"](
        SimpleNamespace(project_id=uuid4()),
        [
            {
                "sounding_id": "small-1",
                "observations_path": str(observations),
                "easting_m": 600_000.0,
                "northing_m": 4_650_000.0,
                "flight_height_m": 50.0,
            }
        ],
    )

    # Retain the case builder's units, system conventions and schema, while limiting the
    # calculation to one pair, two layers and two iterations.
    payload = spec.model_dump(mode="json")
    payload["physics"]["earth"]["layer_thicknesses"]["value"] = [5.0]
    payload["physics"]["optimizer"]["max_iterations"] = 2
    payload["physics"]["system"]["coil_pairs"] = payload["physics"]["system"]["coil_pairs"][:1]
    payload["physics"]["soundings"][0]["data_uncertainty"]["value"] = [10.0, 10.0]
    observations.write_text("response_ppm\n100\n100\n", encoding="utf-8")
    small = RunSpec.model_validate(payload)

    plugin = SimPEGFDEM1DPlugin()
    context = PluginContext(tmp_path)
    assert plugin.validate(context, small).valid
    result = plugin.execute(context, small)
    assert result.summary["sounding_count"] == 1
    section = np.load(tmp_path / result.artifacts[0].relative_path)
    assert section["conductivity_s_m"].shape == (1, 2)
    assert np.isfinite(section["chi_squared"]).all()
