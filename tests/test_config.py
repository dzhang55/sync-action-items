import asyncio
import json

import pytest

from config import (
    CONFIG_KEYS,
    CONFIG_FIELD_SCHEMA,
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
        default_labels=["bug"],
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
            default_labels=["bug"],
        ),
        path,
    )

    updated = update_config(default_labels=["feature"], path=path)

    assert updated == Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Daniel",
        default_linear_org="ARC",
        default_labels=["feature"],
    )


def test_update_rejects_unknown_keys(tmp_path):
    with pytest.raises(ValueError, match="Unknown config key"):
        Config.from_dict(
            {
                "default_notion_doc_name": "Weekly Plan",
                "default_notion_doc_id": None,
                "default_assignee": None,
                "default_linear_org": None,
                "default_labels": [],
                "notion_doc_name": "Legacy Field",
            }
        )


def test_legacy_default_label_loads_as_default_labels():
    config = Config.from_dict({"default_label": "bug"})

    assert config.default_labels == ["bug"]
    assert "default_label" not in config.to_dict()


def test_empty_list_clears_labels_while_omitted_fields_are_preserved(tmp_path):
    path = tmp_path / "config.json"
    save_config(
        Config(
            default_notion_doc_name="Weekly Plan",
            default_notion_doc_id="notion-page-123",
            default_assignee="Daniel",
            default_linear_org="ARC",
            default_labels=["bug"],
        ),
        path,
    )

    updated = update_config(default_labels=[], path=path)

    assert updated == Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Daniel",
        default_linear_org="ARC",
        default_labels=[],
    )


def test_config_tools_return_json(tmp_path):
    path = tmp_path / "config.json"

    read_result = json.loads(asyncio.run(read_config_tool(None, "{}", config_path=path)))
    assert read_result == {
        "default_notion_doc_name": None,
        "default_notion_doc_id": None,
        "default_assignee": None,
        "default_linear_org": None,
        "default_labels": [],
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
                        "default_labels": ["bug", "feature"],
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
        "default_labels": ["bug", "feature"],
    }
    assert load_config(path) == Config(
        default_notion_doc_name="Weekly Plan",
        default_notion_doc_id="notion-page-123",
        default_assignee="Daniel",
        default_labels=["bug", "feature"],
    )


def test_config_tools_expose_load_config_tool_name():
    assert [tool.name for tool in build_config_tools()] == ["load_config", "update_config"]


def test_format_config_context_renders_config_snapshot():
    context = format_config_context(default_config())

    assert "Current local config JSON:" in context
    assert "default_notion_doc_name" in context
    assert "default_notion_doc_id" in context
    assert "default_labels" in context
