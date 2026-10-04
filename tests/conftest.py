from datetime import timedelta

import pytest

from autolab import schemas as s
from autolab.ledger import ResearchLedger
from autolab.ledger_smoke import populate_demo


@pytest.fixture
def ledger(tmp_path):
    with ResearchLedger(tmp_path / "ledger.db") as value:
        yield value


@pytest.fixture
def records(ledger):
    demo = populate_demo(ledger)
    project, source, evidence, hypothesis = demo[:4]
    experiment = demo[6]
    link = dict(project_id=project.project_id, experiment_id=experiment.experiment_id)
    review = ledger.add_review(s.ReviewRecord(
        review_id=ledger.next_id("HREV"), project_id=project.project_id,
        review_type="hypothesis", target_type="Hypothesis", target_id=hypothesis.hypothesis_id,
        verdict="REVISE", reviewer_role="fixture critic",
        issues=[{"severity": "minor", "detail": {"missing": ["power estimate"]}}],
    ))
    resource = ledger.add_resource(s.ResourceRecord(
        resource_id=ledger.next_id("RES"), **link, resource_type="dataset", purpose="test input",
        path_or_uri="scratch/data.json", metadata={"dimensions": [2, 3], "synthetic": True},
    ))
    readiness = ledger.add_readiness_report(s.ReadinessReport(
        readiness_id=ledger.next_id("READY"), **link, resource_readiness=True,
        technical_readiness=True, scientific_readiness=False, quality_readiness=True,
        verdict="REPAIR", failed_checks=["Power estimate missing"],
    ))
    implementation = ledger.add_implementation(s.ImplementationRecord(
        implementation_id=ledger.next_id("IMPL"), **link, code_path="scratch/fixture.py",
        implementation_plan=["Load fixture", "Compare"], code_version="fixture-v1",
    ))
    started = s.utc_now()
    run = ledger.add_run(s.ExperimentRun(
        run_id=ledger.next_id("RUN"), **link, implementation_id=implementation.implementation_id,
        started_at=started, completed_at=started + timedelta(seconds=1), status="COMPLETED",
        random_seed=42, environment_metadata={"python": "fixture", "packages": ["stdlib"]},
        input_manifest={"files": [{"path": "data.json", "checksum": "synthetic"}]},
        output_manifest={"measurements": [0.1, 0.2]}, cost_usd=0.05,
    ))
    metric = ledger.add_metric(s.MetricRecord(
        metric_id=ledger.next_id("METRIC"), **link, run_id=run.run_id,
        metric_name="fixture_delta", metric_value=0.2, unit="fraction",
    ))
    analysis = ledger.add_analysis(s.ScientificAnalysis(
        analysis_id=ledger.next_id("ANALYSIS"), **link, run_id=run.run_id,
        hypothesis_assessment="INCONCLUSIVE", interpretation="Synthetic test only.",
        confidence=0.2, limitations=["No actual experiment ran"],
    ))
    cost = ledger.add_cost(s.CostRecord(
        cost_id=ledger.next_id("COST"), **link, category="fixture", estimated_usd=1,
        actual_usd=0.05, metadata={"line_items": [{"category": "compute", "usd": 0.05}]},
    ))
    # One representative instance of each of the sixteen canonical types.
    all_records = [project, source, evidence, hypothesis, review, demo[4], experiment,
                   resource, readiness, implementation, run, metric, analysis, demo[7], cost, demo[8]]
    return {type(record): record for record in all_records}
