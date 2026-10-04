from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from autolab import schemas as s
from autolab.ledger.serialization import deserialize, serialize

SCORES = [
    (s.EvidenceRecord, "confidence"),
    (s.Hypothesis, "novelty_score"), (s.Hypothesis, "testability_score"),
    (s.Hypothesis, "scientific_value_score"),
    (s.ExperimentCandidate, "expected_information_gain"), (s.ExperimentCandidate, "feasibility_score"),
    (s.ExperimentSpec, "expected_information_gain"),
    (s.ScientificAnalysis, "confidence"),
    (s.NextDecision, "expected_information_gain"), (s.NextDecision, "goal_alignment"),
]


@pytest.mark.parametrize("model,field", SCORES)
@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf")])
def test_scores_reject_outside_range(records, model, field, bad):
    data = records[model].model_dump()
    data[field] = bad
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model,field", SCORES)
@pytest.mark.parametrize("boundary", [0, 1])
def test_score_boundaries(records, model, field, boundary):
    data = records[model].model_dump()
    data[field] = boundary
    assert getattr(model.model_validate(data), field) == boundary


@pytest.mark.parametrize("model,field", [
    (s.ResearchCharter, "status"), (s.Hypothesis, "status"),
    (s.ExperimentSpec, "status"), (s.ExperimentRun, "status"),
    (s.ReviewRecord, "verdict"), (s.ReadinessReport, "verdict"),
    (s.ScientificAnalysis, "hypothesis_assessment"), (s.NextDecision, "action"),
])
def test_invalid_enum(records, model, field):
    data = records[model].model_dump()
    data[field] = "INVALID_VALUE"
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("model", [
    s.ResearchCharter, s.SourceRecord, s.EvidenceRecord, s.Hypothesis, s.ReviewRecord,
    s.ExperimentCandidate, s.ExperimentSpec, s.ResourceRecord, s.ReadinessReport,
    s.ImplementationRecord, s.ExperimentRun, s.MetricRecord, s.ScientificAnalysis,
    s.NextDecision, s.CostRecord, s.EventRecord,
])
def test_required_project_id_and_extra_fields(records, model):
    data = records[model].model_dump()
    data["project_id"] = "  "
    with pytest.raises(ValidationError):
        model.model_validate(data)
    data = records[model].model_dump()
    data["unexpected"] = "field"
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_charter_immutable(records):
    with pytest.raises(ValidationError):
        records[s.ResearchCharter].objective = "Changed research goal"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_nonnegative_budgets(records, bad):
    with pytest.raises(ValidationError):
        s.ResearchCharter.model_validate({**records[s.ResearchCharter].model_dump(), "budget_usd": bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "0.2"])
def test_metrics_require_finite_numbers(records, bad):
    with pytest.raises(ValidationError):
        s.MetricRecord.model_validate({**records[s.MetricRecord].model_dump(), "metric_value": bad})


def test_timestamps_normalize_and_reject_naive(records):
    data = records[s.EventRecord].model_dump()
    aware = datetime(2026, 10, 3, 12, tzinfo=timezone(timedelta(hours=-4)))
    event = s.EventRecord.model_validate({**data, "created_at": aware})
    assert event.created_at.hour == 16 and event.created_at.utcoffset() == timedelta(0)
    with pytest.raises(ValidationError):
        s.EventRecord.model_validate({**data, "created_at": aware.replace(tzinfo=None)})


def test_run_timestamp_order(records):
    run = records[s.ExperimentRun]
    with pytest.raises(ValidationError):
        s.ExperimentRun.model_validate({**run.model_dump(), "completed_at": run.started_at - timedelta(seconds=1)})


def test_serialization_revalidates_bypassed_mutation(records):
    bad = records[s.ScientificAnalysis].model_copy(update={"confidence": 2})
    with pytest.raises(ValidationError):
        serialize(bad)
    source = records[s.SourceRecord].model_copy(deep=True)
    source.metadata["invalid_nested_number"] = float("nan")
    with pytest.raises((ValidationError, ValueError)):
        serialize(source)


def test_json_round_trip_all_fields(records):
    for model, record in records.items():
        assert deserialize(model, serialize(record)) == record


def test_unknown_payload_values(records):
    data = records[s.SourceRecord].model_dump()
    data["metadata"] = {"not_json": object()}
    with pytest.raises(ValidationError):
        s.SourceRecord.model_validate(data)


def test_evidence_reference_lists(records):
    hypothesis = records[s.Hypothesis]
    evidence_id = hypothesis.supporting_evidence_ids[0]
    for change in ({"supporting_evidence_ids": [evidence_id, evidence_id]}, {"contradicting_evidence_ids": [evidence_id]}):
        with pytest.raises(ValidationError):
            s.Hypothesis.model_validate({**hypothesis.model_dump(), **change})
