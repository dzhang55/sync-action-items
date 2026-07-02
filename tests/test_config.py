import asyncio
import json

import pytest

from config import (
    Config,
    build_config_tools,
    default_config,
    format_config_context,
    load_config,
    read_config_tool,
    save_config,
    update_config,
    update_config_tool,
)


def test_load_config_defaults_when_missing(tmp_path):
    assert load_config(tmp_path / "config.json") == default_config()


def test_save_and_reload_config(tmp_path):
    path = tmp_path / "config.json"
    config = Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Daniel",
        default_linear_org="ARC",
    )

    assert save_config(config, path) == config
    assert load_config(path) == config


def test_partial_update_preserves_unspecified_fields(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(
            default_notion_doc_name="Weekly Plan",
            default_notion_doc_id="notion-page-123",
            default_assignee="Daniel",
            default_linear_org="ARC",
        ),
        path,
    )

    updated = update_config(default_assignee="Priya", path=path)

    assert updated == Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Priya",
        default_linear_org="ARC",
    )


def test_update_rejects_unknown_keys(tmp_path):
    with pytest.raises(ValueError, match="Unknown config key"):
        Config.from_dict(
            {
                "default_notion_doc_name": "Weekly Plan",
                "default_notion_doc_id": None,
                "default_assignee": None,
                "default_linear_org": None,
                "notion_doc_name": "Legacy Field",
            }
        )


@pytest.mark.parametrize("key", ["default_label", "default_labels"])
def test_label_fields_are_unknown(key: str):
    with pytest.raises(ValueError, match="Unknown config key"):
        Config.from_dict({key: "bug"})


def test_update_rejects_default_labels(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(
            default_notion_doc_name="Weekly Plan",
            default_notion_doc_id="notion-page-123",
            default_assignee="Daniel",
            default_linear_org="ARC",
        ),
        path,
    )

    with pytest.raises(ValueError, match="Unknown config key"):
        asyncio.run(update_config_tool(None, '{"default_labels": []}', config_path=path))


def test_config_tools_return_json(tmp_path):
    path = tmp_path / "config.json"

    read_result = json.loads(asyncio.run(read_config_tool(None, "{}", config_path=path)))
    assert read_result == {
        "default_notion_doc_name": None,
        "default_notion_doc_id": None,
        "default_assignee": None,
        "default_linear_org": None,
    }

    update_result = json.loads(
        asyncio.run(
            update_config_tool(
                None,
                json.dumps(
                    {
                        "default_notion_doc_name": "Weekly Plan",
                        "default_notion_doc_id": "notion-page-123",
                        "default_assignee": "Daniel",
                    }
                ),
                config_path=path,
            )
        )
    )

    assert update_result == {
        "default_notion_doc_name": "Weekly Plan",
        "default_notion_doc_id": "notion-page-123",
        "default_assignee": "Daniel",
        "default_linear_org": None,
    }
    assert load_config(path) == Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Daniel",
    )


def test_config_tools_expose_load_config_tool_name():
    assert [tool.name for tool in build_config_tools()] == ["load_config", "update_config"]


def test_format_config_context_renders_config_snapshot():
    context = format_config_context(default_config())

    assert "Current local config JSON:" in context
    assert "default_notion_doc_name" in context
    assert "default_notion_doc_id" in context
    assert "default_labels" not in context
