from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agents import FunctionTool


CONFIG_PATH = Path("config.json")
LINEAR_TEAMMATES_PATH = Path("linear_teammates.json")
CONFIG_CONTEXT_PREFIX = "Current local config JSON:"
UNSET = object()
LinearTeammates = dict[str, list[str]]
ConfigValue = str | None


@dataclass(frozen=True)
class Config:
    default_notion_doc_name: str | None = None
    default_notion_doc_id: str | None = None
    default_assignee: str | None = None
    default_linear_org: str | None = None

    @classmethod
    def keys(cls) -> tuple[str, ...]:
        return tuple(cls.__dataclass_fields__)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Config":
        normalized_values = dict(values)

        unknown_keys = sorted(set(normalized_values) - set(cls.keys()))
        if unknown_keys:
            raise ValueError(f"Unknown config key(s): {', '.join(unknown_keys)}")

        config_values: dict[str, ConfigValue] = {}
        for key in cls.keys():
            value = normalized_values.get(key)
            validate_config_value(key, value)
            config_values[key] = value
        return cls(**config_values)

    def to_dict(self) -> dict[str, ConfigValue]:
        return asdict(self)


CONFIG_KEYS = Config.keys()
CONFIG_FIELD_SCHEMA = {
    "anyOf": [
        {"type": "string"},
        {"type": "null"},
    ],
}
CONFIG_FIELD_SCHEMAS = {key: CONFIG_FIELD_SCHEMA for key in CONFIG_KEYS}
READ_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
UPDATE_CONFIG_SCHEMA = {
    "type": "object",
    "properties": CONFIG_FIELD_SCHEMAS,
    "additionalProperties": False,
}
LINEAR_TEAMMATES_SCHEMA = {
    "type": "object",
    "description": (
        "Map Linear usernames to nickname lists. Each key is the exact Linear username. "
        "Each value is a list of nicknames to match for that user. Initialize to [] "
        "when no nicknames are known yet."
    ),
    "propertyNames": {
        "type": "string",
        "minLength": 1,
    },
    "additionalProperties": {
        "type": "array",
        "description": (
            "Nicknames to match for this Linear username. Initialize to [] when "
            "no nicknames are known yet; never use [\"\"] as a placeholder."
        ),
        "items": {"type": "string", "minLength": 1},
    },
}
READ_LINEAR_TEAMMATES_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
UPDATE_LINEAR_TEAMMATES_SCHEMA = {
    "type": "object",
    "properties": {
        "linear_teammates": LINEAR_TEAMMATES_SCHEMA,
    },
    "required": ["linear_teammates"],
    "additionalProperties": False,
}


def default_config() -> Config:
    return Config()


def validate_config_value(key: str, value: Any) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")


