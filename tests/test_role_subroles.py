from pathlib import Path

from src.engine import Complexity, Engine, Phase, TaskContext
from src.runtime.role_router import RoleSubrolePolicy


def test_role_subrole_policy_selects_extensible_domain_overlays():
    policy = RoleSubrolePolicy.from_skills_section(
        {
            "subroles": {
                "security_review": {
                    "description": "Security-sensitive review overlay.",
                    "applies_when": {
                        "keywords": ["auth", "token", "secret"],
                        "files": ["**/auth*.py", "**/security*.py"],
                    },
                    "compatible_base_roles": ["nirnaya", "prajna"],
                    "evidence_required": ["threat_model", "secret_scan"],
                    "review_mode": "adversarial_verification",
                },
                "network_architecture": {
                    "description": "Network design overlay.",
                    "applies_when": {"keywords": ["gateway", "tls", "proxy"]},
                    "compatible_base_roles": ["disha", "prajna"],
                    "evidence_required": ["topology_summary"],
                },
            }
        }
    )

    selections = policy.select(
        task_description="Review auth token rotation around the gateway",
        file_paths=["src/security.py"],
        base_roles=["nirnaya", "disha"],
    )

    assert [selection["key"] for selection in selections] == [
        "security_review",
        "network_architecture",
    ]
    assert selections[0]["base_role"] == "nirnaya"
    assert selections[0]["review_mode"] == "adversarial_verification"
    assert selections[0]["evidence_required"] == ["threat_model", "secret_scan"]
    assert "keyword:auth" in selections[0]["matched_by"]
    assert "file:**/security*.py" in selections[0]["matched_by"]
    assert selections[1]["base_role"] == "disha"


def test_role_subrole_policy_is_empty_without_subroles():
    policy = RoleSubrolePolicy.from_skills_section({"task_type_to_skill": {"bug_fix": {}}})

    assert policy.select(task_description="Fix auth bug", file_paths=["src/auth.py"]) == []


def test_route_harness_carries_policy_selected_subroles(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "skills.md").write_text(
        """# Skills

```yaml
subroles:
  security_review:
    applies_when:
      keywords: ["auth", "token", "permission"]
    compatible_base_roles: ["nirnaya", "prajna"]
    evidence_required: ["threat_model", "permission_boundary_checked"]
    review_mode: "adversarial_verification"
```
""",
        encoding="utf-8",
    )

    task = TaskContext(
        task_id="task-role-plan",
        description="Review auth token permission boundary",
        complexity=Complexity.LOW,
    )
    result = Engine(policy_pack_path=str(policy_dir)).run_task(task)
    route = next(phase for phase in result.phase_results if phase.phase == Phase.ROUTE)

    role_plan = route.artifacts["role_plan"]
    assert role_plan["selected_subroles"][0]["key"] == "security_review"
    assert role_plan["selected_subroles"][0]["base_role"] == "nirnaya"
    assert role_plan["selected_subroles"][0]["evidence_required"] == [
        "threat_model",
        "permission_boundary_checked",
    ]
    assert route.artifacts["harness_config"]["role_plan"] == role_plan
