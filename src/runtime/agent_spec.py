"""Declarative user-agent specs: prompt + harness + TaskClass + Python function-tools."""
from __future__ import annotations

import importlib
import inspect
import re
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

try:
    from .agent_roles import AgentRole
except ImportError:
    from agent_roles import AgentRole

try:
    from ..task_class import TaskClass
except ImportError:
    from task_class import TaskClass


_YAML_BLOCK_RE = re.compile(r"```yaml\s*(.*?)\s*```", re.DOTALL)


# ---------------------------------------------------------------------------
# Tool callable resolution
# ---------------------------------------------------------------------------

def resolve_tool_callable(dotted_path: str) -> Callable[..., Any]:
    """Resolve a dotted path to a callable.

    Accepts ``"module.submodule:function"`` (preferred) or
    ``"module.submodule.function"`` (split on the last dot).
    """
    if not dotted_path or not isinstance(dotted_path, str):
        raise ValueError(f"Invalid tool callable path: {dotted_path!r}")

    if ":" in dotted_path:
        module_name, _, attr_path = dotted_path.partition(":")
    else:
        if "." not in dotted_path:
            raise ValueError(
                f"Invalid tool callable path {dotted_path!r}: "
                "expected 'module:function' or 'module.function'"
            )
        module_name, _, attr_path = dotted_path.rpartition(".")

    if not module_name or not attr_path:
        raise ValueError(
            f"Invalid tool callable path {dotted_path!r}: "
            "expected 'module:function' or 'module.function'"
        )

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"Cannot import module {module_name!r} from tool path {dotted_path!r}: {exc}") from exc

    obj: Any = module
    for part in attr_path.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise ValueError(
                f"Cannot resolve attribute {attr_path!r} on module {module_name!r} "
                f"from tool path {dotted_path!r}: {exc}"
            ) from exc

    if not callable(obj):
        raise ValueError(f"Resolved object at {dotted_path!r} is not callable: {obj!r}")

    return obj


