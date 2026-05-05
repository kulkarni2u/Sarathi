"""Deterministic local provider for early orchestration slices."""
from __future__ import annotations

import re

try:
    from ..contracts import DispatchRequest, DispatchResponse
except ImportError:
    from runtime.contracts import DispatchRequest, DispatchResponse

from .base import ProviderAdapter


class LocalProviderAdapter(ProviderAdapter):
    @property
    def name(self) -> str:
        return "local"

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        if request.mode == "explore":
            return self._dispatch_explore(request)
        return self._dispatch_execute(request)

    def _dispatch_explore(self, request: DispatchRequest) -> DispatchResponse:
        description = request.inputs.get("task_description", request.prompt)
        complexity = request.inputs.get("complexity", "medium")
        approaches = [
            f"Direct implementation: {description}",
            "Modular approach: Break down into smaller components",
            "Test-driven approach: Write tests first, then implementation",
        ]
        if complexity == "high":
            approaches.extend([
                "Iterative approach: Implement in phases with checkpoints",
                "Spike approach: Create proof-of-concept first",
            ])

        risks = []
        for approach in approaches:
            lower = approach.lower()
            if "direct" in lower:
                risks.append("May miss edge cases without proper analysis")
            if "modular" in lower:
                risks.append("Additional complexity in component interfaces")
            if "test-driven" in lower:
                risks.append("Initial time investment in test writing")
            if "iterative" in lower:
                risks.append("Scope creep if phases not well-defined")
            if "spike" in lower:
                risks.append("Proof-of-concept may not translate to production")

        success_criteria = [
            "Functionality works as specified",
            "No regressions in existing code",
            "Code follows project conventions",
            "Tests pass with adequate coverage",
        ]
        outputs = {
            "messages": [f"Explored {len(approaches)} approaches for {request.phase}"],
            "confidence": 1.0 if risks and success_criteria else 0.7,
            "approaches": approaches,
            "risks": risks,
            "success_criteria": success_criteria,
        }
        evidence = {
            "alternative_approaches_considered": len(approaches) >= 3,
            "risks_identified": len(risks) > 0,
            "success_criteria_defined": len(success_criteria) > 0,
            "reversibility_assessed": any("rollback" in risk.lower() for risk in risks),
        }
        return DispatchResponse(
            success=True,
            outputs=outputs,
            evidence=evidence,
            artifacts={"mode": "explore", "provider": self.name},
        )

    def _dispatch_execute(self, request: DispatchRequest) -> DispatchResponse:
        if request.constraints.get("purpose") == "quality_recovery_fix":
            reason = request.inputs.get("reason", "phase requested recovery")
            recovery_class = request.constraints.get(
                "recovery_class",
                request.inputs.get("recovery_class", "generic_retry"),
            )
            provider_context = (
                request.inputs.get("provider_context")
                if isinstance(request.inputs.get("provider_context"), dict)
                else {}
            )
            provider_name = (
                provider_context.get("provider")
                if isinstance(provider_context.get("provider"), str)
                else request.constraints.get("provider", self.name)
            )
            outputs = {
                "recovery_actions": [
                    {
                        "action": "provider_guided_retry_preparation",
                        "reason": reason,
                        "provider": provider_name,
                        "recovery_class": recovery_class,
                    }
                ],
                "retry_guidance": self._retry_guidance(
                    reason=reason,
                    recovery_class=str(recovery_class),
                    provider_name=str(provider_name),
                ),
                "changes_applied": False,
            }
            return DispatchResponse(
                success=True,
                outputs=outputs,
                evidence={
                    "provider_recovery_fix_prepared": True,
                    "recovery_class": recovery_class,
                    "provider_recovery_target": provider_name,
                },
                artifacts={
                    "mode": "execute",
                    "provider": self.name,
                    "purpose": "quality_recovery_fix",
                    "recovery_class": recovery_class,
                    "target_provider": provider_name,
                },
            )

        if request.constraints.get("purpose") == "child_task_execution":
            node = request.inputs.get("node", {})
            changed_files = self._changed_files_for_node(node)
            response_evidence = {
                "child_task_executed": True,
                "changed_files": changed_files,
                "tests_ran": [self._test_command_for_files(changed_files)],
            }
            outputs = {
                "work_unit_result": {
                    "node_id": node.get("id"),
                    "title": node.get("title"),
                    "status": "completed",
                },
                "evidence": response_evidence,
            }
            return DispatchResponse(
                success=True,
                outputs=outputs,
                evidence=response_evidence,
                artifacts={"mode": "execute", "provider": self.name, "purpose": "child_task_execution"},
            )

        description = request.inputs.get("task_description", request.prompt)
        approaches = request.inputs.get("approaches", [])
        risks = request.inputs.get("risks", [])
        success_criteria = request.inputs.get("success_criteria", [])
        plan = {
            "objective": description,
            "approach": approaches[0] if approaches else "Direct implementation",
            "steps": [
                "Analyze requirements and constraints",
                "Design solution architecture",
                "Implement core functionality",
                "Add tests and validation",
                "Review and refine",
            ],
            "dependencies": risks,
            "timeline": "1-2 weeks",
            "success_criteria": success_criteria,
        }
        outputs = {
            "implementation_plan": plan,
            "effort_estimate": max(len(plan["steps"]) + len(plan["dependencies"]), 1),
        }
        return DispatchResponse(
            success=True,
            outputs=outputs,
            evidence={
                "checkpoint_list": len(plan["steps"]) > 0,
                "dependency_map": len(plan["dependencies"]) > 0,
                "rollback_plan": bool(risks),
            },
            artifacts={"mode": "execute", "provider": self.name},
        )

    def _changed_files_for_node(self, node: dict) -> list[str]:
        title = str(node.get("title") or "work unit")
        slug_parts = [part for part in re.split(r"[^a-z0-9]+", title.lower()) if part]
        slug = "_".join(slug_parts[:3]) or "work_unit"
        return [f"src/{slug}.py", f"tests/test_{slug}.py"]

    def _test_command_for_files(self, changed_files: list[str]) -> str:
        test_files = [path for path in changed_files if path.startswith("tests/")]
        if test_files:
            return f"python3 -m pytest {' '.join(test_files)}"
        return "python3 -m pytest"

    def _retry_guidance(
        self,
        *,
        reason: str,
        recovery_class: str,
        provider_name: str,
    ) -> list[str]:
        if recovery_class == "auth":
            return [
                f"Refresh or re-check authentication for provider {provider_name} before retrying.",
                f"Then address the recovery reason: {reason}",
            ]
        if recovery_class == "provider_offline":
            return [
                f"Confirm the {provider_name} CLI path and provider availability before retrying.",
                f"Then address the recovery reason: {reason}",
            ]
        if recovery_class == "native_cli_failure":
            return [
                f"Inspect the native CLI invocation for provider {provider_name} and correct the failing command context.",
                f"Then address the recovery reason: {reason}",
            ]
        return [
            f"Address recovery reason before retrying: {reason}",
            "Re-run the phase with preserved evidence context.",
        ]
