"""Model audits compare stated choices with the saved interpretation."""

import numpy as np
import pytest

from ofag.agent.model_stability import evaluate
from ofag.agent.roles import Role, dispatcher_for
from ofag.agent.volumes import CellGridSpec, build_cell_grid
from ofag.core.schemas import UnitRule, UnitRuleKind
from ofag.services.interpretation_service import LayeredSection


def test_27_choice_model_stability_keeps_a_depth_profile(tmp_path) -> None:
    grid = build_cell_grid(
        CellGridSpec(
            name="synthetic",
            min_x_m=0,
            max_x_m=20,
            min_y_m=0,
            max_y_m=20,
            cell_m=(10, 10, 10),
            depth_m=30,
            ground_easting_m=(5,),
            ground_northing_m=(5,),
            ground_elevation_m=(0,),
            ground_source="declared synthetic surface",
        )
    )
    section = LayeredSection(
        easting_m=np.array([5.0]),
        northing_m=np.array([5.0]),
        values=np.array([[10.0, 6.0, 4.0]]),
        layer_top_depth_m=np.array([0.0, 10.0, 20.0]),
    )
    rules = (
        UnitRule(
            name="resistive",
            source="synthetic method",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="electrical",
            threshold=5.0,
            below_threshold=False,
            reach_m=200.0,
            resolved_to_depth_m=30.0,
        ),
        UnitRule(name="unassigned", source="none", kind=UnitRuleKind.REMAINDER),
    )

    result = evaluate(
        grid,
        rules,
        {},
        {"electrical": section},
        rule_name="resistive",
        thresholds=[2.0, 5.0, 8.0],
        reaches_m=[2.0, 20.0, 200.0],
        depth_limits_m=[10.0, 20.0, 30.0],
    )

    assert result.variant_count == 27
    assert result.agreement.shape == (grid.cells,)
    assert np.all((result.agreement >= 0) & (result.agreement <= 1))
    assert len(result.depth_profile) == 3
    assert any(0 < row["mean_agreement"] < 1 for row in result.depth_profile)
    assert {item.name for item in dispatcher_for(Role.AUDIT, tmp_path).manifest()} >= {
        "ofag.model_stability"
    }
    assert "ofag.model_stability" not in {
        item.name for item in dispatcher_for(Role.MODELLING, tmp_path).manifest()
    }


def test_model_stability_rejects_invalid_choice_ranges() -> None:
    with pytest.raises(ValueError, match="Name one"):
        evaluate(
            build_cell_grid(
                CellGridSpec(
                    name="synthetic",
                    min_x_m=0,
                    max_x_m=10,
                    min_y_m=0,
                    max_y_m=10,
                    cell_m=(10, 10, 10),
                    depth_m=10,
                    ground_easting_m=(0,),
                    ground_northing_m=(0,),
                    ground_elevation_m=(0,),
                    ground_source="declared synthetic surface",
                )
            ),
            (UnitRule(name="other", source="none", kind=UnitRuleKind.REMAINDER),),
            {},
            {},
            rule_name="missing",
            thresholds=[1.0, 2.0],
            reaches_m=[1.0, 2.0],
            depth_limits_m=[1.0, 2.0],
        )
