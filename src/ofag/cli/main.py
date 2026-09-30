"""Composable local CLI; stdout is JSON only when --json is requested."""

import ipaddress
import json
import os
import sys
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
import yaml

from ofag.core.schemas import RunSpec
from ofag.reference_data import (
    available_reference_datasets,
    fetch_reference_dataset,
    prepare_cross_gradient_gravity_run,
    prepare_cross_gradient_joint_run,
    prepare_tdem1d_run,
    prepare_tdem3d_tutorial_run,
    verify_reference_dataset,
)
from ofag.services.project_folder import DEFAULT_RESULT_ROOT
from ofag.services.run_service import RunService
from ofag.services.run_start_policy import RunStartPolicy

app = typer.Typer(help="OFAG local inversion orchestration CLI", no_args_is_help=True)
reference_data_app = typer.Typer(help="Official numerical reference data.")
app.add_typer(reference_data_app, name="reference-data")
_service = RunService()


def _runs_for(project_id: UUID | None = None, run_id: UUID | None = None) -> RunService:
    """The run service rooted where this run's project keeps its work."""
    from ofag.services.project_service import ProjectService

    projects = ProjectService()
    if project_id is not None:
        try:
            return RunService(artifact_root=projects.folder(project_id).runs_root)
        except KeyError as error:
            raise typer.BadParameter(
                f"project {project_id} was not found under {projects.result_root}"
            ) from error
    if run_id is not None:
        from ofag.services.project_folder import folders_in
        from ofag.services.project_paths import repair_project_paths

        for folder in folders_in(projects.result_root):
            if (folder.runs_root / str(run_id)).is_dir():
                repair_project_paths(folder)
                return RunService(artifact_root=folder.runs_root)
    return _service


def _emit(ctx: typer.Context, value: Any) -> None:
    if ctx.obj and ctx.obj["json"]:
        typer.echo(json.dumps(value, default=str, sort_keys=True))
    else:
        typer.echo(yaml.safe_dump(value, sort_keys=True))


