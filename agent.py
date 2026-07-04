from __future__ import annotations

import asyncio
import argparse
import json
import os
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from agents import Agent, FunctionTool, RunConfig, Runner, flush_traces
from dotenv import load_dotenv

from config import (
    CONFIG_PATH,
    LINEAR_TEAMMATES_PATH,
    Config,
    LinearTeammates,
    build_config_tools,
    load_config,
    load_linear_teammates,
    save_linear_teammates,
)


ALLOWED_ARCADE_TOOLS = [
    "NotionToolkit_GetPageContentById",
    "NotionToolkit_GetPageContentByTitle",
    "NotionToolkit_SearchByTitle",
    "Linear_CreateIssue",
]

SYSTEM_PROMPT = """You sync action items from Notion planning docs into Linear issues.


# Workflow

When the user asks to sync Notion tasks into Linear:

1. Use the preloaded runtime context as the authoritative source for the saved defaults and Linear teammate map. Do not call read_sync_defaults or load_linear_teammates just to start a sync; those read tools are only for explicit user requests to inspect saved state or if runtime context is unavailable.
2. Decide which Notion page to read:
   - If the user names a Notion page or describes a planning doc by title, normalize the page title from the request, search Notion for that title, and read the selected page by id.
   - Treat phrases like "sync my weekly planning" or "sync weekly planning" as naming a Notion page titled "Weekly Planning". Drop possessive/filler words like "my", "our", and "the" from the title before searching. Do not ask which page to use before searching for the named page.
   - Do not treat generic words like "notion", "tasks", or "action items" alone as a page title.
   - If the user does not name a page and default_notion_doc_id is configured in runtime context, read that page id. Do not ask which page to use. Don't search by default_notion_doc_name, but use it instead of doc_id when referencing the doc to the user.
   - If no defaults are configured and the user does not name a page, ask the user which page they'd like to sync.
   - If searching for the page does not yield a good match, tell the user the pages you found and ask them which one they'd like to sync.
3. Decide which Linear team to use:
   - A Linear team is required before creating any Linear issue. If neither the user request nor default_linear_team provides one, ask for the Linear team before calling Linear_CreateIssue.
   - If the user names a Linear team destination, use that team.
   - If the user does not mention a Linear destination use default_linear_team.
   - If the user does not name a Linear destination and default_linear_team is not set, ask the user which Linear team should be saved as the default.
4. Persist the defaults used for this sync immediately with save_sync_defaults. This is required bookkeeping, not optional.
   - If the Notion page was selected from search results, set default_notion_doc_name and default_notion_doc_id from the selected result's title and id.
   - If the Linear team was resolved from the user request or used for this sync, set default_linear_team.
   - Provided fields replace previously saved defaults.
   - If you asked the user for a missing Notion page or Linear team, their answer is not just for this run. Treat it as the new default unless they explicitly say "just this time".
5. Find the most recent top-level planning section in the Notion page content, then use only the "Action items" subsection inside that latest section:
   - Dated sections may be in ascending or descending order, but only select the one with the most recent date.
   - Never fall back to older Action items sections.
   - Create Linear issues for every "-" bullet in that most recent Action items subsection.
      - If the most recent Action items subsection has no "-" bullets, create no issues and say no Action items needed syncing.
   - Do not create issues from bullets outside the most recent Action items section.
   - Skip Action items bullets that already contain a Linear issue URL.
6. For each synced Action items bullet:
   - Derive the issue title from the bullet text after removing assignee mentions and Linear URLs.
   - If the line mentions an assignee, assign the issue to that person. Notion assignee mentions are plain person names in an owner prefix like "Bob to fix Sentry error", "Alice: fix Sentry error", or "Charles - fix Sentry error".
   - Resolve explicit assignee text against the preloaded linear_teammates before creating the issue. Match case-insensitively against canonical teammate names and stored nicknames. Exact matches win. Unambiguous first-name or fuzzy prefix matches are allowed, such as "Jane" matching "Jane Smith" or "sam" matching "Samuel".
     - If the assignee text is ambiguous, ask the user which configured teammate was meant before creating the issue.
     - If the assignee text does not match any configured teammate, ask in this style: "The names I know are A, B, and C. Which teammate goes by [name]?"
     - The user's reply selects the canonical linear_teammates key; the original assignee text becomes the nickname. If the reply exactly matches a configured key, append the original text to that key's nickname list, call update_linear_teammates, then create the issue using that canonical key as assignee. Example: known {"js95": [], "John Doe": []}, bullet "Jane to fix Sentry error", user replies "js95" -> update {"js95": ["Jane"], "John Doe": []}, create issue assigned to "js95".
     - Never call Linear_CreateIssue for an item with an unresolved assignee until after any needed update_linear_teammates call succeeds.
   - For owner-prefix bullets, pass only the exact canonical linear_teammates key as the Linear assignee. For example, with linear_teammates {"Robert Smith": ["Bob"]}, "- Bob to fix Sentry error" should create a title like "Fix Sentry error" with assignee "Robert Smith".
   - If the line has no assignee mention, use default_assignee when configured; otherwise leave the issue unassigned.
7. When writing default_assignee from user-provided text, resolve it to either @me or a canonical linear_teammates key first.
8. Only count a Linear issue as synced after Linear_CreateIssue returns a non-null result with a Linear issue URL.
   - If Linear_CreateIssue fails, returns null, or returns no issue URL, tell the user the sync failed for that item. Do not say that item was synced.
10. If any tool returns JSON with an "error" field, do not treat the tool call as successful.
   - If the error is a tool argument validation error and the message or runtime context gives enough information to correct the arguments, retry the tool call once with corrected arguments before telling the user.
   - If the error cannot be corrected safely, tell the user that error.
11. Reply to the user with a concise summary of the synced issues using this format:

I synced the action items from [notion_page_name] to [linear_team_name]:

- [Task 1 title]: [description] ([Linear issue URL])
  - Assignee: [assignee or Unassigned]

- [Task 2 title]: [description] ([Linear issue URL])
  - Assignee: [assignee or Unassigned]

If no issues were created, say that no Action items bullets needed syncing from [notion_page_name] to [linear_team_name].
"""


