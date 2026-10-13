# OFAG

OFAG is an open framework for geophysical data import, inversion, project records, and agent-assisted review. It provides a command-line interface, a local HTTP API, and an optional desktop workbench.

This repository currently opens only part of the code and documentation for peer review. The complete OFAG system and related author-created documentation will be released after the manuscript is accepted. Case-specific data, scripts, figures, run records, and research knowledge are held by the authors during review. Third-party datasets remain subject to their original access and redistribution terms.

## Install

Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/) are required for the development workflow.

```powershell
uv sync --locked
uv run ofag --json doctor --self-test
```

Optional numerical engines and the desktop interface can be installed with extras:

```powershell
uv sync --locked --extra simpeg --extra desktop
uv run ofag workbench
```

Run `uv run ofag --help` for CLI commands. The HTTP server starts with `uv run ofag serve`. The desktop and server use the same project and run services.

## Agent access

The Agent tools use a provider selected by the user. An API key can be supplied through an environment variable. `ofag auth login gpt` supports the available ChatGPT browser sign-in, and `ofag auth login claude` uses the Anthropic Console sign-in provided by its CLI. `ofag auth status` reports the selected provider without displaying credentials. Account access and provider availability depend on the provider.

The included knowledge corpus is a small synthetic demonstration. It is labelled as such and does not represent the manuscript's full research corpus. Audit decisions for a user's project are recorded by the runtime in that user's project directory.

The Lead Agent can delegate missing Python capabilities to the Developer Agent. Set `OFAG_DEVELOPER_WRITE_ENABLED=1` before starting OFAG to allow it to create a private Git worktree, edit source and tests, and return a local branch after Ruff, mypy and pytest pass. It never merges or pushes. The Audit Agent can call `ofag.model_stability` on a saved model recipe to recompute labels across stated threshold, reach and depth-limit choices; this does not approve a run audit.

The Data Agent can call `ofag.ert_reciprocal_qc` on an imported ERT dataset. It pairs normal and reciprocal readings, applies the specified disagreement limit, optionally checks an aligned contact-resistance CSV, and saves retained observations with a fitted error model and rejection counts.

## Scope

The source code is [MIT licensed](LICENSE). [Architecture](docs/architecture.md), [unit policy](docs/unit_policy.md), [workbench guidance](docs/workbench.md), and [public release scope](docs/release_scope.md) describe the distributed software. Field datasets and unpublished case materials are separate from this license.