@app.callback()
def main(
    ctx: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@app.command()
def doctor(
    ctx: typer.Context,
    self_test: Annotated[
        bool, typer.Option("--self-test", help="Run an offline child-process fixture.")
    ] = False,
) -> None:
    """Report optional modules and optionally exercise the installed core."""
    requirements = {
        "desktop": ("PySide6",),
        "simpeg": ("simpeg", "choclo", "sklearn"),
        "pygimli": ("pygimli", "pgcore"),
        "seismic": ("deepwave", "segyio", "torch"),
        "gempy": ("gempy", "gempy_engine"),
        "mcp": ("mcp",),
    }
    features = {
        name: {
            "available": all(find_spec(module) is not None for module in modules),
            "missing_modules": [module for module in modules if find_spec(module) is None],
        }
        for name, modules in requirements.items()
    }
    supported_python = (3, 11) <= sys.version_info[:2] < (3, 13)
    runtime_test: dict[str, bool | str] | None = None
    if self_test:
        from ofag.services.diagnostics import run_offline_self_test

        try:
            passed, detail = run_offline_self_test()
        except (OSError, ValueError, RuntimeError) as error:
            passed, detail = False, str(error)
        runtime_test = {"passed": passed, "detail": detail}
    _emit(
        ctx,
        {
            "status": "ok"
            if supported_python and (runtime_test is None or runtime_test["passed"])
            else "failed",
            "mode": "local",
            "python_supported": supported_python,
            "features": features,
            "runtime_self_test": runtime_test,
            "check_scope": (
                "installed modules and offline fixture; numerical solvers and user data are not "
                "exercised"
                if self_test
                else "installed modules only; use --self-test to exercise the core worker"
            ),
            "auth_required": False,
            "artifact_root": "artifacts",
        },
    )


@app.command("plugins")
def plugins(ctx: typer.Context) -> None:
    """List installed inversion plugins and their limitations."""
    _emit(ctx, [manifest.model_dump(mode="json") for manifest in _service.list_plugins()])


@reference_data_app.command("list")
def reference_data_list(ctx: typer.Context) -> None:
    """List the fixed source URLs available to fetch."""
    _emit(
        ctx,
        [
            {
                "dataset_id": item.dataset_id,
                "source_url": item.source_url,
            }
            for item in available_reference_datasets()
        ],
    )


@reference_data_app.command("fetch")
def reference_data_fetch(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument()],
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Fetch one official fixture."""
    receipt = fetch_reference_dataset(dataset_id, cache_dir)
    _emit(ctx, receipt.__dict__)


@reference_data_app.command("verify")
def reference_data_verify(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument()],
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Verify a cached fixture offline without downloading it again."""
    receipt = verify_reference_dataset(dataset_id, cache_dir)
    _emit(ctx, receipt.__dict__)


@reference_data_app.command("prepare-gravity")
def reference_data_prepare_gravity(
    ctx: typer.Context,
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Derive a full-size gravity-only RunSpec from the cached joint fixture."""
    prepared = prepare_cross_gradient_gravity_run(cache_dir)
    _emit(ctx, prepared.__dict__)


@reference_data_app.command("prepare-gravmag-joint")
def reference_data_prepare_gravmag_joint(
    ctx: typer.Context,
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Materialize SimPEG's complete gravity/TMI cross-gradient tutorial profile."""
    prepared = prepare_cross_gradient_joint_run(cache_dir)
    _emit(ctx, prepared.__dict__)


@reference_data_app.command("prepare-tdem1d")
def reference_data_prepare_tdem1d(
    ctx: typer.Context,
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Derive an SI, official-TDEM single-sounding RunSpec from the cached fixture."""
    prepared = prepare_tdem1d_run(cache_dir)
    _emit(ctx, prepared.__dict__)


@reference_data_app.command("prepare-tdem3d-tutorial")
def reference_data_prepare_tdem3d_tutorial(
    ctx: typer.Context,
    cache_dir: Annotated[Path, typer.Option()] = Path("data/reference-cache"),
) -> None:
    """Materialize the official 3D airborne-TDEM tutorial as an opt-in OFAG profile."""
    prepared = prepare_tdem3d_tutorial_run(cache_dir)
    _emit(ctx, prepared.__dict__)


def _load_spec(path: Path) -> RunSpec:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise typer.BadParameter(f"cannot read {path}: {error}") from error
    if not isinstance(payload, dict):
        raise typer.BadParameter("run specification must be a YAML object")
    return RunSpec.model_validate(payload)


@app.command("validate")
def validate(
    ctx: typer.Context,
    spec_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate a RunSpec without dispatching numerical work."""
    spec = _load_spec(spec_path)
    report = _service.validate(spec)
    _emit(ctx, report.model_dump(mode="json"))
    if not report.valid:
        raise typer.Exit(code=2)


@app.command("estimate")
def estimate(
    ctx: typer.Context,
    spec_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Estimate resources without creating or dispatching a run."""
    spec = _load_spec(spec_path)
    report = _service.validate(spec)
    if not report.valid:
        _emit(ctx, report.model_dump(mode="json"))
        raise typer.Exit(code=2)
    _emit(ctx, _service.estimate_resources(spec).model_dump(mode="json"))


@app.command("run")
def run(
    ctx: typer.Context,
    spec_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    sample_run_id: Annotated[UUID | None, typer.Option(help="Completed smaller trial run.")] = None,
    allow_unchecked_large_run: Annotated[
        bool,
        typer.Option(help="Waive the large-run trial after reviewing the estimate."),
    ] = False,
) -> None:
    """Create and submit one validated run."""
    spec = _load_spec(spec_path)
    runs = _runs_for(project_id=spec.project_id)
    policy = RunStartPolicy(runs)
    try:
        assessment = policy.check(
            spec,
            sample_run_id=sample_run_id,
            allow_unchecked_large_run=allow_unchecked_large_run,
        )
    except (KeyError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    record = runs.create(spec)
    policy.record(spec, assessment)
    record = runs.start(record.spec.run_id)
    # The executor's worker is a daemon child of this CLI process.
    try:
        while record.state.value == "RUNNING":
            time.sleep(0.05)
            record = runs.get(record.spec.run_id)
    except KeyboardInterrupt:
        # On Windows the worker shares this console and takes the same Ctrl+C, so by the
        # time this runs the watcher may already have moved the run to FAILED or
        # SUCCEEDED and cancel refuses.
        try:
            record = runs.cancel(record.spec.run_id)
        except ValueError:
            record = runs.get(record.spec.run_id)
        _emit(ctx, record.model_dump(mode="json"))
        raise typer.Exit(code=130) from None
    _emit(ctx, record.model_dump(mode="json"))


@app.command("status")
def status_command(ctx: typer.Context, run_id: str) -> None:
    """Read one run by stable UUID."""
    identifier = UUID(run_id)
    _emit(ctx, _runs_for(run_id=identifier).get(identifier).model_dump(mode="json"))


@app.command("workbench")
def workbench(
    result_root: Annotated[Path, typer.Option()] = DEFAULT_RESULT_ROOT,
) -> None:
    """Open the desktop workbench."""
    from ofag.desktop.app import run_desktop

    raise typer.Exit(code=run_desktop(result_root))


@app.command("project-pack")
def project_pack(
    ctx: typer.Context,
    project_id: UUID,
    destination: Annotated[Path, typer.Option(help="Parent directory for the portable copy.")],
    result_root: Annotated[Path, typer.Option(help="Directory containing the project.")] = (
        DEFAULT_RESULT_ROOT
    ),
) -> None:
    """Copy a project with its referenced external inputs for another machine."""
    from ofag.services.project_service import ProjectService

    try:
        exported = ProjectService(result_root).export_portable(project_id, destination)
    except (KeyError, OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    _emit(ctx, {"project_id": str(project_id), "path": str(exported)})


@app.command("cancel")
def cancel(ctx: typer.Context, run_id: str) -> None:
    """Cancel one queued or running run."""
    identifier = UUID(run_id)
    _emit(ctx, _runs_for(run_id=identifier).cancel(identifier).model_dump(mode="json"))


@app.command("delete")
def delete(
    ctx: typer.Context,
    run_id: str,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete one finished run and everything it wrote."""
    identifier = UUID(run_id)
    runs = _runs_for(run_id=identifier)
    record = runs.get(identifier)
    described = record.spec.label or str(identifier)
    if not yes:
        typer.confirm(
            f"Delete run {described} and everything it wrote "
            f"({runs.run_dir(identifier)})? This cannot be undone.",
            abort=True,
        )
    runs.delete(identifier)
    _emit(ctx, {"run_id": str(identifier), "deleted": True})


@app.command("artifacts")
def artifacts(ctx: typer.Context, run_id: str) -> None:
    """List portable artifacts for a completed run."""
    identifier = UUID(run_id)
    result = _runs_for(run_id=identifier).result(identifier)
    _emit(
        ctx,
        [] if result is None else [item.model_dump(mode="json") for item in result.artifacts],
    )


@app.command("agent-tools")
def agent_tools(
    artifact_root: Annotated[Path, typer.Option(help="Where runs and the ledger live.")] = Path(
        "Result"
    ),
    role: Annotated[
        str | None,
        typer.Option(
            help="Serve one role's tools only: lead, data, inversion, modelling, "
            "audit, literature or developer."
        ),
    ] = None,
) -> None:
    """Serve the agent tool surface over MCP on stdio, for an external agent."""
    from ofag.agent.roles import dispatcher_for, spec_for

    try:
        from ofag.agent.mcp_server import serve as serve_tools
    except ImportError as missing:  # pragma: no cover
        raise typer.BadParameter(
            f"the MCP transport needs the 'mcp' extra: uv sync --extra mcp ({missing})"
        ) from missing

    if role is None:
        from ofag.agent.dispatch import Dispatcher
        from ofag.agent.tools import tool_manifest

        # Named, so what it runs can be audited by a role server; unnamed, nothing it
        # executed could ever be audited (obligations.INDEPENDENT_OF).
        everything_but_audit = frozenset(
            tool.name for tool in tool_manifest() if tool.name != "ofag.audit"
        )
        serve_tools(
            artifact_root,
            Dispatcher(artifact_root=artifact_root, actor="surface", allowed=everything_but_audit),
        )
        return
    try:
        spec = spec_for(role)
    except ValueError as unknown:
        raise typer.BadParameter(str(unknown)) from unknown
    serve_tools(artifact_root, dispatcher_for(spec.role, artifact_root), role=spec.role.value)


@app.command("agent-chat")
def agent_chat(
    artifact_root: Annotated[Path, typer.Option(help="The project's runs folder.")] = Path(
        "Result"
    ),
) -> None:
    """Talk to the agents in the terminal, with the model set in the desktop's Agents panel."""
    from ofag.agent.orchestrator import Cancelled, Event, Orchestrator
    from ofag.agent.providers import ProviderError, load_settings, model_from, resolve_key

    settings = load_settings()
    try:
        key = resolve_key(settings.provider)
    except ProviderError as missing:
        raise typer.BadParameter(str(missing)) from missing

    def show(event: Event) -> None:
        if event.kind == "delegate":
            typer.echo(f"  -> {event.role}: {event.text}")
        elif event.kind == "tool_call":
            typer.echo(f"     {event.role} . {event.text}")
        elif event.kind == "report":
            typer.echo(f"  <- {event.role} reports")
        elif event.kind == "error":
            typer.echo(f"  !  {event.role}: {event.text}")

    def approve(role: str, tool: str, arguments: dict[str, object]) -> bool:
        return typer.confirm(f"The {role} agent wants {tool} {arguments}. Allow?", default=False)

    where = "this machine" if settings.provider.is_local else settings.provider.host
    typer.echo(f"{settings.provider.model}, sent to {where}. Empty line to stop.")
    runner = Orchestrator(
        artifact_root,
        lambda role: model_from(
            settings.config_for(role.value), key, session_id=f"ofag-{runner.conversation_id}"
        ),
        approve=approve,
        emit=show,
    )
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        try:
            typer.echo(f"\nlead> {runner.ask(text)}")
        except (Cancelled, KeyboardInterrupt):
            typer.echo("stopped")
        except ProviderError as failed:
            typer.echo(f"the model could not be reached: {failed}")
    typer.echo(f"conversation kept at {runner.log_path}")


@app.command("agent-test")
def agent_test() -> None:
    """Send one small request with the saved model settings and show what came back."""
    from dataclasses import replace

    from ofag.agent.providers import ProviderError, endpoint, load_settings, probe, resolve_key

    settings = load_settings()
    config = replace(settings.provider, timeout_s=30.0, max_tokens=64)
    typer.echo(f"{config.kind.value}  {config.model}  ->  {endpoint(config.kind, config.base_url)}")
    try:
        answer = probe(config, resolve_key(config))
    except ProviderError as failed:
        typer.echo(f"failed: {failed}")
        raise typer.Exit(code=1) from None
    typer.echo(f"works: {answer}")


@app.command("agent-brief")
def agent_brief(
    role: Annotated[str, typer.Argument(help="The role to brief.")],
    task: Annotated[str, typer.Option(help="What the role is being asked to do.")] = "",
    method: Annotated[str | None, typer.Option(help="Prefer passages about this method.")] = None,
) -> None:
    """Print the brief a role is started with, retrieved passages included."""
    from ofag.agent.roles import brief

    try:
        text = brief(role, question=task, method=method)
    except ValueError as refused:
        raise typer.BadParameter(str(refused)) from refused
    # The passages are quoted, and they carry minus signs, micro signs and em dashes
    # that a Windows console's code page cannot encode.
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace")
    typer.echo(text)


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve locally, or require authentication before listening on a network."""
    import uvicorn

    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    if not loopback and (
        os.getenv("OFAG_ENV", "development").lower() != "production"
        or not os.getenv("OFAG_API_TOKEN")
    ):
        raise typer.BadParameter(
            "network listening requires OFAG_ENV=production and OFAG_API_TOKEN"
        )
    uvicorn.run("ofag.api.app:app", host=host, port=port, reload=False)