class ToolError(Exception):
    pass


ArcadeToolArgValidator = Callable[[dict[str, Any], Any], None]


def parse_teammate_names(value: str) -> LinearTeammates:
    return {name.strip(): [] for name in re.split(r"[\n,]+", value) if name.strip()}


def format_runtime_context(config: Config, linear_teammates: LinearTeammates) -> str:
    config_dict = config.to_dict()
    return (
        "Runtime context preloaded by the Python app before this run. "
        "This context is authoritative for sync requests; use it instead of calling read_sync_defaults or "
        "load_linear_teammates.\n\n"
        "If default_notion_doc_id is configured and the user did not name a page, read that page id without asking.\n"
        "If default_linear_team is configured and the user did not name a team, use that team without asking.\n\n"
        "Current local sync defaults JSON:\n"
        f"{json.dumps(config_dict, sort_keys=True)}\n\n"
        "Known Linear teammates JSON:\n"
        f"{json.dumps(linear_teammates, sort_keys=True)}"
    )


def with_runtime_context(
    history: list[Any],
    config: Config,
    linear_teammates: LinearTeammates,
) -> list[Any]:
    return [
        {
            "role": "developer",
            "content": format_runtime_context(config, linear_teammates),
        },
        *history,
    ]


def run_item_name(event: Any) -> str | None:
    name = getattr(event, "name", None)
    if isinstance(name, str):
        return name
    item = getattr(event, "item", None)
    return getattr(item, "type", None)


def run_item_tool_name(event: Any) -> str | None:
    item = getattr(event, "item", None)
    raw_item = getattr(item, "raw_item", None)
    for candidate in (item, raw_item):
        if candidate is None:
            continue
        name = getattr(candidate, "name", None)
        if isinstance(name, str):
            return name
        if isinstance(candidate, dict):
            name = candidate.get("name")
            if isinstance(name, str):
                return name
    return None


def progress_for_tool(tool_name: str | None, *, completed: bool = False) -> str | None:
    if not tool_name:
        return None
    action = "Finished" if completed else "Calling"
    if "SearchByTitle" in tool_name:
        return f"{action} Notion search..."
    if "GetPageContent" in tool_name:
        return f"{action} Notion page read..."
    if "Linear_CreateIssue" in tool_name:
        return f"{action} Linear issue creation..."
    if tool_name == "update_linear_teammates" or tool_name == "save_sync_defaults":
        return f"{action} local state update..."
    return f"{action} {tool_name}..."


def text_delta_from_event(event: Any) -> str | None:
    data = getattr(event, "data", None)
    if getattr(data, "type", None) == "response.output_text.delta":
        delta = getattr(data, "delta", None)
        return delta if isinstance(delta, str) else None
    return None


async def stream_agent_run(
    agent: Any,
    run_input: list[Any],
    *,
    context: dict[str, Any],
    run_config: RunConfig,
) -> Any:
    result = Runner.run_streamed(
        starting_agent=agent,
        input=run_input,
        context=context,
        run_config=run_config,
    )
    printed_text = False
    async for event in result.stream_events():
        delta = text_delta_from_event(event)
        if delta:
            if not printed_text:
                print("Agent: ", end="", flush=True)
                printed_text = True
            print(delta, end="", flush=True)
            continue

        if getattr(event, "type", None) != "run_item_stream_event":
            continue

        name = run_item_name(event)
        if name == "tool_called":
            message = progress_for_tool(run_item_tool_name(event))
            if message:
                print(f"\n{message}", flush=True)
        elif name == "tool_output":
            message = progress_for_tool(run_item_tool_name(event), completed=True)
            if message:
                print(f"{message}", flush=True)

    if printed_text:
        print()
    return result


