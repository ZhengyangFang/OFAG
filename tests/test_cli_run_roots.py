"""Where the command line puts a run."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from ofag.cli import main as cli_main
from ofag.cli.main import _runs_for, _service
from ofag.core.schemas import CoordinateConvention, ProjectCreateRequest
from ofag.services.project_service import ProjectService


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectService, object]:
    monkeypatch.chdir(tmp_path)
    projects = ProjectService(root=Path("Result"))
    record = projects.create(
        ProjectCreateRequest(
            name="Slag dump",
            coordinate_convention=CoordinateConvention(crs="EPSG:31467"),
            elevation_reference="local datum",
            enabled_methods=("ert",),
        )
    )
    return projects, record.project_id


def test_a_spec_puts_its_run_in_the_project_it_names(project) -> None:  # type: ignore[no-untyped-def]
    projects, project_id = project

    service = _runs_for(project_id=project_id)

    assert service.artifact_root == projects.folder(project_id).runs_root


def test_a_run_is_found_by_identifier_across_the_projects(project) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    projects, project_id = project
    run_id = uuid4()
    runs_root = projects.folder(project_id).runs_root
    (runs_root / str(run_id)).mkdir(parents=True)

    assert _runs_for(run_id=run_id).artifact_root == runs_root
    # One that is nowhere falls back rather than raising: `ofag status` on an unknown
    # identifier should report that it is unknown, not fail to start.
    assert _runs_for(run_id=uuid4()).artifact_root == _service.artifact_root


def test_a_spec_naming_a_missing_project_is_rejected(project) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    with pytest.raises(typer.BadParameter, match="was not found"):
        _runs_for(project_id=uuid4())


def test_network_api_requires_production_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OFAG_ENV", raising=False)
    monkeypatch.delenv("OFAG_API_TOKEN", raising=False)
    with pytest.raises(typer.BadParameter, match="network listening requires"):
        cli_main.serve(host="0.0.0.0", port=8000)


def test_cli_keeps_owning_a_long_run_until_it_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A daemon worker must not be abandoned at the old sixty-second deadline."""
    from uuid import uuid4

    run_id = uuid4()
    project_id = uuid4()
    spec = SimpleNamespace(run_id=run_id, project_id=project_id)

    class Record:
        def __init__(self, state: str) -> None:
            self.spec = spec
            self.state = SimpleNamespace(value=state)

        def model_dump(self, mode: str) -> dict[str, str]:
            return {"state": self.state.value}

    class Runs:
        polls = 0

        def create(self, given: object) -> Record:
            assert given is spec
            return Record("VALIDATED")

        def start(self, given: object) -> Record:
            assert given == run_id
            return Record("RUNNING")

        def get(self, given: object) -> Record:
            assert given == run_id
            self.polls += 1
            return Record("SUCCEEDED" if self.polls == 3 else "RUNNING")

    runs = Runs()
    emitted: list[dict[str, str]] = []
    monkeypatch.setattr(cli_main, "_load_spec", lambda path: spec)
    monkeypatch.setattr(cli_main, "_runs_for", lambda project_id: runs)
    monkeypatch.setattr(
        cli_main,
        "RunStartPolicy",
        lambda selected: SimpleNamespace(
            check=lambda given, **options: None,
            record=lambda given, assessment: None,
        ),
    )
    monkeypatch.setattr(cli_main.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(cli_main, "_emit", lambda ctx, value: emitted.append(value))
    cli_main.run(object(), Path("unused.yaml"), None, False)  # type: ignore[arg-type]

    assert runs.polls == 3
    assert emitted == [{"state": "SUCCEEDED"}]


def test_doctor_reports_missing_optional_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(cli_main, "find_spec", lambda module: None)
    monkeypatch.setattr(cli_main, "_emit", lambda ctx, value: emitted.append(value))

    cli_main.doctor(object())  # type: ignore[arg-type]

    assert emitted[0]["status"] == "ok"
    features = emitted[0]["features"]
    assert isinstance(features, dict)
    assert features["simpeg"]["missing_modules"] == ["simpeg", "choclo", "sklearn"]


def test_doctor_self_test_exercises_a_worker_and_artifact(tmp_path: Path) -> None:
    from ofag.services.diagnostics import run_offline_self_test

    passed, detail = run_offline_self_test(tmp_path)

    assert passed, detail


def test_cli_packs_a_project_under_an_explicit_result_root(
    project,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, project_id = project
    emitted: list[dict[str, str]] = []
    monkeypatch.setattr(cli_main, "_emit", lambda ctx, value: emitted.append(value))

    cli_main.project_pack(object(), project_id, tmp_path / "recipient", projects.result_root)  # type: ignore[arg-type]

    assert Path(emitted[0]["path"]).is_dir()
    assert (Path(emitted[0]["path"]) / "project.json").is_file()
