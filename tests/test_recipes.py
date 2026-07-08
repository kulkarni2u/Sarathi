"""Tests for reference recipes (src.runtime.recipes) and the shipped recipe packs."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.policy.compiler import compile_policy_pack
from src.runtime.agent_spec import load_agent_specs
from src.runtime.recipes import (
    Recipe,
    load_recipe,
    load_recipes,
    parse_recipe_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = REPO_ROOT / "policy-pack" / "RECIPES"


# ---------------------------------------------------------------------------
# parse_recipe_dict
# ---------------------------------------------------------------------------

def _minimal_recipe_dict() -> dict:
    return {
        "name": "My Recipe",
        "workflow": {"nodes": [{"id": "a", "title": "A", "node_type": "execute"}]},
    }


def test_parse_recipe_dict_applies_defaults():
    recipe = parse_recipe_dict(_minimal_recipe_dict(), source="<test>")

    assert recipe.key == "my-recipe"
    assert recipe.name == "My Recipe"
    assert recipe.description == ""
    assert recipe.providers == []
    assert recipe.workflow["nodes"][0]["id"] == "a"


def test_parse_recipe_dict_not_a_mapping_raises():
    with pytest.raises(ValueError):
        parse_recipe_dict("not a mapping", source="<test>")  # type: ignore[arg-type]


def test_parse_recipe_dict_missing_name_raises():
    data = _minimal_recipe_dict()
    del data["name"]
    with pytest.raises(ValueError):
        parse_recipe_dict(data, source="<test>")


def test_parse_recipe_dict_missing_workflow_raises():
    with pytest.raises(ValueError):
        parse_recipe_dict({"name": "X"}, source="<test>")


def test_parse_recipe_dict_empty_nodes_raises():
    with pytest.raises(ValueError):
        parse_recipe_dict({"name": "X", "workflow": {"nodes": []}}, source="<test>")


def test_parse_recipe_dict_providers_non_string_raises():
    data = _minimal_recipe_dict()
    data["providers"] = ["ok", 123]
    with pytest.raises(ValueError):
        parse_recipe_dict(data, source="<test>")


def test_parse_recipe_dict_explicit_key_honored():
    data = _minimal_recipe_dict()
    data["key"] = "custom-key"
    recipe = parse_recipe_dict(data, source="<test>")
    assert recipe.key == "custom-key"


def test_parse_recipe_dict_slugifies_name_for_key():
    data = _minimal_recipe_dict()
    data["name"] = "My Cool   Recipe_v2"
    recipe = parse_recipe_dict(data, source="<test>")
    assert recipe.key == "my-cool-recipe-v2"


# ---------------------------------------------------------------------------
# load_recipe
# ---------------------------------------------------------------------------

_MD_RECIPE = """# My Recipe

Some prose.

