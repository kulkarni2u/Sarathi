"""Configurable deterministic provider adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import shlex
import subprocess
from typing import Any

try:
    from ..contracts import DispatchRequest, DispatchResponse
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse

from .base import ProviderAdapter
from .local import LocalProviderAdapter


class ExternalProviderAdapter(ProviderAdapter):
    """Deterministic placeholder for future external provider integrations."""

    def __init__(
        self,
        name: str,
        supported_modes: Sequence[str] = ("explore", "execute"),
        fail_dispatch: bool = False,
    ):
        if not name:
            raise ValueError("Provider name must be non-empty")
        self._name = name
        self.supported_modes = tuple(supported_modes)
        self.fail_dispatch = fail_dispatch

    @property
    def name(self) -> str:
        return self._name

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        artifacts = {
            "mode": request.mode,
            "provider": self.name,
            "supported_modes": list(self.supported_modes),
        }
        if request.mode not in self.supported_modes:
            return DispatchResponse(
                success=False,
                artifacts=artifacts,
                error=f"Provider '{self.name}' does not support mode '{request.mode}'",
            )
        if self.fail_dispatch:
            return DispatchResponse(
                success=False,
                artifacts=artifacts,
                error=f"Provider '{self.name}' failed deterministically",
            )
        outputs = {
            "messages": [
                f"Provider '{self.name}' accepted {request.mode} for {request.phase}"
            ],
            "provider": self.name,
            "mode": request.mode,
            "task_id": request.task_id,
        }
        evidence = {"provider_selected": True, "mode_supported": True}
        if request.mode == "explore":
            outputs.update(
                {
                    "approaches": [
                        f"Provider-guided implementation for {request.prompt}",
                        "Dependency-aware decomposition",
                        "Evidence-first validation path",
                    ],
                    "risks": ["Provider-backed execution needs artifact validation"],
                    "success_criteria": ["Provider result is structured and reviewable"],
                    "confidence": 0.9,
                }
            )
            evidence.update(
                {
                    "alternative_approaches_considered": True,
                    "risks_identified": True,
                    "success_criteria_defined": True,
                    "reversibility_assessed": True,
                }
            )
        if request.mode == "execute":
            if request.constraints.get("purpose") == "quality_recovery_fix":
                outputs.update(
                    {
                        "recovery_actions": [
                            {
                                "action": "external_provider_recovery_fix",
                                "provider": self.name,
                            }
                        ],
                        "retry_guidance": [f"Retry after provider '{self.name}' recovery guidance."],
                        "changes_applied": False,
                    }
                )
                evidence["provider_recovery_fix_prepared"] = True
            elif request.constraints.get("purpose") == "child_task_execution":
                node = request.inputs.get("node", {})
                outputs.update(
                    {
                        "work_unit_result": {
                            "node_id": node.get("id"),
                            "title": node.get("title"),
                            "status": "completed",
                            "provider": self.name,
                        }
                    }
                )
                evidence["child_task_executed"] = True
            else:
                outputs.update(
                    {
                    "implementation_plan": {
                        "objective": request.prompt,
                        "approach": "Provider-backed execution",
                        "steps": [
                            "Collect provider inputs",
                            "Execute provider-backed work unit",
                            "Persist structured outputs",
                            "Verify and review artifacts",
                        ],
                        "dependencies": [],
                        "timeline": "provider-dependent",
                        "success_criteria": ["Structured provider artifact returned"],
                    },
                    "effort_estimate": 4,
                    }
                )
            evidence.update(
                {
                    "checkpoint_list": True,
                    "dependency_map": True,
                    "rollback_plan": True,
                }
            )
        return DispatchResponse(
            success=True,
            outputs=outputs,
            evidence=evidence,
            artifacts=artifacts,
        )


class CommandProviderAdapter(ProviderAdapter):
    """Provider adapter that delegates dispatch to a local command."""

    def __init__(self, name: str, command: str | Sequence[str], timeout_seconds: int = 60):
        if not name:
            raise ValueError("Provider name must be non-empty")
        self._name = name
        self.command = command
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return self._name

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        command = shlex.split(self.command) if isinstance(self.command, str) else list(self.command)
        payload = json.dumps(
            {
                "mode": request.mode,
                "task_id": request.task_id,
                "phase": request.phase,
                "prompt": request.prompt,
                "inputs": request.inputs,
                "expected_outputs": request.expected_outputs,
                "constraints": request.constraints,
            }
        )
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return DispatchResponse(
                success=False,
                artifacts={"provider": self.name, "command": command},
                error=f"Command provider '{self.name}' failed: {exc}",
            )

        try:
            parsed = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return DispatchResponse(
                success=False,
                artifacts={"provider": self.name, "command": command, "stderr": completed.stderr},
                error=f"Command provider '{self.name}' returned non-JSON output",
            )
        if not isinstance(parsed, dict):
            parsed = {}
        return DispatchResponse(
            success=bool(parsed.get("success", completed.returncode == 0)),
            outputs=parsed.get("outputs") if isinstance(parsed.get("outputs"), dict) else {},
            evidence=parsed.get("evidence") if isinstance(parsed.get("evidence"), dict) else {},
            artifacts={
                "provider": self.name,
                "command": command,
                **(parsed.get("artifacts") if isinstance(parsed.get("artifacts"), dict) else {}),
            },
            raw_transcript_ref=parsed.get("raw_transcript_ref") if isinstance(parsed.get("raw_transcript_ref"), str) else None,
            error=parsed.get("error") if isinstance(parsed.get("error"), str) else (completed.stderr.strip() or None),
        )


class ConfiguredProviderAdapter(ProviderAdapter):
    """Routes dispatches to provider adapters selected by config or policy."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        providers: Mapping[str, ProviderAdapter] | None = None,
        default_provider: str = "local",
    ):
        self.config = dict(config or {})
        self.default_provider = str(self.config.get("provider", default_provider))
        self.phase_providers = {
            str(phase): str(provider_name)
            for phase, provider_name in (self.config.get("phase_providers", {}) or {}).items()
            if isinstance(phase, str) and isinstance(provider_name, str) and phase and provider_name
        }
        self.providers: dict[str, ProviderAdapter] = {"local": LocalProviderAdapter()}
        configured_providers = self.config.get("providers", ())
        if isinstance(configured_providers, Mapping):
            for provider_name, provider_cfg in configured_providers.items():
                self.providers[str(provider_name)] = self._provider_from_config(str(provider_name), provider_cfg)
        else:
            for provider_name in configured_providers:
                if provider_name != "local":
                    self.providers[provider_name] = ExternalProviderAdapter(provider_name)
        if providers:
            self.providers.update(providers)

    @property
    def name(self) -> str:
        return self.default_provider

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        provider_name = self._provider_name_for(request)
        provider = self.providers.get(provider_name)
        if provider is None:
            return DispatchResponse(
                success=False,
                artifacts={
                    "provider": provider_name,
                    "available_providers": sorted(self.providers),
                },
                error=f"Provider '{provider_name}' is not configured",
            )
        try:
            return provider.dispatch(request)
        except Exception as exc:
            return DispatchResponse(
                success=False,
                artifacts={"provider": provider_name},
                error=f"Provider '{provider_name}' failed: {exc}",
            )

    def _provider_name_for(self, request: DispatchRequest) -> str:
        for source in (request.constraints, request.inputs):
            provider_name = self._provider_name_from(source)
            if provider_name:
                return provider_name
        phase_provider = self.phase_providers.get(request.phase)
        if phase_provider:
            return phase_provider
        return self.default_provider

    def _provider_name_from(self, source: Mapping[str, Any]) -> str | None:
        for key in ("provider", "provider_name"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
        runtime_config = source.get("runtime")
        if isinstance(runtime_config, Mapping):
            value = runtime_config.get("provider")
            if isinstance(value, str) and value:
                return value
        return None

    def _provider_from_config(self, provider_name: str, provider_cfg: Any) -> ProviderAdapter:
        if isinstance(provider_cfg, Mapping) and provider_cfg.get("type") == "command":
            command = provider_cfg.get("command")
            if isinstance(command, (str, list, tuple)):
                return CommandProviderAdapter(
                    provider_name,
                    command,
                    timeout_seconds=int(provider_cfg.get("timeout_seconds", 60) or 60),
                )
        return ExternalProviderAdapter(provider_name)


def validate_provider_routing_config(config: Any) -> list[str]:
    """Return validation issues for model-routing provider configuration."""
    if config is None:
        return []
    if not isinstance(config, Mapping):
        return ["model_routing must be a mapping"]
    issues: list[str] = []
    provider = config.get("provider")
    if "provider" in config and not isinstance(provider, str):
        issues.append("model_routing.provider must be a string")
    phase_providers = config.get("phase_providers")
    if phase_providers is not None and not isinstance(phase_providers, Mapping):
        issues.append("model_routing.phase_providers must be a mapping")
    providers = config.get("providers")
    if providers is not None and not isinstance(providers, (list, tuple, Mapping)):
        issues.append("model_routing.providers must be a list or mapping")
    if isinstance(providers, Mapping):
        for provider_name, provider_cfg in providers.items():
            if not isinstance(provider_name, str) or not provider_name:
                issues.append("model_routing.providers keys must be non-empty strings")
            if isinstance(provider_cfg, Mapping) and provider_cfg.get("type") == "command":
                command = provider_cfg.get("command")
                if not isinstance(command, (str, list, tuple)):
                    issues.append(f"model_routing.providers.{provider_name}.command must be a string or list")
    if isinstance(phase_providers, Mapping):
        for phase_name, provider_name in phase_providers.items():
            if not isinstance(phase_name, str) or not phase_name:
                issues.append("model_routing.phase_providers keys must be non-empty strings")
            if not isinstance(provider_name, str) or not provider_name:
                issues.append(
                    f"model_routing.phase_providers.{phase_name} must be a non-empty provider string"
                )
    return issues


def apply_learning_feedback_to_provider_routing(
    config: Mapping[str, Any] | None,
    learning_feedback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge accepted routing hints from learning feedback into provider config."""
    merged = dict(config or {})
    if not isinstance(learning_feedback, Mapping):
        return merged
    phase_providers = dict(merged.get("phase_providers", {}) or {})
    for proposal in learning_feedback.get("accepted_proposals", []):
        if not isinstance(proposal, Mapping):
            continue
        routing_hint = proposal.get("routing_hint")
        if not isinstance(routing_hint, Mapping):
            continue
        phase = routing_hint.get("phase")
        preferred_provider = routing_hint.get("preferred_provider")
        if isinstance(phase, str) and phase and isinstance(preferred_provider, str) and preferred_provider:
            phase_providers[phase] = preferred_provider
    if phase_providers:
        merged["phase_providers"] = phase_providers
    return merged
