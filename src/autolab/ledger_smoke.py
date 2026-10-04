"""Isolated ledger demo; no LLM calls or persistent workspace artifacts."""
from pathlib import Path
from tempfile import TemporaryDirectory

from autolab import schemas as s
from autolab.ledger import ResearchLedger


def populate_demo(ledger: ResearchLedger) -> list[s.Record]:
    project_id = ledger.next_id("PROJECT")
    project = ledger.create_project(s.ResearchCharter(
        project_id=project_id, title="Recovery reliability",
        research_question="Does error-aware recovery outperform blind retry?",
        objective="Compare recovery strategies", primary_outcome="Task success rate",
        success_criteria={"improvement": {"minimum": 0.1, "unit": "fraction"}},
        constraints={"local_only": True, "max_attempts": 3},
        budget_usd=25, max_runtime_minutes=30,
        stop_conditions=["Budget exhausted", "Preregistered trials complete"],
    ))
    source = ledger.add_source(s.SourceRecord(
        source_id=ledger.next_id("SRC"), project_id=project_id,
        title="Synthetic setup source", authors=["AutoLab smoke test"],
        metadata={"synthetic": True, "nested": {"labels": ["test", None, 1]}},
    ))
    evidence = ledger.add_evidence(s.EvidenceRecord(
        evidence_id=ledger.next_id("EVID"), project_id=project_id, source_id=source.source_id,
        claim="A recovery strategy can use error categories.",
        supporting_text="Synthetic fixture; no real scientific evidence claimed.",
        location="fixture paragraph 1", confidence=0.5, tags=["synthetic"],
    ))
    hypothesis = ledger.add_hypothesis(s.Hypothesis(
        hypothesis_id=ledger.next_id("HYP"), project_id=project_id,
        statement="Error-aware recovery improves success rate.",
        supporting_evidence_ids=[evidence.evidence_id],
        falsifiable_prediction="Success rate exceeds blind retry by at least 0.1.",
        testability_score=0.8,
    ))
    candidates = [ledger.add_experiment_candidate(s.ExperimentCandidate(
        candidate_id=ledger.next_id("CAND"), project_id=project_id,
        hypothesis_id=hypothesis.hypothesis_id, title=title,
        objective="Estimate recovery success", approach=approach,
        expected_information_gain=gain, feasibility_score=0.9,
    )) for title, approach, gain in (
        ("Paired synthetic failures", "Paired comparison", 0.8),
        ("Unpaired synthetic failures", "Independent comparison", 0.5),
    )]
    experiment = ledger.add_experiment_spec(s.ExperimentSpec(
        experiment_id=ledger.next_id("EXP"), project_id=project_id,
        hypothesis_id=hypothesis.hypothesis_id, title=candidates[0].title,
        objective="Estimate paired success-rate improvement", experiment_type="paired_comparison",
        independent_variables={"recovery_strategy": ["error_aware", "blind_retry"]},
        dependent_variables={"success": "boolean"}, controls={"max_attempts": 3},
        dataset_requirements={"synthetic": True, "error_classes": ["timeout", "format"]},
        required_capabilities=["deterministic Python"], primary_metric="success_rate_delta",
        success_criteria={"success_rate_delta": {"gte": 0.1}},
        falsification_criteria={"success_rate_delta": {"lte": 0.0}},
        assumptions=["Same tasks in both conditions"], estimated_cost_usd=1,
    ))
    decision = ledger.add_decision(s.NextDecision(
        decision_id=ledger.next_id("DEC"), project_id=project_id,
        action=s.PlannerAction.PREPARE_RESOURCES, target_agent="resource_preparation",
        reason="Selected scientific contract needs data.",
        required_context_ids=[experiment.experiment_id], remaining_budget_usd=25,
    ))
    events = [ledger.add_event(s.EventRecord(
        event_id=ledger.next_id("EVENT"), project_id=project_id,
        event_type=kind, actor="ledger_smoke", target_type=target_type,
        target_id=target_id, summary=summary, payload=payload,
    )) for kind, target_type, target_id, summary, payload in (
        ("PROJECT_CREATED", "projects", project_id, "Created synthetic project", {"synthetic": True}),
        ("EVIDENCE_ADDED", "evidence", evidence.evidence_id, "Added synthetic evidence", {"source_id": source.source_id}),
        ("HYPOTHESIS_CREATED", "hypotheses", hypothesis.hypothesis_id, "Stored test hypothesis", {"version": 1}),
        ("EXPERIMENT_SELECTED", "experiments", experiment.experiment_id, "Stored scientific contract", {"candidate_id": candidates[0].candidate_id}),
        ("PLANNER_DECISION", "decisions", decision.decision_id, "Stored fixture decision; no planner executed", {"action": decision.action.value}),
    )]
    return [project, source, evidence, hypothesis, *candidates, experiment, decision, *events]


def verify_demo(ledger: ResearchLedger, expected: list[s.Record]) -> None:
    from autolab.ledger.repository import TABLES
    for record in expected:
        table = TABLES[type(record)]
        kwargs = {"version": record.version} if table.versioned else {}
        restored = ledger.get(type(record), getattr(record, table.id_field), **kwargs)
        assert restored == record
    project_id = expected[0].project_id
    assert ledger.list_evidence(project_id)[0].source_id == ledger.list_sources(project_id)[0].source_id
    assert ledger.list_hypotheses(project_id)[0].supporting_evidence_ids == [ledger.list_evidence(project_id)[0].evidence_id]
    assert ledger.list_experiments(project_id)[0].hypothesis_id == ledger.list_hypotheses(project_id)[0].hypothesis_id
    assert ledger.list_events(project_id) == sorted(ledger.list_events(project_id), key=lambda event: event.created_at)
    assert ledger.database.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def main() -> None:
    with TemporaryDirectory(prefix="autolab-ledger-") as directory:
        path = Path(directory) / "smoke.db"
        with ResearchLedger(path) as ledger:
            records = populate_demo(ledger)
        with ResearchLedger(path) as ledger:
            verify_demo(ledger, records)
            project_id = records[0].project_id
            print("AUTOLAB_LEDGER_OK")
            print(f"Project: {project_id}")
            for name, listing in (
                ("Sources", ledger.list_sources), ("Evidence", ledger.list_evidence),
                ("Hypotheses", ledger.list_hypotheses),
                ("Experiment candidates", ledger.list_experiment_candidates),
                ("Experiments", ledger.list_experiments), ("Decisions", ledger.list_decisions),
                ("Events", ledger.list_events),
            ):
                print(f"{name}: {len(listing(project_id))}")


if __name__ == "__main__":
    main()
