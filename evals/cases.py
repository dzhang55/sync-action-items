from __future__ import annotations

from dataclasses import dataclass, field

from config import Config


@dataclass(frozen=True)
class EvalCase:
    name: str
    prompt: str
    config: Config
    markdown_by_page_id: dict[str, str] = field(default_factory=dict)
    markdown_by_title: dict[str, str] = field(default_factory=dict)
    search_results_by_title: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    expected_load_config_calls: int = 1
    expected_search_calls: int = 0
    expected_created_titles: list[str] = field(default_factory=list)
    expected_created_teams: list[str] = field(default_factory=list)
    expected_created_assignees: list[str | None] = field(default_factory=list)
    expected_notion_call: dict[str, str] | None = None

    @property
    def expected_create_calls(self) -> int:
        return len(self.expected_created_titles)


def unchecked_tasks(*tasks: str) -> str:
    return "\n".join(["# Planning", *(f"- [ ] {task}" for task in tasks)])


EVAL_CASES = [
    EvalCase(
        name="search page and create linear issues",
        prompt=(
            "Load config, search for the Notion page named 'Weekly Planning', parse it, "
            "and create one Linear issue for each unchecked todo. Use explicit emails "
            "in todos as assignees."
        ),
        config=Config(default_linear_org="ENG", default_labels=["weekly-planning"]),
        markdown_by_page_id={
            "notion-page-123": unchecked_tasks(
                "Ship onboarding polish daniel@example.com",
                "QA billing edge cases priya@example.com",
            )
        },
        search_results_by_title={
            "Weekly Planning": [{"id": "notion-page-123", "title": "Weekly Planning"}]
        },
        expected_search_calls=1,
        expected_created_titles=["Ship onboarding polish", "QA billing edge cases"],
        expected_created_teams=["ENG", "ENG"],
        expected_created_assignees=["daniel@example.com", "priya@example.com"],
        expected_notion_call={"page_id": "notion-page-123"},
    ),
    EvalCase(
        name="search page with no todos",
        prompt=(
            "Load config, search for the Notion page named 'Empty Planning', parse it, "
            "and create Linear issues only for unchecked todo checkboxes."
        ),
        config=Config(default_linear_org="ENG"),
        markdown_by_page_id={
            "empty-page-123": "# Empty Planning\nMeeting notes only.\nNo action items today."
        },
        search_results_by_title={
            "Empty Planning": [{"id": "empty-page-123", "title": "Empty Planning"}]
        },
        expected_search_calls=1,
        expected_notion_call={"page_id": "empty-page-123"},
    ),
    EvalCase(
        name="completed todos are skipped",
        prompt=(
            "Sync my default Notion planning page into Linear. Create one Linear issue "
            "for each unchecked checkbox item. Skip checked items."
        ),
        config=Config(
            default_notion_doc_id="notion-page-123",
            default_linear_org="ENG",
            default_labels=["weekly-planning"],
        ),
        markdown_by_page_id={
            "notion-page-123": "\n".join(
                [
                    "# Weekly Planning",
                    "- [ ] Ship onboarding polish daniel@example.com",
                    "- [x] Already shipped priya@example.com",
                    "- [ ] QA billing edge cases priya@example.com",
                ]
            )
        },
        expected_created_titles=["Ship onboarding polish", "QA billing edge cases"],
        expected_created_teams=["ENG", "ENG"],
        expected_created_assignees=["daniel@example.com", "priya@example.com"],
        expected_notion_call={"page_id": "notion-page-123"},
    ),
    EvalCase(
        name="previously synced tasks are skipped",
        prompt=(
            "Sync my default Notion planning page into Linear. Create issues for unchecked "
            "todos, but skip any todo that already includes a Linear issue URL."
        ),
        config=Config(default_notion_doc_id="notion-page-123", default_linear_org="ENG"),
        markdown_by_page_id={
            "notion-page-123": "\n".join(
                [
                    "# Weekly Planning",
                    "- [ ] Already synced https://linear.app/acme/issue/ENG-88",
                    "- [ ] Prepare launch checklist priya@example.com",
                ]
            )
        },
        expected_created_titles=["Prepare launch checklist"],
        expected_created_teams=["ENG"],
        expected_created_assignees=["priya@example.com"],
        expected_notion_call={"page_id": "notion-page-123"},
    ),
    EvalCase(
        name="cannot find notion page",
        prompt=(
            "Load config, search for the Notion page named 'Missing Planning', parse it, "
            "and create Linear issues for unchecked todos."
        ),
        config=Config(default_linear_org="ENG"),
        search_results_by_title={"Missing Planning": []},
        expected_search_calls=1,
    ),
    EvalCase(
        name="no notion page provided uses default",
        prompt=(
            "Sync my default Notion planning page into Linear. Create issues for unchecked todos."
        ),
        config=Config(default_notion_doc_id="default-page-123", default_linear_org="ENG"),
        markdown_by_page_id={"default-page-123": unchecked_tasks("Draft changelog")},
        expected_created_titles=["Draft changelog"],
        expected_created_teams=["ENG"],
        expected_created_assignees=[None],
        expected_notion_call={"page_id": "default-page-123"},
    ),
    EvalCase(
        name="no linear team provided uses default",
        prompt=(
            "Sync the default Notion planning page into Linear. Create issues for unchecked todos."
        ),
        config=Config(default_notion_doc_id="default-page-123", default_linear_org="Product"),
        markdown_by_page_id={"default-page-123": unchecked_tasks("Review import logs")},
        expected_created_titles=["Review import logs"],
        expected_created_teams=["Product"],
        expected_created_assignees=[None],
        expected_notion_call={"page_id": "default-page-123"},
    ),
    EvalCase(
        name="uses default assignee",
        prompt=(
            "Sync the default Notion planning page into Linear. Create issues for unchecked "
            "todos and use config defaults when a todo has no assignee."
        ),
        config=Config(
            default_notion_doc_id="notion-page-123",
            default_assignee="@me",
            default_linear_org="Product Engineering",
            default_labels=["weekly-planning", "ops"],
        ),
        markdown_by_page_id={"notion-page-123": unchecked_tasks("Prepare launch checklist")},
        expected_created_titles=["Prepare launch checklist"],
        expected_created_teams=["Product Engineering"],
        expected_created_assignees=["@me"],
        expected_notion_call={"page_id": "notion-page-123"},
    ),
    EvalCase(
        name="notion page override beats config default",
        prompt=(
            "Load config, but use the Notion page named 'Launch Planning' instead of the "
            "default Notion page. Search for that page and create issues for unchecked todos."
        ),
        config=Config(
            default_notion_doc_id="default-page-123",
            default_notion_doc_name="Default Planning",
            default_linear_org="ENG",
        ),
        markdown_by_page_id={
            "default-page-123": unchecked_tasks("Do not use this task"),
            "launch-page-456": unchecked_tasks("Coordinate launch review"),
        },
        search_results_by_title={
            "Launch Planning": [{"id": "launch-page-456", "title": "Launch Planning"}]
        },
        expected_search_calls=1,
        expected_created_titles=["Coordinate launch review"],
        expected_created_teams=["ENG"],
        expected_created_assignees=[None],
        expected_notion_call={"page_id": "launch-page-456"},
    ),
    EvalCase(
        name="linear team override beats config default",
        prompt=(
            "Sync the default Notion planning page into Linear. Create issues for unchecked "
            "todos in the Linear team Support, even though config has a different default team."
        ),
        config=Config(default_notion_doc_id="default-page-123", default_linear_org="ENG"),
        markdown_by_page_id={"default-page-123": unchecked_tasks("Triage customer escalation")},
        expected_created_titles=["Triage customer escalation"],
        expected_created_teams=["Support"],
        expected_created_assignees=[None],
        expected_notion_call={"page_id": "default-page-123"},
    ),
]
