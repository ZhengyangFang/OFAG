"""The roles: who holds what, and what the split refuses."""

from dataclasses import replace

import pytest

from ofag.agent import roles
from ofag.agent.dispatch import ToolError
from ofag.agent.mcp_server import brief_for, server_name
from ofag.agent.roles import ROLES, Role, brief, check_the_split, dispatcher_for, spec_for
from ofag.agent.tools import Tier


def test_the_split_as_written_breaks_none_of_its_rules() -> None:
    assert check_the_split() == []


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        (lambda: {Role.AUDIT: ("ofag.execute",)}, "produces what it audits"),
        (lambda: {Role.DATA: ("ofag.resolve_identifier",)}, "only literature"),
        (lambda: {Role.MODELLING: ("ofag.delete_run",)}, "only the lead"),
        (lambda: {Role.LEAD: ("ofag.audit",)}, "other than the auditor"),
        (lambda: {Role.MODELLING: ("ofag.diagnose",)}, "whoever executes"),
        (lambda: {Role.DATA: ("ofag.no_such_tool",)}, "do not exist"),
    ],
)
def test_a_split_that_undoes_the_design_is_caught(monkeypatch, change, complaint) -> None:
    altered = dict(ROLES)
    for role, extra in change().items():
        altered[role] = replace(ROLES[role], tools=ROLES[role].tools + extra)
    monkeypatch.setattr(roles, "ROLES", altered)

    assert any(complaint in problem for problem in check_the_split())


def test_a_tool_nobody_holds_is_caught(monkeypatch) -> None:
    altered = dict(ROLES)
    altered[Role.LEAD] = replace(
        ROLES[Role.LEAD], tools=tuple(t for t in ROLES[Role.LEAD].tools if t != "ofag.delete_run")
    )
    monkeypatch.setattr(roles, "ROLES", altered)

    assert any("no role holds ['ofag.delete_run']" in p for p in check_the_split())


class TestARolesSurface:
    def test_it_sees_its_own_tools_and_no_others(self, tmp_path) -> None:
        audit = dispatcher_for(Role.AUDIT, tmp_path)

        assert {t.name for t in audit.manifest()} == set(spec_for("audit").holds)

    def test_a_tool_it_does_not_hold_is_refused_by_name(self, tmp_path) -> None:
        with pytest.raises(ToolError, match="not a tool of audit"):
            dispatcher_for(Role.AUDIT, tmp_path).call("ofag.execute", {"spec": {}})

    def test_its_tiers_are_what_its_tools_need(self, tmp_path) -> None:
        assert Tier.OUTWARD in dispatcher_for(Role.LITERATURE, tmp_path).granted
        assert Tier.OUTWARD not in dispatcher_for(Role.AUDIT, tmp_path).granted
        assert Tier.DESTRUCTIVE in dispatcher_for(Role.LEAD, tmp_path).granted
        assert Tier.COMPUTE not in dispatcher_for(Role.MODELLING, tmp_path).granted

    def test_it_acts_under_its_name(self, tmp_path) -> None:
        assert dispatcher_for("inversion", tmp_path).actor == "inversion"

    def test_every_role_can_read_and_add_to_the_journal(self, tmp_path) -> None:
        for role in Role:
            names = {t.name for t in dispatcher_for(role, tmp_path).manifest()}
            assert {"ofag.journal", "ofag.note", "ofag.retrieve"} <= names

    def test_an_unknown_role_is_refused(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="no role 'critic'"):
            dispatcher_for("critic", tmp_path)


def test_every_role_uses_the_leads_model_unless_told_otherwise() -> None:
    """Independence comes from what the auditor is shown, not from its model."""
    assert all(spec.model is None for spec in ROLES.values())


def test_the_roles_that_fan_out_are_the_lead_the_auditor_and_the_developer() -> None:
    fan_out = {spec.role for spec in ROLES.values() if spec.subagents}

    assert fan_out == {Role.LEAD, Role.AUDIT, Role.DEVELOPER}


class TestTheBrief:
    def test_it_carries_the_roles_tools_and_quoted_passages(self) -> None:
        text = brief("audit", question="declared ramp time", method="tdem", k=3)

        assert text.startswith("# You are the audit role")
        assert "ofag.audit" in text and "ofag.execute" not in text
        assert text.count("\n### ") == 3
        assert "## Subagents" in text

    def test_with_no_task_it_leads_with_the_roles_own_steps(self) -> None:
        text = brief("modelling", k=5)

        headings = [line for line in text.splitlines() if line.startswith("### ")]
        assert headings and all("-- C" in line for line in headings)

    def test_a_role_that_works_alone_is_not_told_it_may_fan_out(self) -> None:
        assert "## Subagents" not in brief("data", k=1)


class TestOverMCP:
    def test_the_whole_surface_is_no_role_and_has_no_brief(self) -> None:
        with pytest.raises(ValueError, match="no role"):
            brief_for("", {"task": "anything"})

    def test_a_roles_server_is_named_for_it(self) -> None:
        assert (server_name(None), server_name("audit")) == ("ofag", "ofag-audit")

    def test_the_brief_prompt_is_the_roles_brief(self) -> None:
        text = brief_for("literature", {"task": "resolve the ScienceBase DOI", "method": ""})

        assert text.startswith("# You are the literature role")
        assert "ofag.resolve_identifier" in text


