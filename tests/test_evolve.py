import pytest
from datetime import datetime
from src.evolve import Evolver, Pattern, EvolveBaseline, PolicyProposal, ProposalReviewStore
from src.runtime.learning import LearningRecord


def test_pattern_pass_gate():
    evolver = Evolver()
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.9,
    )
    assert evolver.should_promote(pattern) is True


def test_pattern_fails_below_gate():
    evolver = Evolver()
    pattern = Pattern(
        name="test-pattern",
        first_seen=datetime.now(),
        pass_rate=0.5,
    )
    assert evolver.should_promote(pattern) is False


def test_policy_proposal_to_artifact_shape():
    proposal = PolicyProposal(
        title="Add Verify failure recovery guidance",
        policy_file="commands.md",
        rationale="Verify recorded repeated failures.",
        suggested_change="Add a root-cause checklist.",
        evidence_refs=["task-1:repeated_failures:Verify"],
        confidence=0.7,
        source="repeated_failures",
    )

    artifact = proposal.to_artifact()

    assert artifact["id"] == proposal.proposal_id
    assert artifact["title"] == "Add Verify failure recovery guidance"
    assert artifact["policy_file"] == "commands.md"
    assert artifact["evidence_refs"] == ["task-1:repeated_failures:Verify"]
    assert artifact["confidence"] == 0.7
    assert artifact["source"] == "repeated_failures"
    assert artifact["routing_hint"] == {}


def test_generates_policy_proposals_from_learning_record_signals():
    evolver = Evolver()
    records = [
        LearningRecord(
            task_id="task-1",
            complexity="high",
            generated_at="2026-04-23T10:00:00",
            summary="Verify failed repeatedly.",
            repeated_failures=[{"phase": "Verify", "count": 2}],
            escalations=[{"phase": "Review", "count": 2}],
            iteration_hotspots=[{"phase": "Build", "iterations": 3}],
        )
    ]

    proposals = evolver.generate_policy_proposals(learning_records=records)
    proposals_by_source = {proposal.source: proposal for proposal in proposals}

    assert set(proposals_by_source) == {
        "iteration_hotspots",
        "repeated_failures",
        "escalations",
    }
    assert proposals_by_source["iteration_hotspots"].title == "Reduce Build iteration hotspot"
    assert proposals_by_source["iteration_hotspots"].policy_file == "commands.md"
    assert proposals_by_source["repeated_failures"].title == "Add Verify failure recovery guidance"
    assert proposals_by_source["repeated_failures"].policy_file == "commands.md"
    assert proposals_by_source["escalations"].title == "Tighten Review escalation criteria"
    assert proposals_by_source["escalations"].policy_file == "escalation.md"


def test_generates_model_routing_proposal_from_provider_failures():
    evolver = Evolver()
    records = [
        LearningRecord(
            task_id="task-routing",
            complexity="high",
            generated_at="2026-04-23T10:00:00",
            summary="Codex failed repeatedly in Verify.",
            provider_failures=[{"phase": "Verify", "provider": "codex", "count": 2}],
        )
    ]

    proposals = evolver.generate_policy_proposals(learning_records=records)
    provider_proposal = next(
        proposal for proposal in proposals if proposal.source == "provider_failures"
    )

    assert provider_proposal.title == "Reroute Verify away from codex"
    assert provider_proposal.policy_file == "model-routing.md"
    assert provider_proposal.routing_hint["phase"] == "Verify"
    assert provider_proposal.routing_hint["preferred_provider"] == "local"


def test_generates_policy_proposals_from_repeated_signals_across_records():
    evolver = Evolver()
    records = [
        {"task_id": "task-1", "escalations": [{"phase": "Plan", "count": 1}]},
        {"task_id": "task-2", "escalations": [{"phase": "Plan", "count": 1}]},
    ]

    proposals = evolver.propose_from_learning_records(records)

    assert len(proposals) == 1
    assert proposals[0].title == "Tighten Plan escalation criteria"
    assert proposals[0].evidence_refs == [
        "task-1:escalations:Plan",
        "task-2:escalations:Plan",
    ]


