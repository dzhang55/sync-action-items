import asyncio
import json
from types import SimpleNamespace

import pytest

from agent import (
    SYSTEM_PROMPT,
    authorize_tool,
    chat_loop,
    ensure_linear_teammates,
    format_runtime_context,
    invoke_arcade_tool,
    parse_teammate_names,
    parse_args,
    reset_config_files,
    stream_agent_run,
)
from config import Config, load_linear_teammates


def test_parse_args_accepts_reset_config_flag() -> None:
    args = parse_args(["--reset-config"])

    assert args.reset_config is True


def test_reset_config_files_removes_existing_files_and_ignores_missing(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    teammates_path = tmp_path / "linear_teammates.json"
    missing_path = tmp_path / "missing.json"
    config_path.write_text("{}\n")
    teammates_path.write_text("{}\n")

    removed = reset_config_files((config_path, teammates_path, missing_path))

    assert removed == [config_path, teammates_path]
    assert not config_path.exists()
    assert not teammates_path.exists()


def test_parse_teammate_names_accepts_commas_and_newlines() -> None:
    assert parse_teammate_names("Daniel, John Doe\nPriya") == {
        "Daniel": [],
        "John Doe": [],
        "Priya": [],
    }


def test_ensure_linear_teammates_asks_and_saves_when_missing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    teammates = ensure_linear_teammates(
        {},
        input_fn=lambda _prompt: "Daniel, John Doe",
    )

    assert teammates == {"Daniel": [], "John Doe": []}
    assert load_linear_teammates() == {"Daniel": [], "John Doe": []}


def test_chat_loop_collects_linear_teammates_before_first_user_prompt(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARCADE_USER_ID", "eval-user")
    events = []

    async def fake_build_agent() -> object:
        events.append("build_agent")
        return object()

    def fake_input(prompt: str) -> str:
        events.append(f"input:{prompt}")
        if prompt == "Linear teammates: ":
            return "Daniel"
        if prompt == "You: ":
            return "exit"
        raise AssertionError(f"unexpected input prompt: {prompt}")

    monkeypatch.setattr("agent.build_agent", fake_build_agent)
    monkeypatch.setattr("builtins.input", fake_input)

    assert asyncio.run(chat_loop()) == 0
    assert events == [
        "input:Linear teammates: ",
        "build_agent",
        "input:You: ",
    ]
    assert load_linear_teammates() == {"Daniel": []}


def test_prompt_and_runtime_context_discourage_sync_config_reads() -> None:
    runtime_context = format_runtime_context(
        Config(default_notion_doc_id="page-123", default_linear_team="ENG"),
        {"Daniel": []},
    )

    assert "Do not call read_sync_defaults or load_linear_teammates just to start a sync" in SYSTEM_PROMPT
    assert "read that page id. Do not ask which page to use" in SYSTEM_PROMPT
    assert "Persist the defaults used for this sync immediately with save_sync_defaults" in SYSTEM_PROMPT
    assert "Never fall back to older Action items sections" in SYSTEM_PROMPT
    assert "instead of calling read_sync_defaults or load_linear_teammates" in runtime_context
    assert '"default_notion_doc_id": "page-123"' in runtime_context
    assert "read that page id without asking" in runtime_context


def test_ensure_linear_teammates_retries_until_name_is_provided(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    answers = iter(["", "Daniel"])
    messages = []

    teammates = ensure_linear_teammates(
        {},
        input_fn=lambda _prompt: next(answers),
        print_fn=messages.append,
    )

    assert teammates == {"Daniel": []}
    assert "Agent: Please enter at least one Linear teammate name." in messages
    assert load_linear_teammates() == {"Daniel": []}


def test_stream_agent_run_prints_text_deltas(monkeypatch, capsys) -> None:
    class FakeResult:
        final_output = "Done"

        async def stream_events(self):
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(type="response.output_text.delta", delta="Done"),
            )

    def fake_run_streamed(**kwargs):
        return FakeResult()

    monkeypatch.setattr("agent.Runner.run_streamed", fake_run_streamed)

    result = asyncio.run(
        stream_agent_run(
            agent=object(),
            run_input=[],
            context={"user_id": "eval-user"},
            run_config=SimpleNamespace(),
        )
    )

    assert result.final_output == "Done"
    assert capsys.readouterr().out == "Agent: Done\n"


class FakeAuthorizationResult:
    status = "pending"

    def __init__(self, url: str) -> None:
        self.url = url


class FakeAuth:
    def __init__(self, url: str) -> None:
        self.waited_for: FakeAuthorizationResult | None = None

    async def wait_for_completion(self, result: FakeAuthorizationResult) -> None:
        self.waited_for = result


class FakeTools:
    def __init__(self, url: str) -> None:
        self.url = url

    async def authorize(self, *, tool_name: str, user_id: str) -> FakeAuthorizationResult:
        return FakeAuthorizationResult(self.url)


class FakeArcadeClient:
    def __init__(self, url: str) -> None:
        self.tools = FakeTools(url)
        self.auth = FakeAuth(url)


@pytest.mark.parametrize(
    ("tool_name", "auth_url"),
    [
        ("NotionToolkit_GetPageContentById", "https://arcade.dev/auth/notion"),
        ("Linear_CreateIssue", "https://arcade.dev/auth/linear"),
    ],
)
def test_authorize_tool_prints_authorization_url_when_auth_is_required(
    tool_name: str,
    auth_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeArcadeClient(auth_url)

    asyncio.run(authorize_tool(client, user_id="eval-user", tool_name=tool_name))

    captured = capsys.readouterr()
    assert f"{tool_name} requires authorization. Open this URL: {auth_url}" in captured.out
    assert client.auth.waited_for is not None


class FakeExecutingTools:
    def __init__(self, result: object) -> None:
        self.result = result
        self.executed_with: dict[str, object] | None = None

    async def authorize(self, *, tool_name: str, user_id: str) -> SimpleNamespace:
        return SimpleNamespace(status="completed")

    async def execute(
        self,
        *,
        tool_name: str,
        input: dict[str, object],
        user_id: str,
    ) -> object:
        self.executed_with = {
            "tool_name": tool_name,
            "input": input,
            "user_id": user_id,
        }
        return self.result


class FakeExecutingArcadeClient:
    def __init__(self, result: object) -> None:
        self.tools = FakeExecutingTools(result)


def arcade_result(value: object, *, success: bool = True) -> SimpleNamespace:
    return SimpleNamespace(success=success, output=SimpleNamespace(value=value))


def test_invoke_arcade_tool_returns_error_when_linear_create_returns_null() -> None:
    client = FakeExecutingArcadeClient(arcade_result(None))
    context = SimpleNamespace(context={"user_id": "eval-user"})

    output = json.loads(
        asyncio.run(
            invoke_arcade_tool(
                context,
                '{"title": "Ship onboarding polish"}',
                client=client,
                tool_name="Linear_CreateIssue",
            )
        )
    )

    assert output == {
        "tool_name": "Linear_CreateIssue",
        "error": "Linear_CreateIssue returned null output",
    }


def test_invoke_arcade_tool_accepts_linear_issue_url() -> None:
    client = FakeExecutingArcadeClient(
        arcade_result(
            {
                "created": True,
                "issue": {
                    "identifier": "ENG-1",
                    "url": "https://linear.app/acme/issue/ENG-1",
                }
            }
        )
    )
    context = SimpleNamespace(context={"user_id": "eval-user"})

    output = asyncio.run(
        invoke_arcade_tool(
            context,
            '{"title": "Ship onboarding polish"}',
            client=client,
            tool_name="Linear_CreateIssue",
        )
    )

    assert "https://linear.app/acme/issue/ENG-1" in output


def test_invoke_arcade_tool_accepts_exact_linear_teammate_key() -> None:
    client = FakeExecutingArcadeClient(
        arcade_result(
            {
                "created": True,
                "issue": {
                    "identifier": "ENG-1",
                    "url": "https://linear.app/acme/issue/ENG-1",
                },
            }
        )
    )
    context = SimpleNamespace(
        context={
            "user_id": "eval-user",
            "linear_teammates": {"js95": ["Jane"], "John Doe": []},
        }
    )

    output = asyncio.run(
        invoke_arcade_tool(
            context,
            '{"title": "Fix Sentry bug", "assignee": "js95"}',
            client=client,
            tool_name="Linear_CreateIssue",
        )
    )

    assert "https://linear.app/acme/issue/ENG-1" in output
    assert client.tools.executed_with is not None
    assert client.tools.executed_with["input"] == {
        "title": "Fix Sentry bug",
        "assignee": "js95",
    }


def test_invoke_arcade_tool_rejects_linear_assignee_that_is_not_exact_key() -> None:
    client = FakeExecutingArcadeClient(
        arcade_result(
            {
                "created": True,
                "issue": {
                    "identifier": "ENG-1",
                    "url": "https://linear.app/acme/issue/ENG-1",
                },
            }
        )
    )
    context = SimpleNamespace(
        context={
            "user_id": "eval-user",
            "linear_teammates": {"js95": ["Jane"], "John Doe": []},
        }
    )

    output = json.loads(
        asyncio.run(
            invoke_arcade_tool(
                context,
                '{"title": "Fix Sentry bug", "assignee": "Jane"}',
                client=client,
                tool_name="Linear_CreateIssue",
            )
        )
    )

    assert output == {
        "tool_name": "Linear_CreateIssue",
        "error": (
            "Linear_CreateIssue assignee must be an exact linear_teammates key. "
            "Got 'Jane'. Known keys: John Doe, js95. "
            "Resolve the assignee from the preloaded linear_teammates map, then retry "
            "Linear_CreateIssue once with assignee set to the exact matching key."
        ),
    }
    assert client.tools.executed_with is None