class TestRetrieveThroughTheSurface:
    def test_it_returns_quoted_passages_with_citations(self, tmp_path) -> None:
        answer = dispatcher_for(Role.DATA, tmp_path).call(
            "ofag.retrieve", {"procedure": "A13", "k": 2}
        )

        first = answer["passages"][0]
        assert first["id"] == "procedure:A13"
        assert first["cite_as"].startswith("docs/agent_validation_and_debugging.md -- A13.")

    def test_a_stage_that_is_not_one_is_refused(self, tmp_path) -> None:
        with pytest.raises(ToolError, match="has to be one of"):
            dispatcher_for(Role.DATA, tmp_path).call("ofag.retrieve", {"stage": "D"})


class TestAPublishedModelThroughTheRoles:
    """Case 2's path, end to end: a published inversion imported by the data role, diagnosed
    by inversion, audited by audit, read by modelling."""

    def test_import_diagnose_audit_build(self, tmp_path) -> None:
        from tests.test_line_data_import import CONVENTION, _release

        root = tmp_path / "artifacts"
        data, header = _release(tmp_path / "release", {"10010": 12})
        imported = dispatcher_for(Role.DATA, root).call(
            "ofag.import_data",
            {
                "importer_id": "ofag.import.layered_line",
                "request": {
                    "data_path": str(data),
                    "header_path": str(header),
                    "line": "10010",
                    "name": "Line 10010",
                    "coordinate_convention": CONVENTION,
                },
            },
        )
        run_id = str(imported["run_id"])

        dispatcher_for(Role.INVERSION, root).call(
            "ofag.diagnose", {"run_id": run_id, "evidence": "PhiD 1.02 at all twelve soundings"}
        )
        with pytest.raises(ToolError, match="not a tool of data"):
            dispatcher_for(Role.DATA, root).call(
                "ofag.audit", {"run_id": run_id, "verdict": "pass", "evidence": "x" * 20}
            )
        passed = dispatcher_for(Role.AUDIT, root).call(
            "ofag.audit",
            {"run_id": run_id, "verdict": "pass", "evidence": "misfit column and layer tops read"},
        )
        assert passed["audited"] is True

        modelling = dispatcher_for(Role.MODELLING, root)
        grid = modelling.call(
            "ofag.cell_grid",
            {
                "spec": {
                    "name": "line",
                    "min_x_m": 400000.0,
                    "max_x_m": 400275.0,
                    "min_y_m": 7500000.0,
                    "max_y_m": 7500022.0,
                    "cell_m": [25.0, 11.0, 10.0],
                    "depth_m": 60.0,
                    "ground_easting_m": [400000.0, 400275.0, 400000.0, 400275.0],
                    "ground_northing_m": [7500000.0, 7500000.0, 7500022.0, 7500022.0],
                    "ground_elevation_m": [300.0, 294.5, 300.0, 294.5],
                    "ground_source": "the release's own elevation column",
                }
            },
        )
        model = modelling.call(
            "ofag.build_model",
            {
                "grid_id": grid["grid_id"],
                "rules": [
                    {
                        "name": "conductive",
                        "source": "AEM",
                        "kind": "property_threshold",
                        "section": "aem",
                        "threshold": 0.004,
                        "below_threshold": False,
                    },
                    {"name": "rest", "source": "nothing measured here", "kind": "remainder"},
                ],
                "sections": {"aem": {"run_id": run_id, "as_resistivity": False}},
            },
        )

        assert model["built"] is True


class TestWhoOwnsEachStep:
    def test_every_step_of_the_procedure_has_an_owner(self) -> None:
        import re

        from ofag.agent.lessons import PROJECT_ROOT
        from ofag.agent.roles import STEP_OWNER

        text = (PROJECT_ROOT / "docs" / "agent_validation_and_debugging.md").read_text("utf-8")
        steps = set(re.findall(r"^### ([ABC]\d+)\.", text, re.M))

        assert steps == set(STEP_OWNER)

    def test_the_owner_holds_a_tool_that_acts_at_the_step(self) -> None:
        """Spot checks of the rule the table was drawn by."""
        from ofag.agent.roles import owner_of

        assert owner_of("C4") is Role.INVERSION  # ofag.sample
        assert "ofag.sample" in spec_for(owner_of("C4")).holds
        assert "ofag.cell_grid" in spec_for(owner_of("A12")).holds
        assert "ofag.resolve_identifier" in spec_for(owner_of("A13")).holds
        assert "ofag.import_data" in spec_for(owner_of("A3")).holds

    def test_every_placed_lesson_has_an_owner_and_no_step_belongs_to_the_auditor(self) -> None:
        from ofag.agent.lessons import load_lessons
        from ofag.agent.roles import STEP_OWNER, owner_of

        lessons = load_lessons()
        assert all(owner_of(lesson.procedure) for lesson in lessons if lesson.procedure)
        assert Role.AUDIT not in STEP_OWNER.values()