def test_does_not_propose_for_single_learning_signal():
    evolver = Evolver()
    records = [
        LearningRecord(
            task_id="task-1",
            complexity="low",
            generated_at="2026-04-23T10:00:00",
            summary="One review escalation.",
            escalations=[{"phase": "Review", "count": 1}],
        )
    ]

    assert evolver.generate_policy_proposals(learning_records=records) == []


def test_generates_policy_proposals_from_promoted_patterns_only():
    evolver = Evolver()
    promoted = Pattern(
        name="verify-before-review",
        first_seen=datetime.now(),
        pass_rate=0.9,
        evidence_refs=["task-7"],
    )
    weak = Pattern(
        name="skip-verification",
        first_seen=datetime.now(),
        pass_rate=0.4,
        evidence_refs=["task-8"],
    )

    proposals = evolver.generate_policy_proposals(patterns=[weak, promoted])

    assert len(proposals) == 1
    assert proposals[0].title == "Promote learned pattern: verify-before-review"
    assert proposals[0].policy_file == "conventions.md"
    assert proposals[0].source == "pattern"
    assert proposals[0].evidence_refs == ["task-7"]


def test_proposal_review_store_accepts_and_records_policy_update(tmp_path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text("# Commands\n")
    proposal = PolicyProposal(
        title="Add Verify failure recovery guidance",
        policy_file="commands.md",
        rationale="Verify failed repeatedly.",
        suggested_change="Add root-cause capture before retry.",
        evidence_refs=["task-1:repeated_failures:Verify"],
        confidence=0.8,
        source="repeated_failures",
    )

    decision = ProposalReviewStore(policy_dir).accept(proposal)

    assert decision["status"] == "accepted"
    policy_text = (policy_dir / "commands.md").read_text()
    assert "Accepted Sarathi Proposal" in policy_text
    assert proposal.proposal_id in policy_text
    assert (policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json").exists()


def test_proposal_review_store_persists_routing_hint_metadata(tmp_path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "model-routing.md").write_text("# Model Routing\n")
    proposal = PolicyProposal(
        title="Reroute Verify away from codex",
        policy_file="model-routing.md",
        rationale="codex failed repeatedly in Verify.",
        suggested_change="Prefer local for Verify.",
        routing_hint={"phase": "Verify", "preferred_provider": "local"},
        source="provider_failures",
    )

    decision = ProposalReviewStore(policy_dir).accept(proposal)

    assert decision["routing_hint"]["phase"] == "Verify"
    stored = (policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json").read_text()
    assert '"routing_hint"' in stored


def test_proposal_review_store_applies_to_existing_yaml_block(tmp_path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text(
        """# Commands

```yaml
test:
  command: pytest
```
"""
    )
    proposal = PolicyProposal(
        title="Add Verify failure recovery guidance",
        policy_file="commands.md",
        rationale="Verify failed repeatedly.",
        suggested_change="Add root-cause capture before retry.",
    )

    ProposalReviewStore(policy_dir).accept(proposal)

    policy_text = (policy_dir / "commands.md").read_text()
    assert "accepted_proposals:" in policy_text
    assert proposal.proposal_id in policy_text
    assert "Accepted Sarathi Proposal" not in policy_text


def test_proposal_review_store_rejects_without_policy_mutation(tmp_path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "review.md").write_text("# Review\n")
    proposal = PolicyProposal(
        title="Tighten Review escalation criteria",
        policy_file="review.md",
        rationale="Review escalated repeatedly.",
        suggested_change="Clarify stop conditions.",
    )

    decision = ProposalReviewStore(policy_dir).reject(proposal, reason="Already covered")

    assert decision["status"] == "rejected"
    assert (policy_dir / "review.md").read_text() == "# Review\n"
    assert (policy_dir / ".sarathi-proposals" / f"{proposal.proposal_id}.json").exists()
