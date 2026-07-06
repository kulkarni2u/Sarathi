"""Load and compile policy-pack markdown into typed sections."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


POLICY_FILES = {
    "complexity": "complexity.md",
    "conventions": "conventions.md",
    "commands": "commands.md",
    "review": "review.md",
    "escalation": "escalation.md",
    "model_routing": "model-routing.md",
    "skills": "skills.md",
    "task_tracking": "task-tracking.md",
    "permissions": "permissions.md",
    "notifications": "notifications.md",
}


@dataclass
class CompiledPolicyData(Mapping[str, Any]):
    """Typed wrapper around compiled section payloads."""

    values: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


@dataclass
class PolicySection:
    """Compiled representation of a single policy file."""

    name: str
    path: str
    typed_data: CompiledPolicyData = field(default_factory=CompiledPolicyData)
    raw_excerpt: str = ""

    @property
    def data(self) -> dict[str, Any]:
        """Backwards-compatible raw dictionary access."""
        return self.typed_data.as_dict()

    def get(self, key: str, default: Any = None) -> Any:
        return self.typed_data.get(key, default)


@dataclass
class CompiledPolicyPack:
    """Compiled policy-pack with section lookup and source metadata."""

    root_path: str
    sections: dict[str, PolicySection] = field(default_factory=dict)
    parse_errors: dict[str, str] = field(default_factory=dict)

    def get(self, section_name: str) -> dict[str, Any]:
        return self.typed_get(section_name).as_dict()

    def get_section(self, section_name: str) -> PolicySection | None:
        return self.sections.get(section_name)

    def typed_get(self, section_name: str) -> CompiledPolicyData:
        section = self.get_section(section_name)
        if section is None:
            return CompiledPolicyData()
        return section.typed_data


def compile_policy_pack(policy_pack_path: str) -> CompiledPolicyPack:
    """Compile known policy-pack files from markdown/YAML content."""
    root = Path(policy_pack_path)
    compiled = CompiledPolicyPack(root_path=str(root))
    if not root.exists():
        return compiled

    for section_name, filename in POLICY_FILES.items():
        file_path = root / filename
        if not file_path.exists():
            continue
        content = file_path.read_text()
        typed_data, errors = _parse_policy_content(content)
        if errors:
            compiled.parse_errors[filename] = errors
        compiled.sections[section_name] = PolicySection(
            name=section_name,
            path=str(file_path),
            typed_data=CompiledPolicyData(typed_data),
            raw_excerpt=content[:500],
        )
    learning_feedback = _load_learning_feedback(root)
    if learning_feedback:
        compiled.sections["learning_feedback"] = PolicySection(
            name="learning_feedback",
            path=str(root / ".sarathi-proposals"),
            typed_data=CompiledPolicyData(learning_feedback),
            raw_excerpt=str(learning_feedback)[:500],
        )

    return compiled


def _parse_policy_content(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML blocks from markdown, returning (data, error_string)."""
    yaml_blocks = re.findall(r"```yaml\s*(.*?)\s*```", content, re.DOTALL)
    merged: dict[str, Any] = {}
    parse_errors: list[str] = []
    for block in yaml_blocks:
        try:
            parsed = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            parse_errors.append(str(exc))
            continue
        if isinstance(parsed, dict):
            merged.update(parsed)
    if merged:
        return merged, "; ".join(parse_errors)

    result: dict[str, Any] = {}
    for line in content.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result, "; ".join(parse_errors)


def _load_learning_feedback(root: Path) -> dict[str, Any]:
    review_dir = root / ".sarathi-proposals"
    if not review_dir.exists():
        return {}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in sorted(review_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("status") == "accepted":
            accepted.append(data)
        elif data.get("status") == "rejected":
            rejected.append(data)
    if not accepted and not rejected:
        return {}
    return {
        "accepted_proposals": accepted,
        "rejected_proposals": rejected,
    }
