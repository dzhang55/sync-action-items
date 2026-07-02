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


JUN_16_DISCUSSION = [
    "Reviewed the weekly planning board and confirmed the highest-risk workstream.",
    "Clarified that onboarding copy changes are blocked on final product language.",
    "Noted that billing QA still needs coverage for annual plan downgrades.",
    "Compared last week's estimates with actual completion and called out drift.",
    "Confirmed support wants earlier notice before release trains are cut.",
    "Discussed whether the import job should remain in the launch milestone.",
    "Captured a reminder to watch the signup conversion dashboard after release.",
    "Checked in on design review timing and the dependency on final screenshots.",
    "Agreed to keep the customer escalation path unchanged for this week.",
    "Reviewed open Linear issues and moved stale discovery items out of scope.",
    "Talked through the risk of carrying too many polish tasks into Friday.",
    "Confirmed engineering can absorb one more QA pass before the release branch.",
    "Reviewed owner coverage for vacation conflicts later in the sprint.",
    "Noted that the mobile review is informational and does not block launch.",
    "Discussed telemetry gaps around retry behavior in the background worker.",
    "Aligned on keeping the release notes short and focused on customer value.",
    "Reviewed feedback from sales calls about onboarding expectations.",
    "Confirmed no additional security review is needed for the current changes.",
    "Captured follow-up questions for the next product sync.",
    "Closed with agreement to revisit open risks during the Friday checkpoint.",
]

JUN_23_DISCUSSION = [
    "Opened with a review of last week's remaining launch concerns.",
    "Confirmed the onboarding polish shipped behind the planned feature flag.",
    "Reviewed billing QA notes and narrowed the remaining edge cases.",
    "Discussed import logs and the need for clearer failure messages.",
    "Checked whether support had enough context for customer-facing questions.",
    "Reviewed the changelog draft and trimmed implementation details.",
    "Talked through the plan for measuring activation after the next release.",
    "Confirmed design has no further changes for the empty-state screenshots.",
    "Reviewed the status of test fixtures for the planning sync workflow.",
    "Noted that the customer escalation was resolved without a process change.",
    "Discussed whether default assignees should be visible in the config file.",
    "Aligned on keeping the next demo focused on operational reliability.",
    "Reviewed recent incidents and confirmed no new release blockers.",
    "Checked the team calendar for review coverage later in the week.",
    "Discussed how to make the planning notes easier to scan across dates.",
    "Captured a reminder to prune old action items before the next planning pass.",
    "Reviewed outstanding documentation updates for the support handoff.",
    "Confirmed QA can run a final smoke test before the branch cut.",
    "Noted that unanswered product questions should stay in the notes section.",
    "Closed with owners confirming the next batch of action items.",
]

JUN_30_DISCUSSION = [
    "Started by reviewing the prior week's completed action items.",
    "Confirmed the planning doc should keep historical context for readers.",
    "Reviewed the newest weekly priorities and separated discussion from tasks.",
    "Discussed which action items should become Linear issues after parsing.",
    "Checked that explicit assignee emails should override default ownership.",
    "Confirmed checked items should remain in the notes but not create new work.",
    "Discussed how synced Linear links should prevent duplicate issues.",
    "Reviewed team defaults and when a prompt should override the configured team.",
    "Talked through how missing Notion pages should fail without creating issues.",
    "Confirmed the runner report should stay concise even with larger fixtures.",
    "Reviewed how longer notes may affect the model's tool selection.",
    "Discussed keeping the latest section near the end of the document.",
    "Checked that the action-item header is consistent across weekly entries.",
    "Aligned on preserving older planning notes for realistic context.",
    "Reviewed labels and whether they should be carried into created issues.",
    "Discussed using config defaults when action items omit an assignee.",
    "Confirmed search-based flows should still read the chosen page by id.",
    "Captured the expectation that only relevant unchecked items become issues.",
    "Reviewed possible ambiguity between old notes and current tasks.",
    "Closed by recording the latest action items for this week.",
]

WEEKLY_PLANNING_PREAMBLE = "\n".join(
    [
        "# Jun 16",
        *JUN_16_DISCUSSION,
        "",
        "## Action items",
        "- [x] Send Jun 16 planning recap to stakeholders",
        "- [x] Close out Jun 16 billing QA follow-up",
        "",
        "# Jun 23",
        *JUN_23_DISCUSSION,
        "",
        "## Action items",
        "- [x] Publish Jun 23 support handoff notes",
        "- [x] Confirm Jun 23 launch smoke-test coverage",
        "",
        "# Jun 30",
        *JUN_30_DISCUSSION,
        "",
        "## Action items",
    ]
)


def weekly_planning_doc(*latest_action_items: str) -> str:
    action_items = latest_action_items or ("No new action items today.",)
    return "\n".join([WEEKLY_PLANNING_PREAMBLE, *action_items])


def unchecked_tasks(*tasks: str) -> str:
    return weekly_planning_doc(*(f"- [ ] {task}" for task in tasks))


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
        markdown_by_page_id={"empty-page-123": weekly_planning_doc()},
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
            "notion-page-123": weekly_planning_doc(
                "- [ ] Ship onboarding polish daniel@example.com",
                "- [x] Already shipped priya@example.com",
                "- [ ] QA billing edge cases priya@example.com",
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
            "notion-page-123": weekly_planning_doc(
                "- [ ] Already synced https://linear.app/acme/issue/ENG-88",
                "- [ ] Prepare launch checklist priya@example.com",
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
