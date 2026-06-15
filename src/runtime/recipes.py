"""Reference recipes: declarative FANOUT/JUDGE workflow specs over policy packs."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from ..task_graph import TaskGraph, graph_from_workflow
except ImportError:
    from task_graph import TaskGraph, graph_from_workflow

_YAML_BLOCK_RE = re.compile(r"```yaml\s*(.*?)\s*```", re.DOTALL)
_RECIPE_FILENAMES = ("recipe.md", "recipe.yaml", "recipe.yml", "RECIPE.md")


@dataclass
class Recipe:
    """A declarative FANOUT/JUDGE workflow recipe over a policy pack."""

    key: str
    name: str
    description: str = ""
    providers: list[str] = field(default_factory=list)
    workflow: dict[str, Any] = field(default_factory=dict)  # {"nodes": [...]}
    source_dir: str | None = None

    def build_graph(self) -> TaskGraph:
        return graph_from_workflow(self.workflow)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "providers": list(self.providers),
            "workflow": self.workflow,
            "source_dir": self.source_dir,
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def parse_recipe_dict(data: Mapping[str, Any], *, source: str = "<recipe>") -> Recipe:
    """Validate and build a Recipe from a raw dict (as produced by yaml.safe_load)."""
    if not isinstance(data, Mapping):
        raise ValueError(f"Recipe {source!r} must be a mapping, got {type(data).__name__}")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Recipe {source!r} is missing required field 'name'")

    workflow = data.get("workflow")
    if not isinstance(workflow, Mapping):
        raise ValueError(f"Recipe {source!r} must define workflow.nodes")
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(f"Recipe {source!r} must define workflow.nodes")

    raw_key = data.get("key")
    if raw_key is not None:
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError(f"Recipe {source!r} field 'key' must be a non-empty string")
        key = raw_key
    else:
        key = _slugify(name)

    description = data.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError(f"Recipe {source!r} field 'description' must be a string")

    raw_providers = data.get("providers", [])
    if raw_providers is None:
        raw_providers = []
    if not isinstance(raw_providers, list) or not all(isinstance(p, str) for p in raw_providers):
        raise ValueError(f"Recipe {source!r} field 'providers' must be a list of strings")

    return Recipe(
        key=key,
        name=name,
        description=description,
        providers=list(raw_providers),
        workflow=dict(workflow),
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
        raise ValueError(f"Recipe {source!r} has no parseable ```yaml block(s)")
    return merged


def load_recipe(path: str | Path) -> Recipe:
    """Load a single Recipe from a recipe directory, .md, or .yaml/.yml file."""
    path = Path(path)

    if path.is_dir():
        recipe_file: Path | None = None
        for filename in _RECIPE_FILENAMES:
            candidate = path / filename
            if candidate.exists():
                recipe_file = candidate
                break
        if recipe_file is None:
            raise ValueError(
                f"No recipe file found in directory {str(path)!r} "
                f"(looked for {', '.join(_RECIPE_FILENAMES)})"
            )
        source_dir = str(path)
        data = _load_recipe_data(recipe_file)
    else:
        source_dir = str(path.parent)
        data = _load_recipe_data(path)

    recipe = parse_recipe_dict(data, source=str(path))
    recipe.source_dir = source_dir
    return recipe


def _load_recipe_data(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    content = path.read_text()
    if suffix in (".md", ".markdown"):
        return _parse_markdown_yaml_blocks(content, str(path))
    if suffix in (".yaml", ".yml"):
        loaded = yaml.safe_load(content)
        if not isinstance(loaded, dict):
            raise ValueError(f"Recipe {str(path)!r} must contain a YAML mapping")
        return loaded
    raise ValueError(f"Unsupported recipe file extension: {path.suffix!r} ({path})")


def load_recipes(directory: str | Path) -> dict[str, Recipe]:
    """Discover and load all recipes in a directory.

    Loads recipes from immediate subdirectories that contain a recipe file, plus
    any top-level ``*.md``/``*.yaml``/``*.yml`` recipe files directly in
    ``directory``. Tolerant: entries that fail to parse are skipped. Returns
    ``{}`` if ``directory`` doesn't exist or isn't a directory.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return {}

    recipes: dict[str, Recipe] = {}

    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        if not any((child / fn).exists() for fn in _RECIPE_FILENAMES):
            continue
        try:
            recipe = load_recipe(child)
        except ValueError:
            continue
        recipes[recipe.key] = recipe

    seen: set[Path] = set()
    for pattern in ("*.md", "*.yaml", "*.yml"):
        for candidate in sorted(directory.glob(pattern)):
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            try:
                recipe = load_recipe(candidate)
            except ValueError:
                continue
            recipes[recipe.key] = recipe

    return dict(sorted(recipes.items()))