# ---------------------------------------------------------------------------
# Tool schema generation
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type_for_annotation(annotation: Any) -> tuple[str, bool]:
    """Return (json_type, is_optional) for a Python type annotation."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return "string", False

    origin = typing.get_origin(annotation)

    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        is_optional = type(None) in typing.get_args(annotation)
        if len(args) == 1:
            json_type, _ = _json_type_for_annotation(args[0])
            return json_type, is_optional
        return "string", is_optional

    if origin is not None:
        # e.g. list[int], dict[str, Any], List[...], Dict[...]
        if origin in (list, set, tuple, frozenset):
            return "array", False
        if origin is dict:
            return "object", False
        mapped = _TYPE_MAP.get(origin)
        if mapped:
            return mapped, False
        return "string", False

    mapped = _TYPE_MAP.get(annotation)
    if mapped:
        return mapped, False

    return "string", False


def build_tool_schema(
    func: Callable[..., Any],
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Introspect ``func`` and build a JSON-schema tool definition."""
    sig = inspect.signature(func)

    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = getattr(func, "__annotations__", {}) or {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        annotation = hints.get(param_name, param.annotation)
        json_type, is_optional = _json_type_for_annotation(annotation)
        properties[param_name] = {"type": json_type}

        has_default = param.default is not inspect.Parameter.empty
        if not has_default and not is_optional:
            required.append(param_name)

    if description is not None:
        resolved_description = description
    else:
        doc = inspect.getdoc(func)
        if doc:
            resolved_description = doc.strip().splitlines()[0]
        else:
            resolved_description = ""

    return {
        "name": name or getattr(func, "__name__", "tool"),
        "description": resolved_description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ---------------------------------------------------------------------------
# ToolSpec / AgentSpec
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Declarative description of a Python function-tool."""

    name: str
    description: str = ""
    callable_path: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def to_artifact(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "callable": self.callable_path,
            "parameters": self.parameters,
        }

    def resolve(self) -> Callable[..., Any]:
        return resolve_tool_callable(self.callable_path)


@dataclass
class AgentSpec:
    """Declarative description of a user agent (prompt + harness + tools)."""

    key: str
    name: str
    prompt: str
    purpose: str = "custom agent"
    description: str = ""
    task_class: TaskClass = TaskClass.ANALYSIS
    provider: str | None = None
    model: str | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    sub_agents: list[str] = field(default_factory=list)
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def to_role(self) -> AgentRole:
        return AgentRole(
            key=self.key,
            name=self.name,
            purpose=self.purpose,
            description=self.description,
            aliases=self.aliases,
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _require_str(data: Mapping[str, Any], field_name: str, source: str, *, required: bool = False, default: str = "") -> str:
    value = data.get(field_name)
    if value is None:
        if required:
            raise ValueError(f"Agent spec {source!r} is missing required field {field_name!r}")
        return default
    if not isinstance(value, str):
        raise ValueError(f"Agent spec {source!r} field {field_name!r} must be a string")
    if required and not value.strip():
        raise ValueError(f"Agent spec {source!r} field {field_name!r} must not be empty")
    return value


def _parse_tool_entry(entry: Any, source: str) -> ToolSpec:
    if not isinstance(entry, Mapping):
        raise ValueError(f"Agent spec {source!r} has a tool entry that is not a mapping: {entry!r}")

    tool_name = entry.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError(f"Agent spec {source!r} has a tool entry missing required field 'name'")

    callable_path = entry.get("callable")
    if not isinstance(callable_path, str) or not callable_path.strip():
        raise ValueError(
            f"Agent spec {source!r} tool {tool_name!r} is missing required field 'callable'"
        )

    explicit_description = entry.get("description")
    if explicit_description is not None and not isinstance(explicit_description, str):
        raise ValueError(f"Agent spec {source!r} tool {tool_name!r} field 'description' must be a string")

    explicit_parameters = entry.get("parameters")
    if explicit_parameters is not None and not isinstance(explicit_parameters, dict):
        raise ValueError(f"Agent spec {source!r} tool {tool_name!r} field 'parameters' must be a mapping")

    if explicit_parameters is not None:
        return ToolSpec(
            name=tool_name,
            description=explicit_description or "",
            callable_path=callable_path,
            parameters=explicit_parameters,
        )

    try:
        func = resolve_tool_callable(callable_path)
        schema = build_tool_schema(func, name=tool_name, description=explicit_description)
        parameters = schema["parameters"]
        description = explicit_description if explicit_description is not None else schema["description"]
    except Exception:
        parameters = {"type": "object", "properties": {}}
        description = entry.get("description", "") or ""

    return ToolSpec(
        name=tool_name,
        description=description,
        callable_path=callable_path,
        parameters=parameters,
    )


def parse_agent_spec_dict(data: Mapping[str, Any], *, source: str = "<spec>") -> AgentSpec:
    """Validate and build an AgentSpec from a raw dict (as produced by yaml.safe_load)."""
    if not isinstance(data, Mapping):
        raise ValueError(f"Agent spec {source!r} must be a mapping, got {type(data).__name__}")

    name = _require_str(data, "name", source, required=True)
    prompt = _require_str(data, "prompt", source, required=True)

    raw_key = data.get("key")
    if raw_key is not None:
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError(f"Agent spec {source!r} field 'key' must be a non-empty string")
        key = raw_key
    else:
        key = _slugify(name)

    purpose = _require_str(data, "purpose", source, default="custom agent") or "custom agent"
    description = _require_str(data, "description", source, default="")

    raw_task_class = data.get("task_class", "analysis")
    if not isinstance(raw_task_class, str):
        raise ValueError(f"Agent spec {source!r} field 'task_class' must be a string")
    try:
        task_class = TaskClass(raw_task_class)
    except ValueError:
        raise ValueError(
            f"Agent spec {source!r} has invalid task_class {raw_task_class!r}"
        ) from None

    provider = data.get("provider")
    if provider is not None and not isinstance(provider, str):
        raise ValueError(f"Agent spec {source!r} field 'provider' must be a string")

    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"Agent spec {source!r} field 'model' must be a string")

    raw_tools = data.get("tools", [])
    if not isinstance(raw_tools, list):
        raise ValueError(f"Agent spec {source!r} field 'tools' must be a list")
    tools = [_parse_tool_entry(entry, source) for entry in raw_tools]

    raw_sub_agents = data.get("sub_agents", [])
    if not isinstance(raw_sub_agents, list) or not all(isinstance(a, str) for a in raw_sub_agents):
        raise ValueError(f"Agent spec {source!r} field 'sub_agents' must be a list of strings")

    raw_aliases = data.get("aliases", [])
    if not isinstance(raw_aliases, list) or not all(isinstance(a, str) for a in raw_aliases):
        raise ValueError(f"Agent spec {source!r} field 'aliases' must be a list of strings")

    return AgentSpec(
        key=key,
        name=name,
        prompt=prompt,
        purpose=purpose,
        description=description,
        task_class=task_class,
        provider=provider,
        model=model,
        tools=tools,
        sub_agents=list(raw_sub_agents),
        aliases=tuple(raw_aliases),
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _parse_markdown_yaml_blocks(content: str, source: str) -> dict[str, Any]:
    blocks = _YAML_BLOCK_RE.findall(content)
    merged: dict[str, Any] = {}
    found_dict = False
    for block in blocks:
        parsed = yaml.safe_load(block)
        if isinstance(parsed, dict):
            merged.update(parsed)
            found_dict = True
    if not found_dict:
        raise ValueError(f"Agent spec {source!r} has no parseable ```yaml block(s)")
    return merged


def load_agent_spec(path: str | Path) -> AgentSpec:
    """Load a single AgentSpec from a .md or .yaml/.yml file."""
    path = Path(path)
    suffix = path.suffix.lower()
    content = path.read_text()

    if suffix in (".md", ".markdown"):
        data = _parse_markdown_yaml_blocks(content, str(path))
    elif suffix in (".yaml", ".yml"):
        loaded = yaml.safe_load(content)
        if not isinstance(loaded, dict):
            raise ValueError(f"Agent spec {str(path)!r} must contain a YAML mapping")
        data = loaded
    else:
        raise ValueError(f"Unsupported agent spec file extension: {path.suffix!r} ({path})")

    return parse_agent_spec_dict(data, source=str(path))


def load_agent_specs(directory: str | Path) -> dict[str, AgentSpec]:
    """Discover and load all agent specs in a directory.

    Tolerant: files that fail to parse are skipped silently. Returns ``{}``
    if ``directory`` doesn't exist or isn't a directory.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return {}

    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in ("*.md", "*.yaml", "*.yml"):
        for candidate in sorted(directory.glob(pattern)):
            if candidate not in seen:
                seen.add(candidate)
                paths.append(candidate)

    paths.sort(key=lambda p: p.name)

    result: dict[str, AgentSpec] = {}
    for path in paths:
        try:
            spec = load_agent_spec(path)
        except ValueError:
            continue
        result[spec.key] = spec

    return result
