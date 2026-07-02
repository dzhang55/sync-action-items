from config import Config
from evals.cases import EvalCase
from evals.runner import (
    EvalResult,
    MockArcadeTools,
    MockConfigTools,
    case_insensitive_lookup,
    evaluate_case_result,
    format_eval_html_report,
    format_eval_report
)


def test_case_insensitive_lookup_prefers_exact_match():
    assert case_insensitive_lookup({"Launch Planning": "title", "launch planning": "exact"}, "launch planning", "") == "exact"


def test_case_insensitive_lookup_matches_title_case_fixture():
    assert case_insensitive_lookup(
        {"Launch Planning": [{"id": "launch-page-456", "title": "Launch Planning"}]},
        "launch planning",
        [],
    ) == [{"id": "launch-page-456", "title": "Launch Planning"}]


def test_reports_include_numbered_eval_runs():
    case = EvalCase(
        name="repeatable eval",
        prompt="sync notion",
        config=Config(default_linear_org="ENG"),
    )
    results = [
        EvalResult(
            case=case,
            run_number=1,
            run_total=3,
            passed=True,
            load_config_calls=1,
            load_linear_teammates_calls=1,
            search_calls=0,
            create_calls=0,
            notes=[],
        ),
        EvalResult(
            case=case,
            run_number=2,
            run_total=3,
            passed=False,
            load_config_calls=0,
            load_linear_teammates_calls=0,
            search_calls=0,
            create_calls=0,
            notes=["timed out"],
        ),
    ]

    text_report = format_eval_report(results)
    html_report = format_eval_html_report(results)

    assert "repeatable eval run 1/3: PASS" in text_report
    assert "repeatable eval run 2/3: FAIL" in text_report
    assert "<th>Run</th>" in html_report
    assert "<td>1/3</td>" in html_report
    assert "<td>2/3</td>" in html_report


def test_eval_failure_notes_are_human_readable():
    case = EvalCase(
        name="notion page override beats config default",
        prompt="sync launch planning",
        config=Config(default_linear_org="ENG"),
        expected_load_config_calls=0,
        expected_created_titles=["Coordinate launch review"],
        expected_created_teams=["ENG"],
        expected_created_assignees=[None],
        expected_notion_call={"page_id": "launch-page-456"},
    )
    arcade = MockArcadeTools(
        markdown_by_page_id={},
        markdown_by_title={},
        search_results_by_title={},
    )
    config = MockConfigTools(case.config, case.linear_teammates)

    result = evaluate_case_result(case, arcade, config)

    assert result.notes == [
        "Expected 1 Linear issue to be created, but the agent created 0.",
        "Expected issue titles: Coordinate launch review. Actual issue titles: none.",
        "Expected Linear teams: ENG. Actual Linear teams: none.",
        "Expected assignees: unassigned. Actual assignees: none.",
        "Expected to read Notion page id launch-page-456, but that read did not happen.",
    ]


def test_issue_title_comparison_ignores_capitalization():
    case = EvalCase(
        name="case-only issue title difference",
        prompt="sync notion",
        config=Config(default_linear_org="ENG"),
        expected_load_config_calls=0,
        expected_created_titles=["Ship onboarding polish", "QA billing edge cases"],
        expected_created_teams=["ENG", "ENG"],
        expected_created_assignees=[None, None],
    )
    arcade = MockArcadeTools(
        markdown_by_page_id={},
        markdown_by_title={},
        search_results_by_title={},
    )
    arcade.linear_create_issue_calls.extend(
        [
            {
                "title": "ship onboarding polish",
                "team": "ENG",
                "assignee": None,
                "description": None,
            },
            {
                "title": "QA billing edge cases",
                "team": "ENG",
                "assignee": None,
                "description": None,
            },
        ]
    )
    config = MockConfigTools(case.config, case.linear_teammates)

    result = evaluate_case_result(case, arcade, config)

    assert result.passed
    assert result.notes == []
