from __future__ import annotations

import asyncio
import json
import os
from functools import partial
from typing import Any

from agents import Agent, FunctionTool, RunConfig, Runner, flush_traces
from dotenv import load_dotenv

from config import build_config_tools


ALLOWED_ARCADE_TOOLS = [
    "NotionToolkit_GetPageContentById",
    "NotionToolkit_GetPageContentByTitle",
    "NotionToolkit_SearchByTitle",
    "Linear_CreateIssue",
]

SYSTEM_PROMPT = """You are an Arcade-powered assistant running on the OpenAI Agents SDK.

Use the available Arcade tools when the user asks you to read from Notion or create Linear issues.
Always call load_config before any Notion or Linear tool call, then use those local defaults when they apply.
Use default_notion_doc_id or default_notion_doc_name when the user asks for a Notion page without specifying one.
When creating Linear issues, use default_linear_org as the team, default_assignee when the task has no assignee, and default_labels as labels.
Explicit user instructions override config.
Use load_config when the user asks to inspect current defaults.
Use update_config when the user asks to set or change config defaults.
Ask for missing IDs or required issue fields only when neither the user nor config provides them.
"""


class ToolError(Exception):
    pass


async def authorize_tool(client: Any, user_id: str, tool_name: str) -> None:
    result = await client.tools.authorize(tool_name=tool_name, user_id=user_id)
    if getattr(result, "status", None) == "completed":
        return

    url = getattr(result, "url", None)
    if url:
        print(f"{tool_name} requires authorization. Open this URL: {url}")
    await client.auth.wait_for_completion(result)


def tool_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Unexpected Arcade tool format: {type(value)!r}")


async def get_formatted_tool(client: Any, tool_name: str) -> dict[str, Any]:
    candidates = [tool_name]
    if "_" in tool_name:
        toolkit, name = tool_name.split("_", 1)
        candidates.append(f"{toolkit}.{name}")

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return tool_to_dict(await client.tools.formatted.get(name=candidate, format="openai"))
        except Exception as exc:
            last_error = exc
    raise ToolError(f"Could not load Arcade tool {tool_name}: {last_error}")


async def invoke_arcade_tool(
    context: Any,
    tool_args: str,
    *,
    client: Any,
    tool_name: str,
) -> str:
    user_id = context.context.get("user_id")
    if not user_id:
        raise ToolError("ARCADE_USER_ID is required")

    await authorize_tool(client, user_id, tool_name)
    result = await client.tools.execute(
        tool_name=tool_name,
        input=json.loads(tool_args),
        user_id=user_id,
    )
    if getattr(result, "success", True) is False:
        raise ToolError(f"{tool_name} failed: {result}")

    output = getattr(result, "output", None)
    value = output.value if output is not None and hasattr(output, "value") else result
    return json.dumps(value, indent=2, sort_keys=True, default=str)


async def build_tools(client: Any, allowed_tools: list[str]) -> list[Any]:
    tools = []

    for tool_name in allowed_tools:
        formatted_tool = await get_formatted_tool(client, tool_name)
        function = formatted_tool["function"]
        arcade_tool_name = function["name"]
        tools.append(
            FunctionTool(
                name=arcade_tool_name,
                description=function.get("description") or f"Arcade tool {arcade_tool_name}",
                params_json_schema=function["parameters"],
                on_invoke_tool=partial(
                    invoke_arcade_tool,
                    client=client,
                    tool_name=arcade_tool_name,
                ),
                strict_json_schema=False,
            )
        )

    return tools


async def build_agent() -> Any:
    from arcadepy import AsyncArcade

    arcade_client = AsyncArcade()
    tools = await build_tools(arcade_client, ALLOWED_ARCADE_TOOLS)
    tools.extend(build_config_tools())
    return Agent(
        name="Sync Action Items Agent",
        instructions=SYSTEM_PROMPT,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        tools=tools,
    )


async def chat_loop() -> int:
    agent = await build_agent()
    history: list[Any] = []
    user_id = os.getenv("ARCADE_USER_ID")

    print("Sync Action Items Agent")
    print("Type 'exit' to quit.")

    while True:
        try:
            prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if prompt.lower() in {"exit", "quit"}:
            return 0
        if not prompt:
            continue

        history.append({"role": "user", "content": prompt})
        result = await Runner.run(
            starting_agent=agent,
            input=history,
            context={"user_id": user_id},
            run_config=RunConfig(workflow_name="Sync Action Items Agent"),
        )
        flush_traces()
        history = result.to_input_list()
        print(f"Agent: {result.final_output}")


async def main_async() -> int:
    load_dotenv()
    missing = [
        name
        for name in ("OPENAI_API_KEY", "ARCADE_API_KEY", "ARCADE_USER_ID")
        if not os.getenv(name)
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        return 2

    return await chat_loop()


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
