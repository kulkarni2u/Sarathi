from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

from src.dispatch import LocalDispatcher
from src.engine import Complexity, Engine, PersistenceManager, Phase, TaskContext
from src.policy import CompiledPolicyData, compile_policy_pack
from src.runtime import ArtifactStore, DispatchRequest, DispatchResponse, GateResult


def test_runtime_contracts_are_typed():
    request = DispatchRequest(
        mode="explore",
        task_id="task-1",
        phase="Brainstorm",
        prompt="Explore options",
        expected_outputs=["approaches"],
    )
    response = DispatchResponse(success=True, outputs={"approaches": []})
    gate = GateResult(passed=True, score=1.0, threshold=0.9)

    assert request.mode == "explore"
    assert response.success is True
    assert gate.decision == "pass"


def test_compile_policy_pack_loads_yaml_sections(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: "pytest -q"
```
"""
    )

    compiled = compile_policy_pack(str(policy_dir))
    assert compiled.get("commands") == {"test": {"command": "pytest -q"}}


def test_packaged_skill_policy_files_include_current_templates():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    data_files = pyproject["tool"]["setuptools"]["data-files"]

    example_files = set(data_files["share/sarathi/skill/policy-pack/EXAMPLE"])
    template_files = set(data_files["share/sarathi/skill/policy-pack/TEMPLATE"])

    assert "skill/policy-pack/EXAMPLE/workflow-patterns.md" in example_files
    assert "skill/policy-pack/TEMPLATE/permissions.md" in template_files
    assert "skill/policy-pack/TEMPLATE/workflow-patterns.md" in template_files


def test_compile_policy_pack_loads_accepted_proposal_feedback(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    review_dir = policy_dir / ".sarathi-proposals"
    review_dir.mkdir(parents=True)
    (review_dir / "abc.json").write_text(
        '{"id": "abc", "status": "accepted", "title": "Add Verify failure recovery guidance", "source": "repeated_failures"}'
    )

    compiled = compile_policy_pack(str(policy_dir))

    feedback = compiled.get("learning_feedback")
    assert feedback["accepted_proposals"][0]["id"] == "abc"


def test_compile_policy_pack_exposes_typed_sections_without_breaking_dict_access(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: "pytest -q"
lint:
  command: "ruff check ."
```
"""
    )

    compiled = compile_policy_pack(str(policy_dir))

    assert isinstance(compiled.typed_get("commands"), CompiledPolicyData)
    assert compiled.typed_get("commands").get("test") == {"command": "pytest -q"}
    assert compiled.get_section("commands") is not None
    assert compiled.get_section("commands").get("lint") == {"command": "ruff check ."}
    assert compiled.get("commands") == {
        "test": {"command": "pytest -q"},
        "lint": {"command": "ruff check ."},
    }


def test_artifact_store_persists_phase_outputs(tmp_path: Path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    artifact_ref = store.save_phase_artifacts(
        task_id="task-1",
        phase="Plan",
        artifacts={"implementation_plan": {"steps": ["one"]}},
        evidence={"checkpoint_list": True},
    )

    assert artifact_ref is not None
    assert Path(artifact_ref).exists()
    assert '"checkpoint_list": true' in Path(artifact_ref).read_text().lower()


def test_artifact_store_uses_unique_refs_for_repeated_phase_saves(tmp_path: Path):
    store = ArtifactStore(str(tmp_path / "artifacts"))

    refs = [
        store.save_phase_artifacts("task-1", "Verify", {"attempt": index})
        for index in range(3)
    ]

    assert len(set(refs)) == 3
    assert all(ref is not None and Path(ref).exists() for ref in refs)


def test_engine_persists_artifact_refs_and_gate_results(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: "pytest -q"
```
"""
    )

    task = TaskContext(
        task_id="task-1",
        description="Add auth flow",
        complexity=Complexity.HIGH,
    )
    engine = Engine(policy_pack_path=str(policy_dir), dispatcher=LocalDispatcher())
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))
    engine.artifact_store = ArtifactStore(str(tmp_path / "artifacts"))

    result = engine.run_task(task)

    brainstorm = next(pr for pr in result.phase_results if pr.phase == Phase.BRAINSTORM)
    plan = next(pr for pr in result.phase_results if pr.phase == Phase.PLAN)

    assert brainstorm.artifact_refs
    assert plan.artifact_refs
    assert "gate_result" in brainstorm.artifacts
    assert "gate_result" in plan.artifacts
    assert brainstorm.artifacts["dispatch_artifacts"]["provider"] == "local"
    assert plan.artifacts["dispatch_artifacts"]["provider"] == "local"


def test_engine_uses_model_routing_provider_config_by_default(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "model-routing.md").write_text(
        """# Model Routing

```yaml
provider: acme
providers:
  - acme
```
"""
    )

    task = TaskContext(
        task_id="task-provider",
        description="Add auth flow",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    result = engine.run_task(task)

    brainstorm = next(pr for pr in result.phase_results if pr.phase == Phase.BRAINSTORM)

    assert brainstorm.artifacts["dispatch_artifacts"]["provider"] == "acme"


def test_engine_uses_accepted_learning_feedback_to_adjust_phase_provider(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "model-routing.md").write_text(
        """# Model Routing

```yaml
provider: local
providers:
  - local
  - acme
```
"""
    )
    review_dir = policy_dir / ".sarathi-proposals"
    review_dir.mkdir()
    (review_dir / "routing.json").write_text(
        """
{"id":"routing","status":"accepted","title":"Reroute Brainstorm away from local","source":"provider_failures","routing_hint":{"phase":"Brainstorm","preferred_provider":"acme"}}
""".strip()
    )

    task = TaskContext(
        task_id="task-routing-feedback",
        description="Explore auth flow",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    result = engine.run_task(task)

    brainstorm = next(pr for pr in result.phase_results if pr.phase == Phase.BRAINSTORM)
    plan = next(pr for pr in result.phase_results if pr.phase == Phase.PLAN)

    assert brainstorm.artifacts["dispatch_artifacts"]["provider"] == "acme"
    assert plan.artifacts["dispatch_artifacts"]["provider"] == "local"
