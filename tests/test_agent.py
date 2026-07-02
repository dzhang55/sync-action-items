import asyncio
import json
from types import SimpleNamespace

import pytest

from agent import authorize_tool, invoke_arcade_tool


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
