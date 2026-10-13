"""The tool surface over MCP, for an agent that is not in this process."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.agent.tools import Tool

__all__ = ["ToolDescription", "described", "answer", "brief_for", "server_name", "serve"]

#: The name the transport announces itself under.
SERVER_NAME = "ofag"


@dataclass(frozen=True)
class ToolDescription:
    """One tool as a protocol wants it: a name, prose and a schema."""

    name: str
    description: str
    input_schema: dict[str, Any]


def described(tool: Tool) -> ToolDescription:
    """One tool, with what it refuses written into what an agent reads."""
    prose = tool.summary.strip()
    if tool.refuses:
        prose = f"{prose}\n\nRefuses: {tool.refuses.strip()}"
    return ToolDescription(
        name=tool.name,
        description=f"{prose}\n\nTier: {tool.tier.value}.",
        input_schema=tool.input_schema,
    )


def answer(dispatcher: Dispatcher, name: str, arguments: dict[str, Any] | None) -> tuple[str, bool]:
    """Make one call and render it as text, plus whether it is an error."""
    try:
        result = dispatcher.call(name, arguments)
    except ToolError as refusal:
        return str(refusal), True
    if isinstance(result, str):
        return result, False
    return json.dumps(result, indent=2, default=str), False


#: The one prompt a role's server offers, and the arguments it takes.
BRIEF_PROMPT = "brief"
BRIEF_ARGUMENTS = (
    ("task", "What this role is being asked to do, in a sentence.", True),
    ("method", "tdem, fdem, ert, mt, gravity, magnetic, seismic or boreholes.", False),
)


def server_name(role: str | None) -> str:
    """`ofag` for the whole surface, `ofag-<role>` for one role's."""
    return SERVER_NAME if not role else f"{SERVER_NAME}-{role}"


def brief_for(role: str, arguments: dict[str, str] | None) -> str:
    """The text of one role's brief prompt."""
    from ofag.agent.roles import brief

    given = dict(arguments or {})
    method = (given.get("method") or "").strip() or None
    return brief(role, question=given.get("task", ""), method=method)


def serve(  # pragma: no cover
    artifact_root: Path, dispatcher: Dispatcher | None = None, *, role: str | None = None
) -> None:
    """Run the stdio loop until the client closes it."""
    import anyio
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    router = dispatcher or Dispatcher(artifact_root=artifact_root)
    server: Server = Server(server_name(role))

    @server.list_prompts()  # type: ignore[untyped-decorator, no-untyped-call]
    async def list_prompts() -> list[types.Prompt]:
        # A brief is a role's.
        if role is None:
            return []
        return [
            types.Prompt(
                name=BRIEF_PROMPT,
                description=(
                    f"Start the {role or 'lead'} role: its job, its tools, and the passages "
                    "from the procedure, lessons and case write-ups that bear on the task."
                ),
                arguments=[
                    types.PromptArgument(name=name, description=text, required=required)
                    for name, text, required in BRIEF_ARGUMENTS
                ],
            )
        ]

    @server.get_prompt()  # type: ignore[untyped-decorator, no-untyped-call]
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        if role is None or name != BRIEF_PROMPT:
            raise ValueError(f"no prompt {name!r}; the one prompt is {BRIEF_PROMPT!r}")
        return types.GetPromptResult(
            description=f"brief for the {role or 'lead'} role",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=brief_for(role, arguments)),
                )
            ],
        )

    @server.list_tools()  # type: ignore[untyped-decorator, no-untyped-call]
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=item.name,
                description=item.description,
                inputSchema=item.input_schema,
            )
            for item in (described(tool) for tool in router.manifest())
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        text, failed = answer(router, name, arguments)
        if failed:
            raise ToolError(text)
        return [types.TextContent(type="text", text=text)]

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