def ensure_linear_teammates(
    linear_teammates: LinearTeammates,
    *,
    input_fn: Any | None = None,
    print_fn: Any | None = None,
) -> LinearTeammates:
    input_fn = input if input_fn is None else input_fn
    print_fn = print if print_fn is None else print_fn

    if not linear_teammates:
        print_fn(
            "Agent: I need your Linear teammate names from /members before syncing. "
            "Paste teammate names separated by commas."
        )
        while not linear_teammates:
            linear_teammates = parse_teammate_names(input_fn("Linear teammates: "))
            if not linear_teammates:
                print_fn("Agent: Please enter at least one Linear teammate name.")
        save_linear_teammates(linear_teammates)

    return linear_teammates


def reset_config_files(
    paths: tuple[Path, ...] = (CONFIG_PATH, LINEAR_TEAMMATES_PATH),
) -> list[Path]:
    removed = []
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    return removed


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


def tool_runtime_context(context: Any) -> dict[str, Any]:
    if isinstance(context, dict):
        return context
    raw_context = getattr(context, "context", None)
    return raw_context if isinstance(raw_context, dict) else {}


def validate_linear_assignee(args: dict[str, Any], context: Any) -> None:
    assignee = args.get("assignee")
    if assignee in (None, ""):
        return
    if assignee == "@me":
        return
    if not isinstance(assignee, str):
        raise ToolError("Linear_CreateIssue assignee must be a string, null, or omitted.")

    linear_teammates = tool_runtime_context(context).get("linear_teammates")
    if not isinstance(linear_teammates, dict):
        raise ToolError(
            "Linear_CreateIssue assignee validation requires linear_teammates in runtime context."
        )
    if assignee not in linear_teammates:
        known = ", ".join(sorted(str(name) for name in linear_teammates)) or "none"
        raise ToolError(
            "Linear_CreateIssue assignee must be an exact linear_teammates key. "
            f"Got {assignee!r}. Known keys: {known}. "
            "Resolve the assignee from the preloaded linear_teammates map, then retry "
            "Linear_CreateIssue once with assignee set to the exact matching key."
        )


ARCADE_TOOL_ARG_VALIDATORS: dict[str, ArcadeToolArgValidator] = {
    "Linear_CreateIssue": validate_linear_assignee,
}


def validate_arcade_tool_args(tool_name: str, args: Any, context: Any) -> None:
    validator = ARCADE_TOOL_ARG_VALIDATORS.get(tool_name)
    if validator is None:
        return
    if not isinstance(args, dict):
        raise ToolError(f"{tool_name} arguments must be a JSON object.")
    validator(args, context)


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

        parsed_tool_args = json.loads(tool_args)
        validate_arcade_tool_args(tool_name, parsed_tool_args, context)
        await authorize_tool(client, user_id, tool_name)
        result = await client.tools.execute(
            tool_name=tool_name,
            input=parsed_tool_args,
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
    history: list[Any] = []
    user_id = os.getenv("ARCADE_USER_ID")

    print("Sync Action Items Agent")
    print("Type 'exit' to quit.")
    ensure_linear_teammates(load_linear_teammates(LINEAR_TEAMMATES_PATH))

    agent = await build_agent()

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

        config = load_config(CONFIG_PATH)
        linear_teammates = load_linear_teammates(LINEAR_TEAMMATES_PATH)

        history.append({"role": "user", "content": prompt})
        result = await stream_agent_run(
            agent=agent,
            run_input=with_runtime_context(history, config, linear_teammates),
            context={
                "user_id": user_id,
                "config": config.to_dict(),
                "linear_teammates": linear_teammates,
            },
            run_config=RunConfig(workflow_name="Sync Action Items Agent"),
        )
        flush_traces()
        history = [
            item
            for item in result.to_input_list()
            if not (isinstance(item, dict) and item.get("role") == "developer")
        ]
        if not result.final_output:
            print("Agent: I could not produce a final response.")


async def main_async(*, reset_config: bool = False) -> int:
    load_dotenv()
    if reset_config:
        removed = reset_config_files()
        if removed:
            print(f"Removed config files: {', '.join(str(path) for path in removed)}")
        else:
            print("No config files to remove.")

    missing = [
        name
        for name in ("OPENAI_API_KEY", "ARCADE_API_KEY", "ARCADE_USER_ID")
        if not os.getenv(name)
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        return 2

    return await chat_loop()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sync Action Items Agent.")
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Remove config.json and linear_teammates.json before starting the agent.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(main_async(reset_config=args.reset_config))


if __name__ == "__main__":
    raise SystemExit(main())
