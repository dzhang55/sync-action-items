"""Live LLM eval runner for the sync action-items agent.

How to run:
    uv run python -m evals.runner

Required:
    OPENAI_API_KEY must be set in the environment or in .env.

Optional:
    OPENAI_MODEL=gpt-5-nano
    AGENT_EVAL_TIMEOUT_SECONDS=45
    AGENT_EVAL_CONCURRENCY=10

The runner prints a short score summary, writes an HTML table report, and exits
with status 1 if any eval case fails. These evals call the OpenAI API, so they
are intentionally separate from the deterministic pytest suite.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    FunctionTool,
    RunConfig,
    Runner,
    flush_traces,
    function_tool,
    gen_trace_id,
)
from dotenv import load_dotenv

from agent import SYSTEM_PROMPT
from config import (
    READ_CONFIG_SCHEMA,
    READ_LINEAR_TEAMMATES_SCHEMA,
    UPDATE_CONFIG_SCHEMA,
    UPDATE_LINEAR_TEAMMATES_SCHEMA,
    Config,
    LinearTeammates,
)
from evals.cases import EVAL_CASES, EvalCase


load_dotenv()

DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_EVAL_TIMEOUT_SECONDS = 120
DEFAULT_EVAL_CONCURRENCY = 10
DEFAULT_EVAL_REPORT_DIR = Path("evals/reports")
OPENAI_TRACE_LOG_URL = "https://platform.openai.com/logs/trace"


def openai_model_from_env() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL


def eval_timeout_seconds() -> float:
    return float(os.getenv("AGENT_EVAL_TIMEOUT_SECONDS") or DEFAULT_EVAL_TIMEOUT_SECONDS)


def eval_concurrency() -> int:
    return int(os.getenv("AGENT_EVAL_CONCURRENCY") or DEFAULT_EVAL_CONCURRENCY)


def eval_report_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_EVAL_REPORT_DIR / f"agent-eval-{timestamp}.html"


def trace_url(trace_id: str) -> str:
    return f"{OPENAI_TRACE_LOG_URL}?trace_id={trace_id}"


def case_insensitive_lookup(mapping: dict[str, Any], key: str, default: Any) -> Any:
    if key in mapping:
        return mapping[key]

    normalized_key = key.casefold()
    for candidate_key, value in mapping.items():
        if candidate_key.casefold() == normalized_key:
            return value
    return default


@dataclass(frozen=True)
class EvalResult:
    case: EvalCase
    passed: bool
    load_config_calls: int
    load_linear_teammates_calls: int
    search_calls: int
    create_calls: int
    notes: list[str]
    trace_url: str | None = None


class MockArcadeTools:
    def __init__(
        self,
        *,
        markdown_by_page_id: dict[str, str],
        markdown_by_title: dict[str, str],
        search_results_by_title: dict[str, list[dict[str, str]]],
    ) -> None:
        self.markdown_by_page_id = markdown_by_page_id
        self.markdown_by_title = markdown_by_title
        self.search_results_by_title = search_results_by_title
        self.notion_calls: list[dict[str, Any]] = []
        self.linear_create_issue_calls: list[dict[str, Any]] = []

    def tools(self) -> list[Any]:
        @function_tool(name_override="NotionToolkit_GetPageContentById")
        def get_page_content_by_id(page_id: str) -> str:
            """Read a Notion page by page id."""
            self.notion_calls.append({"page_id": page_id})
            return self.markdown_by_page_id.get(page_id, "")

        @function_tool(name_override="NotionToolkit_GetPageContentByTitle")
        def get_page_content_by_title(title: str) -> str:
            """Read a Notion page by title."""
            self.notion_calls.append({"title": title})
            return case_insensitive_lookup(self.markdown_by_title, title, "")

        @function_tool(name_override="NotionToolkit_SearchByTitle")
        def search_by_title(title: str) -> list[dict[str, str]]:
            """Search Notion pages by title."""
            self.notion_calls.append({"search_title": title})
            return case_insensitive_lookup(self.search_results_by_title, title, [])

        @function_tool(name_override="Linear_CreateIssue")
        def create_issue(
            title: str,
            team: str,
            assignee: str | None = None,
            description: str | None = None,
        ) -> dict[str, str]:
            """Create a Linear issue."""
            self.linear_create_issue_calls.append(
                {
                    "title": title,
                    "team": team,
                    "assignee": assignee,
                    "description": description,
                }
            )
            number = len(self.linear_create_issue_calls)
            return {
                "identifier": f"ENG-{number}",
                "url": f"https://linear.app/acme/issue/ENG-{number}",
            }

        return [get_page_content_by_id, get_page_content_by_title, search_by_title, create_issue]

    @property
    def search_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.notion_calls if "search_title" in call]

    @property
    def page_read_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.notion_calls if "search_title" not in call]


class MockConfigTools:
    def __init__(self, config: Config, linear_teammates: LinearTeammates) -> None:
        self.current_config = config
        self.current_linear_teammates = dict(linear_teammates)
        self.load_config_calls: list[dict[str, Any]] = []
        self.load_linear_teammates_calls: list[dict[str, Any]] = []

    async def load_config(self, context: Any, tool_args: str) -> str:
        self.load_config_calls.append(json.loads(tool_args or "{}"))
        return json.dumps(self.current_config.to_dict(), indent=2, sort_keys=True)

    async def update_config(self, context: Any, tool_args: str) -> str:
        args = json.loads(tool_args or "{}")
        self.current_config = Config.from_dict({**self.current_config.to_dict(), **args})
        return json.dumps(self.current_config.to_dict(), indent=2, sort_keys=True)

    async def load_linear_teammates(self, context: Any, tool_args: str) -> str:
        self.load_linear_teammates_calls.append(json.loads(tool_args or "{}"))
        return json.dumps(
            {"linear_teammates": self.current_linear_teammates},
            indent=2,
            sort_keys=True,
        )

    async def update_linear_teammates(self, context: Any, tool_args: str) -> str:
        args = json.loads(tool_args or "{}")
        self.current_linear_teammates = args["linear_teammates"]
        return json.dumps(
            {"linear_teammates": self.current_linear_teammates},
            indent=2,
            sort_keys=True,
        )

    def tools(self) -> list[Any]:
        return [
            FunctionTool(
                name="load_config",
                description="Read local defaults for the Notion doc and Linear issue creation.",
                params_json_schema=READ_CONFIG_SCHEMA,
                on_invoke_tool=self.load_config,
                strict_json_schema=False,
            ),
            FunctionTool(
                name="update_config",
                description="Update local defaults for the Notion doc and Linear issue creation.",
                params_json_schema=UPDATE_CONFIG_SCHEMA,
                on_invoke_tool=self.update_config,
                strict_json_schema=False,
            ),
            FunctionTool(
                name="load_linear_teammates",
                description="Read the Linear teammate name and nickname map.",
                params_json_schema=READ_LINEAR_TEAMMATES_SCHEMA,
                on_invoke_tool=self.load_linear_teammates,
                strict_json_schema=False,
            ),
            FunctionTool(
                name="update_linear_teammates",
                description="Replace the Linear teammate name and nickname map.",
                params_json_schema=UPDATE_LINEAR_TEAMMATES_SCHEMA,
                on_invoke_tool=self.update_linear_teammates,
                strict_json_schema=False,
            ),
        ]


async def run_live_agent_eval(
    case: EvalCase,
    *,
    trace_id: str,
) -> tuple[MockArcadeTools, MockConfigTools]:
    arcade = MockArcadeTools(
        markdown_by_page_id=case.markdown_by_page_id,
        markdown_by_title=case.markdown_by_title,
        search_results_by_title=case.search_results_by_title,
    )
    config = MockConfigTools(case.config, case.linear_teammates)
    agent = Agent(
        name="Sync Action Items Agent Eval",
        instructions=SYSTEM_PROMPT,
        model=openai_model_from_env(),
        tools=[*arcade.tools(), *config.tools()],
    )
    result = await asyncio.wait_for(
        Runner.run(
            agent,
            case.prompt,
            max_turns=12,
            run_config=RunConfig(
                workflow_name="Sync Action Items Agent Eval",
                trace_id=trace_id,
                trace_metadata={"eval": case.name},
            ),
        ),
        timeout=eval_timeout_seconds(),
    )
    for follow_up in case.follow_up_inputs:
        result = await asyncio.wait_for(
            Runner.run(
                agent,
                [*result.to_input_list(), {"role": "user", "content": follow_up}],
                max_turns=12,
                run_config=RunConfig(
                    workflow_name="Sync Action Items Agent Eval",
                    trace_id=trace_id,
                    trace_metadata={"eval": case.name},
                ),
            ),
            timeout=eval_timeout_seconds(),
        )
    flush_traces()
    return arcade, config


def evaluate_case_result(
    case: EvalCase,
    arcade: MockArcadeTools,
    config: MockConfigTools,
    *,
    trace_url: str | None = None,
) -> EvalResult:
    notes = []
    titles = [call["title"] for call in arcade.linear_create_issue_calls]
    teams = [call["team"] for call in arcade.linear_create_issue_calls]
    assignees = [call["assignee"] for call in arcade.linear_create_issue_calls]

    if len(config.load_config_calls) != case.expected_load_config_calls:
        notes.append(
            f"load_config {len(config.load_config_calls)} != {case.expected_load_config_calls}"
        )
    if len(config.load_linear_teammates_calls) != case.expected_load_config_calls:
        notes.append(
            "load_linear_teammates "
            f"{len(config.load_linear_teammates_calls)} != {case.expected_load_config_calls}"
        )
    if len(arcade.search_calls) != case.expected_search_calls:
        notes.append(f"search {len(arcade.search_calls)} != {case.expected_search_calls}")
    if len(arcade.linear_create_issue_calls) != case.expected_create_calls:
        notes.append(
            f"create {len(arcade.linear_create_issue_calls)} != {case.expected_create_calls}"
        )
    if titles != case.expected_created_titles:
        notes.append(f"titles {titles!r} != {case.expected_created_titles!r}")
    if case.expected_created_teams and teams != case.expected_created_teams:
        notes.append(f"teams {teams!r} != {case.expected_created_teams!r}")
    if case.expected_created_assignees and assignees != case.expected_created_assignees:
        notes.append(f"assignees {assignees!r} != {case.expected_created_assignees!r}")
    if case.expected_notion_call and case.expected_notion_call not in arcade.page_read_calls:
        notes.append(f"missing notion read {case.expected_notion_call!r}")
    if (
        case.expected_final_linear_teammates is not None
        and config.current_linear_teammates != case.expected_final_linear_teammates
    ):
        notes.append(
            "linear_teammates "
            f"{config.current_linear_teammates!r} != {case.expected_final_linear_teammates!r}"
        )

    return EvalResult(
        case=case,
        passed=not notes,
        load_config_calls=len(config.load_config_calls),
        load_linear_teammates_calls=len(config.load_linear_teammates_calls),
        search_calls=len(arcade.search_calls),
        create_calls=len(arcade.linear_create_issue_calls),
        notes=notes,
        trace_url=trace_url,
    )


@dataclass(frozen=True)
class EvalSummary:
    cases_passed: int
    cases_total: int
    actual_loads: int
    expected_loads: int
    actual_teammate_loads: int
    actual_searches: int
    expected_searches: int
    actual_creates: int
    expected_creates: int


def summarize_results(results: list[EvalResult]) -> EvalSummary:
    return EvalSummary(
        cases_passed=sum(result.passed for result in results),
        cases_total=len(results),
        actual_loads=sum(result.load_config_calls for result in results),
        expected_loads=sum(result.case.expected_load_config_calls for result in results),
        actual_teammate_loads=sum(result.load_linear_teammates_calls for result in results),
        actual_searches=sum(result.search_calls for result in results),
        expected_searches=sum(result.case.expected_search_calls for result in results),
        actual_creates=sum(result.create_calls for result in results),
        expected_creates=sum(result.case.expected_create_calls for result in results),
    )


def format_eval_report(results: list[EvalResult]) -> str:
    summary = summarize_results(results)
    lines = [
        "",
        "Agent eval score",
        f"cases passed: {summary.cases_passed}/{summary.cases_total}",
        f"load_config calls: {summary.actual_loads}/{summary.expected_loads}",
        f"load_linear_teammates calls: {summary.actual_teammate_loads}/{summary.expected_loads}",
        f"notion searches: {summary.actual_searches}/{summary.expected_searches}",
        f"linear issues created: {summary.actual_creates}/{summary.expected_creates}",
    ]
    return "\n".join(lines)


def format_notes(notes: list[str]) -> str:
    return "; ".join(notes) if notes else "-"


def score_cell(actual: int, expected: int) -> str:
    return f"{actual}/{expected}"


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_case_html(result: EvalResult) -> str:
    case_name = html_escape(result.case.name)
    if not result.trace_url:
        return case_name
    return (
        f'<a href="{html_escape(result.trace_url)}" target="_blank" '
        f'rel="noopener noreferrer">{case_name}</a>'
    )


def format_eval_html_report(results: list[EvalResult]) -> str:
    summary = summarize_results(results)
    rows = []
    for result in results:
        status_class = "pass" if result.passed else "fail"
        status_text = "PASS" if result.passed else "FAIL"
        rows.append(
            f"""
            <tr>
              <td class="case">{format_case_html(result)}</td>
              <td><span class="badge {status_class}">{status_text}</span></td>
              <td>{html_escape(score_cell(result.load_config_calls, result.case.expected_load_config_calls))}</td>
              <td>{html_escape(score_cell(result.load_linear_teammates_calls, result.case.expected_load_config_calls))}</td>
              <td>{html_escape(score_cell(result.search_calls, result.case.expected_search_calls))}</td>
              <td>{html_escape(score_cell(result.create_calls, result.case.expected_create_calls))}</td>
              <td class="notes">{html_escape(format_notes(result.notes))}</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Agent Eval Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #20242a;
      --muted: #68707c;
      --line: #d9dee7;
      --pass-bg: #e8f6ee;
      --pass: #14743d;
      --fail-bg: #fdecec;
      --fail: #b42318;
      --accent: #355caa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      font-weight: 700;
    }}
    .meta {{
      margin: 0 0 24px;
      color: var(--muted);
      font-size: 14px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 24px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      background: #eef1f6;
      color: #3b4350;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td:not(.case):not(.notes) {{
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    .case {{
      width: 28%;
      font-weight: 600;
    }}
    .case a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .case a:hover {{
      text-decoration: underline;
    }}
    .notes {{
      width: 34%;
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    .badge {{
      display: inline-block;
      min-width: 54px;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      text-align: center;
    }}
    .badge.pass {{
      background: var(--pass-bg);
      color: var(--pass);
    }}
    .badge.fail {{
      background: var(--fail-bg);
      color: var(--fail);
    }}
    @media (max-width: 760px) {{
      main {{ padding: 24px 14px; }}
      .summary {{ grid-template-columns: 1fr 1fr; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Agent Eval Report</h1>
    <p class="meta">Model: {html_escape(openai_model_from_env())}</p>
    <section class="summary" aria-label="Eval score summary">
      <div class="metric"><span>Cases Passed</span><strong>{summary.cases_passed}/{summary.cases_total}</strong></div>
      <div class="metric"><span>load_config Calls</span><strong>{summary.actual_loads}/{summary.expected_loads}</strong></div>
      <div class="metric"><span>Teammate Loads</span><strong>{summary.actual_teammate_loads}/{summary.expected_loads}</strong></div>
      <div class="metric"><span>Notion Searches</span><strong>{summary.actual_searches}/{summary.expected_searches}</strong></div>
      <div class="metric"><span>Linear Issues Created</span><strong>{summary.actual_creates}/{summary.expected_creates}</strong></div>
    </section>
    <table>
      <thead>
        <tr>
          <th>Case</th>
          <th>Status</th>
          <th>load_config</th>
          <th>load_linear_teammates</th>
          <th>Search</th>
          <th>Create</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""


def write_eval_html_report(results: list[EvalResult], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_eval_html_report(results), encoding="utf-8")
    return path


async def run_one_eval_case(
    index: int,
    case: EvalCase,
    *,
    total_cases: int,
    semaphore: asyncio.Semaphore,
) -> EvalResult:
    async with semaphore:
        trace_id = gen_trace_id()
        current_trace_url = trace_url(trace_id)
        print(
            f"Running agent eval {index}/{total_cases}: {case.name} "
            f"(trace: {current_trace_url})"
        )
        try:
            arcade, config = await run_live_agent_eval(case, trace_id=trace_id)
            result = evaluate_case_result(
                case,
                arcade,
                config,
                trace_url=current_trace_url,
            )
        except TimeoutError:
            result = EvalResult(
                case=case,
                passed=False,
                load_config_calls=0,
                load_linear_teammates_calls=0,
                search_calls=0,
                create_calls=0,
                notes=[f"timed out after {eval_timeout_seconds()} seconds"],
                trace_url=current_trace_url,
            )
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{status}: load_config {result.load_config_calls}/"
            f"{case.expected_load_config_calls}, load_linear_teammates "
            f"{result.load_linear_teammates_calls}/{case.expected_load_config_calls}, "
            f"search {result.search_calls}/"
            f"{case.expected_search_calls}, create {result.create_calls}/"
            f"{case.expected_create_calls}"
        )
        return result


async def run_all_evals() -> list[EvalResult]:
    concurrency = eval_concurrency()
    if concurrency < 1:
        raise ValueError("AGENT_EVAL_CONCURRENCY must be at least 1")

    total_cases = len(EVAL_CASES)
    print(f"Running {total_cases} agent evals with concurrency {concurrency}")
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(
        *(
            run_one_eval_case(
                index,
                case,
                total_cases=total_cases,
                semaphore=semaphore,
            )
            for index, case in enumerate(EVAL_CASES, start=1)
        )
    )


async def main_async() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("Missing OPENAI_API_KEY. Set it in the environment or in .env.")
        return 2

    results = await run_all_evals()
    report = format_eval_report(results)
    print(report)
    html_report_path = write_eval_html_report(results, eval_report_path())
    print(f"HTML report: {html_report_path}")
    return 0 if all(result.passed for result in results) else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
