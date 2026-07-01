import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import BASE_SYSTEM_PROMPT
from config import CONFIG_CONTEXT_PREFIX, Config, save_config


def test_instructions_require_loading_config_before_notion_or_linear_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_config(
        Config(
            default_notion_doc_name="Weekly Plan",
            default_assignee="Daniel",
            default_linear_org="ARC",
            default_labels=["feature"],
        )
    )

    assert "Use the available Arcade tools" in BASE_SYSTEM_PROMPT
    assert "Always call load_config before any Notion or Linear tool call" in BASE_SYSTEM_PROMPT
    assert CONFIG_CONTEXT_PREFIX not in BASE_SYSTEM_PROMPT
    assert '"default_notion_doc_name": "Weekly Plan"' not in BASE_SYSTEM_PROMPT
    assert '"default_labels": ["feature"]' not in BASE_SYSTEM_PROMPT
