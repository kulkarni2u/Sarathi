"""Policy-driven domain subrole selection for Sarathi roles."""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


@dataclass(frozen=True)
class RoleSubrole:
    """A domain overlay that can decorate a stable Sarathi lifecycle role."""

    key: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    file_patterns: tuple[str, ...] = ()
    compatible_base_roles: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    review_mode: str | None = None


@dataclass
class RoleSubrolePolicy:
    """Selects optional domain overlays from a policy-pack skills section."""

    subroles: tuple[RoleSubrole, ...] = field(default_factory=tuple)

    @classmethod
    def from_skills_section(cls, section: dict[str, Any] | None) -> "RoleSubrolePolicy":
        if not isinstance(section, dict):
            return cls()

        raw_subroles = section.get("subroles", {})
        if not isinstance(raw_subroles, dict):
            return cls()

        subroles: list[RoleSubrole] = []
        for key, raw_config in raw_subroles.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(raw_config, dict):
                continue
            applies_when = raw_config.get("applies_when", {})
            if not isinstance(applies_when, dict):
                applies_when = {}
            subroles.append(
                RoleSubrole(
                    key=key.strip(),
                    description=_string(raw_config.get("description")),
                    keywords=_strings(applies_when.get("keywords")),
                    file_patterns=_strings(applies_when.get("files") or applies_when.get("file_patterns")),
                    compatible_base_roles=_strings(
                        raw_config.get("compatible_base_roles") or raw_config.get("base_roles")
                    ),
                    evidence_required=_strings(raw_config.get("evidence_required")),
                    review_mode=_optional_string(raw_config.get("review_mode")),
                )
            )
        return cls(subroles=tuple(subroles))

    def select(
        self,
        *,
        task_description: str,
        file_paths: list[str] | tuple[str, ...] | None = None,
        base_roles: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Return selected subrole artifacts ordered by match strength."""

        normalized_roles = [_normalize(role) for role in (base_roles or ()) if isinstance(role, str)]
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for index, subrole in enumerate(self.subroles):
            matched_by = _matches(subrole, task_description=task_description, file_paths=file_paths or ())
            if not matched_by:
                continue
            base_role = _select_base_role(subrole, normalized_roles)
            confidence = _confidence(matched_by)
            candidates.append(
                (
                    confidence,
                    index,
                    {
                        "key": subrole.key,
                        "base_role": base_role,
                        "description": subrole.description,
                        "confidence": confidence,
                        "matched_by": matched_by,
                        "evidence_required": list(subrole.evidence_required),
                        **({"review_mode": subrole.review_mode} if subrole.review_mode else {}),
                    },
                )
            )

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [artifact for _, _, artifact in candidates]

    def role_plan(
        self,
        *,
        task_description: str,
        file_paths: list[str] | tuple[str, ...] | None = None,
        base_roles: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        selected = self.select(
            task_description=task_description,
            file_paths=file_paths,
            base_roles=base_roles,
        )
        return {
            "selected_subroles": selected,
            "selected_count": len(selected),
        }


def _matches(
    subrole: RoleSubrole,
    *,
    task_description: str,
    file_paths: list[str] | tuple[str, ...],
) -> list[str]:
    matched: list[str] = []
    description = task_description.casefold()

    for keyword in subrole.keywords:
        normalized = keyword.strip().casefold()
        if normalized and normalized in description:
            matched.append(f"keyword:{keyword}")

    for pattern in subrole.file_patterns:
        if _matches_any_file(pattern, file_paths):
            matched.append(f"file:{pattern}")

    return _dedupe(matched)


def _matches_any_file(pattern: str, file_paths: list[str] | tuple[str, ...]) -> bool:
    normalized_pattern = pattern.strip()
    if not normalized_pattern:
        return False
    for raw_path in file_paths:
        path = str(raw_path).strip()
        if not path:
            continue
        basename = path.rsplit("/", 1)[-1]
        if fnmatch(path, normalized_pattern) or fnmatch(basename, normalized_pattern):
            return True
    return False


def _select_base_role(subrole: RoleSubrole, normalized_roles: list[str]) -> str | None:
    compatible = [_normalize(role) for role in subrole.compatible_base_roles]
    if not compatible:
        return normalized_roles[0] if normalized_roles else None
    for role in normalized_roles:
        if role in compatible:
            return role
    return compatible[0]


def _confidence(matched_by: list[str]) -> float:
    keyword_matches = sum(1 for match in matched_by if match.startswith("keyword:"))
    file_matches = sum(1 for match in matched_by if match.startswith("file:"))
    return min(0.99, round(0.4 + (keyword_matches * 0.2) + (file_matches * 0.25), 2))


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
