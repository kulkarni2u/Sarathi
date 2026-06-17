"""Tests for declarative user-agent specs (src.runtime.agent_spec)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from src.runtime.agent_roles import AgentRole
from src.runtime.agent_spec import (
    AgentSpec,
    ToolSpec,
    build_tool_schema,
    load_agent_spec,
    load_agent_specs,
    parse_agent_spec_dict,
    resolve_tool_callable,
)
from src.task_class import TaskClass


# ---------------------------------------------------------------------------
# build_tool_schema
# ---------------------------------------------------------------------------

def sample_tool(name: str, count: int, ratio: float = 1.0, verbose: bool = False, label: Optional[str] = None) -> str:
    """Do something useful with the inputs.

    Extra docstring detail that should not appear in the description.
    """
    return name


def test_build_tool_schema_introspects_types_and_required():
    schema = build_tool_schema(sample_tool)

    assert schema["name"] == "sample_tool"
    assert schema["description"] == "Do something useful with the inputs."

    props = schema["parameters"]["properties"]
    assert props["name"] == {"type": "string"}
    assert props["count"] == {"type": "integer"}
    assert props["ratio"] == {"type": "number"}
    assert props["verbose"] == {"type": "boolean"}
    assert props["label"] == {"type": "string"}

    required = schema["parameters"]["required"]
    assert set(required) == {"name", "count"}
    assert "ratio" not in required
    assert "verbose" not in required
    assert "label" not in required


def test_build_tool_schema_with_explicit_name_and_description():
    schema = build_tool_schema(sample_tool, name="custom_name", description="Custom description")

    assert schema["name"] == "custom_name"
    assert schema["description"] == "Custom description"


def test_build_tool_schema_handles_builtin_without_hints():
    # os.path.basename has no type hints resolvable via get_type_hints in some
    # interpreters; build_tool_schema must not raise.
    import os.path

    schema = build_tool_schema(os.path.basename)
    assert schema["name"] == "basename"
    assert schema["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# resolve_tool_callable
# ---------------------------------------------------------------------------

def test_resolve_tool_callable_success_with_colon_path():
    func = resolve_tool_callable("os.path:basename")
    assert callable(func)
    assert func("/a/b/c.txt") == "c.txt"


def test_resolve_tool_callable_success_with_dotted_path():
    func = resolve_tool_callable("os.path.basename")
    assert callable(func)
    assert func("/a/b/c.txt") == "c.txt"


def test_resolve_tool_callable_bad_format_raises():
    with pytest.raises(ValueError):
        resolve_tool_callable("no_separator_here")


def test_resolve_tool_callable_nonexistent_module_raises():
    with pytest.raises(ValueError):
        resolve_tool_callable("totally.nonexistent.module:func")


def test_resolve_tool_callable_nonexistent_attribute_raises():
    with pytest.raises(ValueError):
        resolve_tool_callable("os.path:does_not_exist_fn")


def test_resolve_tool_callable_non_callable_raises():
    with pytest.raises(ValueError):
        resolve_tool_callable("os.path:sep")


# ---------------------------------------------------------------------------
# parse_agent_spec_dict
# ---------------------------------------------------------------------------

def test_parse_agent_spec_dict_missing_name_raises():
    with pytest.raises(ValueError):
        parse_agent_spec_dict({"prompt": "do stuff"}, source="<test>")


def test_parse_agent_spec_dict_missing_prompt_raises():
    with pytest.raises(ValueError):
        parse_agent_spec_dict({"name": "Foo"}, source="<test>")


def test_parse_agent_spec_dict_applies_defaults():
    spec = parse_agent_spec_dict({"name": "Foo Bar", "prompt": "do stuff"}, source="<test>")

    assert spec.key == "foo-bar"
    assert spec.name == "Foo Bar"
    assert spec.prompt == "do stuff"
    assert spec.purpose == "custom agent"
    assert spec.description == ""
    assert spec.task_class == TaskClass.ANALYSIS
    assert spec.provider is None
    assert spec.model is None
    assert spec.tools == []
    assert spec.sub_agents == []
    assert spec.aliases == ()


def test_parse_agent_spec_dict_invalid_task_class_raises():
    with pytest.raises(ValueError):
        parse_agent_spec_dict(
            {"name": "Foo", "prompt": "x", "task_class": "not/a/real/class"},
            source="<test>",
        )


def test_parse_agent_spec_dict_key_slugified_when_absent():
    spec = parse_agent_spec_dict({"name": "My Cool   Agent_v2", "prompt": "x"}, source="<test>")

    assert spec.key == "my-cool-agent-v2"


def test_parse_agent_spec_dict_explicit_key_used():
    spec = parse_agent_spec_dict({"name": "Foo", "prompt": "x", "key": "custom-key"}, source="<test>")
    assert spec.key == "custom-key"


def test_parse_agent_spec_dict_tool_with_explicit_parameters_used_as_is():
    data = {
        "name": "Foo",
        "prompt": "x",
        "tools": [
            {
                "name": "my_tool",
                "callable": "os.path:basename",
                "description": "explicit desc",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            }
        ],
    }
    spec = parse_agent_spec_dict(data, source="<test>")

    assert len(spec.tools) == 1
    tool = spec.tools[0]
    assert tool.name == "my_tool"
    assert tool.description == "explicit desc"
    assert tool.callable_path == "os.path:basename"
    assert tool.parameters == {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}


def test_parse_agent_spec_dict_tool_with_resolvable_callable_gets_auto_schema():
    data = {
        "name": "Foo",
        "prompt": "x",
        "tools": [
            {"name": "basename_tool", "callable": "os.path:basename"}
        ],
    }
    spec = parse_agent_spec_dict(data, source="<test>")

    assert len(spec.tools) == 1
    tool = spec.tools[0]
    assert tool.name == "basename_tool"
    assert "properties" in tool.parameters
    # os.path.basename has a single positional 'p' (or 'path') argument
    assert tool.parameters["type"] == "object"


def test_parse_agent_spec_dict_tool_with_unresolvable_callable_falls_back():
    data = {
        "name": "Foo",
        "prompt": "x",
        "tools": [
            {"name": "broken_tool", "callable": "totally.nonexistent.module:func", "description": "fallback desc"}
        ],
    }
    spec = parse_agent_spec_dict(data, source="<test>")

    assert len(spec.tools) == 1
    tool = spec.tools[0]
    assert tool.name == "broken_tool"
    assert tool.description == "fallback desc"
    assert tool.parameters == {"type": "object", "properties": {}}


def test_parse_agent_spec_dict_invalid_data_type_raises():
    with pytest.raises(ValueError):
        parse_agent_spec_dict("not a mapping", source="<test>")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# load_agent_spec
# ---------------------------------------------------------------------------

def test_load_agent_spec_from_markdown(tmp_path: Path):
    md_path = tmp_path / "researcher.md"
    md_path.write_text(
        """# Researcher Agent

