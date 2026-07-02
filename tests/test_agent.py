import asyncio

import pytest

from agent import authorize_tool


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
