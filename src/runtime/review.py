"""Structured review runtime helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from typing import Literal


Severity = Literal["info", "minor", "major", "critical"]


@dataclass
class ReviewFinding:
    """Single structured review finding."""

    check: str
    passed: bool
    severity: Severity = "info"
    message: str = ""

    def to_artifact(self) -> dict:
        return {
            "check": self.check,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class ReviewVerdict:
    """Aggregate review result."""

    findings: list[ReviewFinding] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    @property
    def score(self) -> float:
        if not self.findings:
            return 0.0
        passed = sum(1 for finding in self.findings if finding.passed)
        return (passed / len(self.findings)) * 10.0

    @property
    def outcome(self) -> Literal["pass", "escalate", "fail"]:
        has_critical = any(
            not finding.passed and finding.severity == "critical"
            for finding in self.findings
        )
        if has_critical:
            return "fail"
        if self.score >= 8:
            return "pass"
        if self.score >= 6:
            return "escalate"
        return "fail"

    @property
    def severity_counts(self) -> dict[Severity, int]:
        counts: dict[Severity, int] = {
            "info": 0,
            "minor": 0,
            "major": 0,
            "critical": 0,
        }
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def totals(self) -> dict[str, int]:
        passed = sum(1 for finding in self.findings if finding.passed)
        failed = len(self.findings) - passed
        return {
            "checks": len(self.findings),
            "passed": passed,
            "failed": failed,
        }

    @property
    def artifact_summary(self) -> dict[str, object]:
        totals = self.totals
        return {
            "generated_at": self.generated_at,
            "outcome": self.outcome,
            "score": self.score,
            "checks": totals["checks"],
            "passed": totals["passed"],
            "failed": totals["failed"],
            "severity_counts": self.severity_counts,
        }

    def to_artifact(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "score": self.score,
            "outcome": self.outcome,
            "severity_counts": self.severity_counts,
            "totals": self.totals,
            "summary": self.artifact_summary,
            "findings": [finding.to_artifact() for finding in self.findings],
        }


class ReviewRunner:
    """Produces structured review verdicts from available phase evidence."""

    DEFAULT_CHECKS = (
        "spec_compliance",
        "code_quality",
        "security",
        "performance",
        "documentation",
    )

    def review(
        self,
        checks: dict[str, bool] | None = None,
        evidence: dict[str, object] | None = None,
    ) -> ReviewVerdict:
        if evidence is not None:
            return self.review_evidence(evidence)
        checks = checks or {check: True for check in self.DEFAULT_CHECKS}
        findings = [
            ReviewFinding(
                check=check,
                passed=passed,
                severity="major" if not passed else "info",
                message="passed" if passed else f"{check} did not pass",
            )
            for check, passed in checks.items()
        ]
        return ReviewVerdict(findings=findings)

    def review_evidence(self, evidence: dict[str, object]) -> ReviewVerdict:
        """Produce review findings from build, graph, and verification evidence."""
        findings: list[ReviewFinding] = []
        graph_summary = evidence.get("task_graph_summary")
        verification_summary = evidence.get("verification_summary")
        escalation_bundle = evidence.get("escalation_bundle")
        diff_summary = evidence.get("diff_summary")
        spec_text = evidence.get("spec_text")
        acceptance_criteria = evidence.get("acceptance_criteria")

        if isinstance(spec_text, str) or isinstance(acceptance_criteria, list):
            has_spec = bool(spec_text.strip()) if isinstance(spec_text, str) else False
            has_criteria = bool(acceptance_criteria)
            findings.append(
                ReviewFinding(
                    check="spec_evidence",
                    passed=has_spec or has_criteria,
                    severity="major",
                    message=(
                        "spec or acceptance criteria available"
                        if has_spec or has_criteria
                        else "no spec or acceptance criteria available"
                    ),
                )
            )

        if isinstance(diff_summary, dict):
            changed_files = int(diff_summary.get("changed_files", 0) or 0)
            findings.append(
                ReviewFinding(
                    check="diff_evidence",
                    passed=changed_files > 0,
                    severity="major",
                    message=(
                        f"diff includes {changed_files} changed file(s)"
                        if changed_files > 0
                        else "no changed files detected for review"
                    ),
                )
            )

        if isinstance(graph_summary, dict):
            failed = int(graph_summary.get("failed", 0) or 0)
            waiting = int(graph_summary.get("waiting_human", 0) or 0)
            pending = int(graph_summary.get("pending", 0) or 0)
            findings.append(
                ReviewFinding(
                    check="graph_execution",
                    passed=failed == 0 and waiting == 0,
                    severity="critical" if waiting > 0 else "major",
                    message=(
                        "graph execution is clear"
                        if failed == 0 and waiting == 0
                        else f"graph has {failed} failed and {waiting} waiting-human node(s)"
                    ),
                )
            )
            findings.append(
                ReviewFinding(
                    check="graph_completion",
                    passed=pending == 0,
                    severity="minor",
                    message="graph completed" if pending == 0 else f"graph has {pending} pending node(s)",
                )
            )

        if isinstance(verification_summary, dict):
            command_ok = verification_summary.get("command_succeeded")
            lint_errors = int(verification_summary.get("lint_errors", 0) or 0)
            security_vulnerabilities = int(verification_summary.get("security_vulnerabilities", 0) or 0)
            findings.append(
                ReviewFinding(
                    check="verification_command",
                    passed=command_ok is not False,
                    severity="major",
                    message="verification command passed" if command_ok is not False else "verification command failed",
                )
            )
            findings.append(
                ReviewFinding(
                    check="lint_quality",
                    passed=lint_errors == 0,
                    severity="major",
                    message="lint passed" if lint_errors == 0 else f"lint reported {lint_errors} error(s)",
                )
            )
            findings.append(
                ReviewFinding(
                    check="security_scan",
                    passed=security_vulnerabilities == 0,
                    severity="critical",
                    message=(
                        "security scan passed"
                        if security_vulnerabilities == 0
                        else f"security scan found {security_vulnerabilities} vulnerability(ies)"
                    ),
                )
            )

        if isinstance(escalation_bundle, dict):
            findings.append(
                ReviewFinding(
                    check="escalation_bundle",
                    passed=False,
                    severity="major",
                    message=str(escalation_bundle.get("reason", "escalation bundle present")),
                )
            )

        if not findings:
            return self.review()
        return ReviewVerdict(findings=findings)