def normalized_teammate_value(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_linear_teammates(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("linear_teammates must be an object")

    canonical_names: set[str] = set()
    nicknames: set[str] = set()
    for member_name, aliases in value.items():
        if not isinstance(member_name, str) or not member_name.strip():
            raise ValueError("linear_teammates keys must be non-empty strings")

        normalized_member_name = normalized_teammate_value(member_name)
        if normalized_member_name in canonical_names:
            raise ValueError(f"Duplicate Linear teammate name: {member_name}")
        canonical_names.add(normalized_member_name)

        if not isinstance(aliases, list):
            raise ValueError(f"linear_teammates[{member_name!r}] must be a list")
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(
                    f"linear_teammates[{member_name!r}] nicknames must be non-empty strings"
                )
            normalized_alias = normalized_teammate_value(alias)
            if normalized_alias in nicknames:
                raise ValueError(f"Duplicate Linear teammate nickname: {alias}")
            nicknames.add(normalized_alias)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return default_config()

    try:
        raw_config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc

    if not isinstance(raw_config, dict):
        raise ValueError(f"{path} must contain a JSON object")

    return Config.from_dict(raw_config)


def save_config(config: Config, path: Path = CONFIG_PATH) -> Config:
    path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n")
    return config


def update_config(
    *,
    default_notion_doc_name: str | None | object = UNSET,
    default_notion_doc_id: str | None | object = UNSET,
    default_assignee: str | None | object = UNSET,
    default_linear_org: str | None | object = UNSET,
    path: Path = CONFIG_PATH,
) -> Config:
    update_fields = {
        "default_notion_doc_name": default_notion_doc_name,
        "default_notion_doc_id": default_notion_doc_id,
        "default_assignee": default_assignee,
        "default_linear_org": default_linear_org,
    }
    config_values = load_config(path).to_dict()
    for key, value in update_fields.items():
        if value is UNSET:
            continue
        validate_config_value(key, value)
        config_values[key] = value
    return save_config(Config.from_dict(config_values), path)


def format_config_context(config: Config) -> str:
    return f"{CONFIG_CONTEXT_PREFIX}\n{json.dumps(config.to_dict(), sort_keys=True)}"


def default_linear_teammates() -> LinearTeammates:
    return {}


def load_linear_teammates(path: Path = LINEAR_TEAMMATES_PATH) -> LinearTeammates:
    if not path.exists():
        return default_linear_teammates()

    try:
        raw_teammates = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc

    validate_linear_teammates(raw_teammates)
    return raw_teammates


def save_linear_teammates(
    linear_teammates: LinearTeammates,
    path: Path = LINEAR_TEAMMATES_PATH,
) -> LinearTeammates:
    validate_linear_teammates(linear_teammates)
    path.write_text(json.dumps(linear_teammates, indent=2, sort_keys=True) + "\n")
    return linear_teammates


async def load_config_tool(
    context: Any,
    tool_args: str,
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    return json.dumps(load_config(config_path).to_dict(), indent=2, sort_keys=True)


read_config_tool = load_config_tool


async def update_config_tool(
    context: Any,
    tool_args: str,
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    args = json.loads(tool_args or "{}")
    if not isinstance(args, dict):
        raise ValueError("update_config requires a JSON object")
    unknown_keys = sorted(set(args) - set(CONFIG_KEYS))
    if unknown_keys:
        raise ValueError(f"Unknown config key(s): {', '.join(unknown_keys)}")

    return json.dumps(
        update_config(
            default_notion_doc_name=args.get("default_notion_doc_name", UNSET),
            default_notion_doc_id=args.get("default_notion_doc_id", UNSET),
            default_assignee=args.get("default_assignee", UNSET),
            default_linear_org=args.get("default_linear_org", UNSET),
            path=config_path,
        ).to_dict(),
        indent=2,
        sort_keys=True,
    )


async def load_linear_teammates_tool(
    context: Any,
    tool_args: str,
    *,
    linear_teammates_path: Path = LINEAR_TEAMMATES_PATH,
) -> str:
    return json.dumps(
        {"linear_teammates": load_linear_teammates(linear_teammates_path)},
        indent=2,
        sort_keys=True,
    )


async def update_linear_teammates_tool(
    context: Any,
    tool_args: str,
    *,
    linear_teammates_path: Path = LINEAR_TEAMMATES_PATH,
) -> str:
    args = json.loads(tool_args or "{}")
    if not isinstance(args, dict):
        raise ValueError("update_linear_teammates requires a JSON object")
    unknown_keys = sorted(set(args) - {"linear_teammates"})
    if unknown_keys:
        raise ValueError(f"Unknown linear teammate key(s): {', '.join(unknown_keys)}")
    if "linear_teammates" not in args:
        raise ValueError("update_linear_teammates requires linear_teammates")

    return json.dumps(
        {
            "linear_teammates": save_linear_teammates(
                args["linear_teammates"],
                linear_teammates_path,
            )
        },
        indent=2,
        sort_keys=True,
    )


def build_config_tools() -> list[Any]:
    return [
        FunctionTool(
            name="load_config",
            description="Read local defaults for the Notion doc and Linear issue creation.",
            params_json_schema=READ_CONFIG_SCHEMA,
            on_invoke_tool=load_config_tool,
            strict_json_schema=False,
        ),
        FunctionTool(
            name="update_config",
            description="Update local defaults for the Notion doc and Linear issue creation.",
            params_json_schema=UPDATE_CONFIG_SCHEMA,
            on_invoke_tool=update_config_tool,
            strict_json_schema=False,
        ),
        FunctionTool(
            name="load_linear_teammates",
            description="Read the Linear username to nickname-list map.",
            params_json_schema=READ_LINEAR_TEAMMATES_SCHEMA,
            on_invoke_tool=load_linear_teammates_tool,
            strict_json_schema=False,
        ),
        FunctionTool(
            name="update_linear_teammates",
            description=(
                "Update the Linear username to nickname-list map. Each key is the exact "
                "Linear username, and each value is a list of nicknames to match. "
                "Initialize to [] when no nicknames are known yet; never use [\"\"] "
                "as a placeholder."
            ),
            params_json_schema=UPDATE_LINEAR_TEAMMATES_SCHEMA,
            on_invoke_tool=update_linear_teammates_tool,
            strict_json_schema=False,
        ),
    ]