```yaml
name: Markdown Recipe
description: from a markdown file
providers:
  - provider-a
  - provider-b
workflow:
  nodes:
    - id: fan
      title: Fan out
      node_type: fanout
      pattern_config:
        count: 2
        providers: [provider-a, provider-b]
    - id: judge
      title: Judge
      node_type: judge
      depends_on: [fan-synthesize]
```
"""


def test_load_recipe_from_markdown(tmp_path: Path):
    md = tmp_path / "recipe.md"
    md.write_text(_MD_RECIPE)

    recipe = load_recipe(md)

    assert recipe.key == "markdown-recipe"
    assert recipe.name == "Markdown Recipe"
    assert recipe.providers == ["provider-a", "provider-b"]
    assert len(recipe.workflow["nodes"]) == 2
    assert recipe.source_dir == str(tmp_path)


def test_load_recipe_from_yaml(tmp_path: Path):
    yaml_path = tmp_path / "recipe.yaml"
    yaml_path.write_text(
        "name: Yaml Recipe\n"
        "workflow:\n"
        "  nodes:\n"
        "    - id: a\n"
        "      title: A\n"
        "      node_type: execute\n"
    )

    recipe = load_recipe(yaml_path)
    assert recipe.key == "yaml-recipe"
    assert recipe.source_dir == str(tmp_path)


def test_load_recipe_from_directory(tmp_path: Path):
    (tmp_path / "recipe.md").write_text(_MD_RECIPE)

    recipe = load_recipe(tmp_path)
    assert recipe.name == "Markdown Recipe"
    assert recipe.source_dir == str(tmp_path)


def test_load_recipe_directory_without_recipe_file_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        load_recipe(tmp_path)


def test_load_recipe_unsupported_extension_raises(tmp_path: Path):
    bad = tmp_path / "recipe.txt"
    bad.write_text("name: X\n")
    with pytest.raises(ValueError):
        load_recipe(bad)


def test_load_recipe_markdown_without_yaml_block_raises(tmp_path: Path):
    md = tmp_path / "recipe.md"
    md.write_text("# Just prose, no yaml.\n")
    with pytest.raises(ValueError):
        load_recipe(md)


# ---------------------------------------------------------------------------
# load_recipes
# ---------------------------------------------------------------------------

def test_load_recipes_scans_subdirectories(tmp_path: Path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    (alpha / "recipe.md").write_text(_MD_RECIPE.replace("Markdown Recipe", "Alpha"))
    beta = tmp_path / "beta"
    beta.mkdir()
    (beta / "recipe.md").write_text(_MD_RECIPE.replace("Markdown Recipe", "Beta"))
    # A subdir without a recipe file is ignored.
    (tmp_path / "noise").mkdir()

    recipes = load_recipes(tmp_path)
    assert set(recipes) == {"alpha", "beta"}


def test_load_recipes_nonexistent_directory_returns_empty(tmp_path: Path):
    assert load_recipes(tmp_path / "does-not-exist") == {}


# ---------------------------------------------------------------------------
# Recipe.build_graph
# ---------------------------------------------------------------------------

def test_recipe_build_graph_includes_declared_nodes():
    recipe = parse_recipe_dict(
        {
            "name": "G",
            "workflow": {
                "nodes": [
                    {"id": "plan", "title": "Plan", "node_type": "execute"},
                    {"id": "fan", "title": "Fan", "node_type": "fanout", "depends_on": ["plan"]},
                ]
            },
        },
        source="<test>",
    )
    graph = recipe.build_graph().to_artifact()
    ids = [n["id"] for n in graph["nodes"]]
    assert ids == ["plan", "fan"]


def test_recipe_to_artifact_roundtrips_fields():
    recipe = Recipe(
        key="k",
        name="N",
        description="D",
        providers=["p1", "p2"],
        workflow={"nodes": [{"id": "a"}]},
        source_dir="/tmp/x",
    )
    art = recipe.to_artifact()
    assert art == {
        "key": "k",
        "name": "N",
        "description": "D",
        "providers": ["p1", "p2"],
        "workflow": {"nodes": [{"id": "a"}]},
        "source_dir": "/tmp/x",
    }


# ---------------------------------------------------------------------------
# Shipped recipe packs
# ---------------------------------------------------------------------------

def test_shipped_recipes_discovered():
    recipes = load_recipes(RECIPES_DIR)
    assert {"orchestrator", "debate", "bakeoff"} <= set(recipes)


@pytest.mark.parametrize("key", ["orchestrator", "debate", "bakeoff"])
def test_shipped_recipe_has_two_providers_and_builds(key: str):
    recipe = load_recipe(RECIPES_DIR / key)
    assert len(recipe.providers) >= 2
    graph = recipe.build_graph().to_artifact()
    assert graph["nodes"]  # non-empty

    fanout_nodes = [n for n in graph["nodes"] if str(n.get("node_type")).endswith("fanout")]
    assert fanout_nodes, f"recipe {key} must declare a fanout node"
    for fan in fanout_nodes:
        providers = fan.get("pattern_config", {}).get("providers", [])
        assert len(providers) >= 2


@pytest.mark.parametrize("key", ["orchestrator", "debate", "bakeoff"])
def test_shipped_recipe_pack_compiles(key: str):
    compiled = compile_policy_pack(str(RECIPES_DIR / key))
    assert not compiled.parse_errors


def test_orchestrator_pack_ships_agents():
    specs = load_agent_specs(RECIPES_DIR / "orchestrator" / "agents")
    assert len(specs) >= 2


def test_bakeoff_pack_ships_agents():
    specs = load_agent_specs(RECIPES_DIR / "bakeoff" / "agents")
    assert len(specs) >= 3  # codex-candidate, opencode-candidate, judge


def test_bakeoff_recipe_declares_native_providers():
    recipe = load_recipe(RECIPES_DIR / "bakeoff")
    assert recipe.providers == ["codex", "opencode"]
    graph = recipe.build_graph().to_artifact()
    fanout_nodes = [n for n in graph["nodes"] if str(n.get("node_type")).endswith("fanout")]
    assert fanout_nodes, "bakeoff recipe must declare a fanout node"
    for fan in fanout_nodes:
        providers = fan.get("pattern_config", {}).get("providers", [])
        assert providers == ["codex", "opencode"], f"bakeoff fanout must declare codex and opencode, got {providers}"
