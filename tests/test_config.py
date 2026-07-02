import asyncio
import json

import pytest

from config import (
    Config,
    build_config_tools,
    default_config,
    default_linear_teammates,
    format_config_context,
    load_config,
    load_linear_teammates,
    load_linear_teammates_tool,
    read_config_tool,
    save_config,
    save_linear_teammates,
    update_config,
    update_config_tool,
    update_linear_teammates_tool,
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


@pytest.mark.parametrize("key", ["default_label", "default_labels", "linear_teammates"])
def test_unknown_config_fields_are_rejected(key: str):
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


def test_load_linear_teammates_defaults_when_missing(tmp_path):
    assert load_linear_teammates(tmp_path / "linear_teammates.json") == default_linear_teammates()


def test_save_and_reload_linear_teammates(tmp_path):
    path = tmp_path / "linear_teammates.json"
    teammates = {"Daniel Zhang": ["dan"], "John Doe": []}

    assert save_linear_teammates(teammates, path) == teammates
    assert load_linear_teammates(path) == teammates


@pytest.mark.parametrize(
    ("linear_teammates", "error"),
    [
        ([], "linear_teammates must be an object"),
        ({"": []}, "keys must be non-empty strings"),
        ({"Daniel": "dan"}, "must be a list"),
        ({"Daniel": [""]}, "nicknames must be non-empty strings"),
        ({"Daniel": ["dan"], "Dana": ["DAN"]}, "Duplicate Linear teammate nickname"),
        ({"Daniel": [], "daniel": []}, "Duplicate Linear teammate name"),
    ],
)
def test_linear_teammates_rejects_malformed_values(tmp_path, linear_teammates, error):
    with pytest.raises(ValueError, match=error):
        save_linear_teammates(linear_teammates, tmp_path / "linear_teammates.json")


def test_linear_teammate_tools_return_json(tmp_path):
    path = tmp_path / "linear_teammates.json"

    read_result = json.loads(
        asyncio.run(load_linear_teammates_tool(None, "{}", linear_teammates_path=path))
    )
    assert read_result == {"linear_teammates": {}}

    update_result = json.loads(
        asyncio.run(
            update_linear_teammates_tool(
                None,
                json.dumps({"linear_teammates": {"Daniel Zhang": ["dan"], "John Doe": []}}),
                linear_teammates_path=path,
            )
        )
    )

    assert update_result == {"linear_teammates": {"Daniel Zhang": ["dan"], "John Doe": []}}
    assert load_linear_teammates(path) == {"Daniel Zhang": ["dan"], "John Doe": []}


def test_update_linear_teammates_tool_rejects_unknown_keys(tmp_path):
    with pytest.raises(ValueError, match="Unknown linear teammate key"):
        asyncio.run(
            update_linear_teammates_tool(
                None,
                '{"linear_teammates": {}, "other": true}',
                linear_teammates_path=tmp_path / "linear_teammates.json",
            )
        )


def test_config_tools_expose_local_tool_names():
    assert [tool.name for tool in build_config_tools()] == [
        "load_config",
        "update_config",
        "load_linear_teammates",
        "update_linear_teammates",
    ]


def test_format_config_context_renders_config_snapshot():
    context = format_config_context(default_config())

    assert "Current local config JSON:" in context
    assert "default_notion_doc_name" in context
    assert "default_notion_doc_id" in context
    assert "default_labels" not in context
