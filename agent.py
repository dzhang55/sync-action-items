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

SYSTEM_PROMPT = """You sync action items from Notion planning docs into Linear issues.


# Workflow

When the user asks to sync Notion tasks into Linear:

1. Call load_config exactly once before the first Notion or Linear tool call for this user request.
2. Decide which Notion page to read:
   - If the user names a Notion page, normalize the page title from the request, search Notion for that title, and read the selected page by id.
   - If the user does not name a page, use default_notion_doc_id when configured.
   - If the user does not name a page and no default_notion_doc_id is configured, use default_notion_doc_name when configured.
   - If no defaults are configured and the user does not name a page, ask the user which page they'd like to sync.
   - If searching for the page does not yield a good match, tell the user the pages you found and ask them which one they'd like to sync.
3. Decide which Linear team to use:
   - If the user names a Linear team destination, use that team.
   - If the user does not mention a Linear destination use default_linear_org.
   - If the user does not name a Linear destination and default_linear_org is not set, ask the user which org they'd like to set.
4. Find the latest/current "Action items" section in the Notion page content.
5. Create Linear issues for every "-" bullet in that Action items section.
6. Do not create issues from bullets outside the latest/current Action items section.
7. Skip Action items bullets that already contain a Linear issue URL.
8. For each synced Action items bullet:
   - Derive the issue title from the bullet text after removing assignee mentions and Linear URLs.
   - If the line mentions an assignee, such as an email address or @handle, assign the issue to that person.
   - If the line has no assignee mention, use default_assignee when configured; otherwise leave the issue unassigned.
9. If any defaults were not set, set them to what was used in this user request. Do not override existing values.
10. Only count a Linear issue as synced after Linear_CreateIssue returns a non-null result with a Linear issue URL.
11. If Linear_CreateIssue fails, returns null, or returns no issue URL, tell the user the sync failed for that item. Do not say that item was synced.
12. If any tool returns JSON with an "error" field, tell the user that error instead of treating the tool call as successful.
13. Reply to the user with a concise summary of the synced issues using this format:

I synced the action items from [notion_page_name] to [linear_team_name]:

- [Task 1 title]: [description] ([Linear issue URL])
  - Assignee: [assignee or Unassigned]

- [Task 2 title]: [description] ([Linear issue URL])
  - Assignee: [assignee or Unassigned]

If no issues were created, say that no Action items bullets needed syncing from [notion_page_name] to [linear_team_name].
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


def linear_issue_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    issue = value.get("issue")
    if not isinstance(issue, dict):
        return None
    url = issue.get("url")
    return url if isinstance(url, str) and url else None


def validate_tool_output(tool_name: str, value: Any) -> None:
    if value is None:
        raise ToolError(f"{tool_name} returned null output")

    if tool_name == "Linear_CreateIssue" and not linear_issue_url(value):
        raise ToolError(f"{tool_name} returned no Linear issue URL: {value!r}")


def format_tool_error(tool_name: str, error: ToolError) -> str:
    return json.dumps(
        {
            "tool_name": tool_name,
            "error": str(error),
        },
        indent=2,
        sort_keys=True,
    )


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
    try:
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
        validate_tool_output(tool_name, value)
        return json.dumps(value, indent=2, sort_keys=True, default=str)
    except ToolError as exc:
        return format_tool_error(tool_name, exc)


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