Some prose describing the agent.

```yaml
name: Researcher
key: researcher
purpose: research
description: Looks things up.
task_class: analysis
tools:
  - name: lookup
    callable: os.path:basename
```

```yaml
prompt: |
  You are a careful researcher.
aliases:
  - lookup-agent
```
"""
    )

    spec = load_agent_spec(md_path)

    assert spec.key == "researcher"
    assert spec.name == "Researcher"
    assert spec.purpose == "research"
    assert spec.description == "Looks things up."
    assert spec.task_class == TaskClass.ANALYSIS
    assert spec.prompt.strip() == "You are a careful researcher."
    assert spec.aliases == ("lookup-agent",)
    assert len(spec.tools) == 1
    assert spec.tools[0].name == "lookup"


def test_load_agent_spec_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "patcher.yaml"
    yaml_path.write_text(
        """
name: Patcher
prompt: "You fix small bugs."
task_class: codegen/patch
provider: acme
model: acme-large
tools:
  - name: read_file
    callable: os.path:basename
sub_agents:
  - reviewer
aliases:
  - patch-bot
"""
    )

    spec = load_agent_spec(yaml_path)

    assert spec.key == "patcher"
    assert spec.name == "Patcher"
    assert spec.prompt == "You fix small bugs."
    assert spec.task_class == TaskClass.CODEGEN_PATCH
    assert spec.provider == "acme"
    assert spec.model == "acme-large"
    assert spec.sub_agents == ["reviewer"]
    assert spec.aliases == ("patch-bot",)
    assert len(spec.tools) == 1


def test_load_agent_spec_unsupported_extension_raises(tmp_path: Path):
    bad_path = tmp_path / "agent.txt"
    bad_path.write_text("name: Foo\nprompt: x\n")

    with pytest.raises(ValueError):
        load_agent_spec(bad_path)


def test_load_agent_spec_markdown_without_yaml_block_raises(tmp_path: Path):
    md_path = tmp_path / "broken.md"
    md_path.write_text("# Just prose, no yaml block here.\n")

    with pytest.raises(ValueError):
        load_agent_spec(md_path)


# ---------------------------------------------------------------------------
# load_agent_specs
# ---------------------------------------------------------------------------

def test_load_agent_specs_directory(tmp_path: Path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    (agents_dir / "alpha.yaml").write_text("name: Alpha\nprompt: alpha prompt\n")
    (agents_dir / "beta.yaml").write_text("name: Beta\nprompt: beta prompt\n")
    (agents_dir / "broken.yaml").write_text("name: Broken\n")  # missing prompt -> invalid

    specs = load_agent_specs(agents_dir)

    assert set(specs) == {"alpha", "beta"}
    assert specs["alpha"].name == "Alpha"
    assert specs["beta"].name == "Beta"


def test_load_agent_specs_nonexistent_directory_returns_empty(tmp_path: Path):
    assert load_agent_specs(tmp_path / "does-not-exist") == {}


# ---------------------------------------------------------------------------
# AgentSpec.to_role
# ---------------------------------------------------------------------------

def test_agent_spec_to_role_matches_fields():
    spec = AgentSpec(
        key="myagent",
        name="My Agent",
        prompt="do things",
        purpose="custom",
        description="A test agent",
        aliases=("ma",),
    )

    role = spec.to_role()

    assert isinstance(role, AgentRole)
    assert role.key == "myagent"
    assert role.name == "My Agent"
    assert role.purpose == "custom"
    assert role.description == "A test agent"
    assert role.aliases == ("ma",)


def test_tool_spec_to_artifact_and_resolve():
    tool = ToolSpec(
        name="basename_tool",
        description="basename",
        callable_path="os.path:basename",
        parameters={"type": "object", "properties": {}},
    )

    artifact = tool.to_artifact()
    assert artifact == {
        "name": "basename_tool",
        "description": "basename",
        "callable": "os.path:basename",
        "parameters": {"type": "object", "properties": {}},
    }

    func = tool.resolve()
    assert func("/a/b/c") == "c"
