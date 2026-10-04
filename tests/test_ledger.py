import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from autolab import schemas as s
from autolab.config import PROJECT_ROOT, ledger_path
from autolab.ids import ID_PREFIXES
from autolab.ledger import ResearchLedger
from autolab.ledger.database import TABLE_COLUMNS
from autolab.ledger.repository import TABLES
from autolab.ledger_smoke import populate_demo, verify_demo


def test_initialization_is_idempotent(ledger):
    ledger.initialize()
    conn = ledger.database.connection
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLE_COLUMNS) <= names
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {f"idx_{name}_project" for name in TABLE_COLUMNS if name != "projects"} <= indexes


def test_round_trip_every_model_and_project_listing(ledger, records):
    for model, record in records.items():
        table = TABLES[model]
        assert ledger.get(model, getattr(record, table.id_field)) == record
        assert record in ledger.list_records(model, record.project_id)
        assert ledger.list_records(model, "PROJECT_MISSING") == []
    assert ledger.database.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_missing_record_returns_none(ledger):
    assert ledger.get_project("PROJECT_MISSING") is None
    assert ledger.get_hypothesis("HYP_MISSING", version=1) is None
    assert ledger.get_experiment("EXP_MISSING") is None
    assert ledger.get_run("RUN_MISSING") is None


def test_foreign_project_and_source(ledger, records):
    evidence = records[s.EvidenceRecord]
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_evidence(evidence.model_copy(update={"evidence_id": "EVID_BAD", "source_id": "SRC_MISSING"}))
    other = records[s.ResearchCharter].model_copy(update={"project_id": "PROJECT_0002"})
    ledger.create_project(other)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_evidence(evidence.model_copy(update={"evidence_id": "EVID_CROSS", "project_id": other.project_id}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_source(records[s.SourceRecord].model_copy(update={"source_id": "SRC_BAD", "project_id": "PROJECT_MISSING"}))


def test_hypothesis_evidence_save_rolls_back(ledger, records):
    original = records[s.Hypothesis]
    invalid = original.model_copy(update={"hypothesis_id": "HYP_BAD", "supporting_evidence_ids": ["EVID_MISSING"]})
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_hypothesis(invalid)
    assert ledger.get_hypothesis("HYP_BAD") is None
    assert not ledger.database.connection.in_transaction
    ledger.add_hypothesis(original.model_copy(update={"hypothesis_id": "HYP_GOOD"}))


def test_versions_are_preserved_and_pinned(ledger, records):
    hypothesis = records[s.Hypothesis]
    newer_hypothesis = ledger.add_hypothesis(hypothesis.model_copy(update={"version": 2, "statement": "Refined prediction"}))
    assert ledger.get_hypothesis(hypothesis.hypothesis_id) == newer_hypothesis
    assert ledger.get_hypothesis(hypothesis.hypothesis_id, version=1) == hypothesis
    experiment = records[s.ExperimentSpec]
    newer_experiment = ledger.add_experiment_spec(experiment.model_copy(update={"version": 2, "hypothesis_version": 2, "controls": {"max_attempts": 5}}))
    assert ledger.get_experiment(experiment.experiment_id) == newer_experiment
    assert ledger.get_experiment(experiment.experiment_id, version=1) == experiment
    assert ledger.get_run(records[s.ExperimentRun].run_id).experiment_version == 1
    assert len(ledger.list_hypotheses(hypothesis.project_id)) == 2
    assert len(ledger.list_experiments(experiment.project_id)) == 2
    for bad_version in (1, 2, 4):
        with pytest.raises(ValueError):
            ledger.add_hypothesis(hypothesis.model_copy(update={"version": bad_version}))
    with pytest.raises(ValueError):
        ledger.add_experiment_spec(experiment.model_copy(update={"experiment_id": "EXP_NEW", "version": 2}))


def test_version_project_cannot_change(ledger, records):
    charter = records[s.ResearchCharter]
    ledger.create_project(charter.model_copy(update={"project_id": "PROJECT_0002"}))
    hypothesis = records[s.Hypothesis]
    with pytest.raises(ValueError):
        ledger.add_hypothesis(hypothesis.model_copy(update={"project_id": "PROJECT_0002", "version": 2, "supporting_evidence_ids": []}))


def test_exact_experiment_and_run_links(ledger, records):
    experiment = records[s.ExperimentSpec]
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_experiment_spec(experiment.model_copy(update={"experiment_id": "EXP_BAD", "hypothesis_version": 999}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_resource(records[s.ResourceRecord].model_copy(update={"resource_id": "RES_BAD", "experiment_version": 999}))
    other = ledger.add_experiment_spec(experiment.model_copy(update={"experiment_id": "EXP_OTHER"}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_run(records[s.ExperimentRun].model_copy(update={"run_id": "RUN_BAD", "experiment_id": other.experiment_id}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_metric(records[s.MetricRecord].model_copy(update={"metric_id": "METRIC_BAD", "experiment_id": other.experiment_id}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_analysis(records[s.ScientificAnalysis].model_copy(update={"analysis_id": "ANALYSIS_BAD", "run_id": "RUN_MISSING"}))


def test_reviews_validate_polymorphic_targets(ledger, records):
    review = records[s.ReviewRecord]
    for updates in ({"target_id": "HYP_MISSING"}, {"target_version": 999}):
        with pytest.raises(sqlite3.IntegrityError):
            ledger.add_review(review.model_copy(update={"review_id": "HREV_BAD", **updates}))
    with pytest.raises(ValueError):
        ledger.add_review(review.model_copy(update={"review_id": "HREV_BAD", "target_type": "unknown"}))
    charter = records[s.ResearchCharter]
    ledger.create_project(charter.model_copy(update={"project_id": "PROJECT_OTHER"}))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.add_review(review.model_copy(update={"review_id": "HREV_CROSS", "project_id": "PROJECT_OTHER"}))


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
def test_all_scientific_tables_reject_overwrites(ledger, records, operation):
    conn = ledger.database.connection
    for model, record in records.items():
        table = TABLES[model]
        identifier = getattr(record, table.id_field)
        if operation == "UPDATE":
            sql = f"UPDATE {table.name} SET record_json = record_json WHERE {table.id_field} = ?"
        elif operation == "DELETE":
            sql = f"DELETE FROM {table.name} WHERE {table.id_field} = ?"
        else:
            sql = f"INSERT OR REPLACE INTO {table.name} SELECT * FROM {table.name} WHERE {table.id_field} = ?"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, (identifier,))
        assert ledger.get(model, identifier) == record
    for operation in ("UPDATE hypothesis_evidence SET relationship='contradicts'", "DELETE FROM hypothesis_evidence"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(operation)


def test_duplicate_charters_and_audit_ids_are_rejected(ledger, records):
    for model in (s.ResearchCharter, s.ExperimentRun, s.NextDecision, s.EventRecord):
        with pytest.raises(sqlite3.IntegrityError):
            ledger.add(records[model])


def test_chronological_audit_order_with_ties(ledger, records):
    event = records[s.EventRecord]
    base = s.utc_now() + timedelta(days=1)
    for identifier, created in (("EVENT_LATE", base + timedelta(seconds=1)), ("EVENT_EARLY", base), ("EVENT_TIE", base)):
        ledger.add_event(event.model_copy(update={"event_id": identifier, "created_at": created}))
    assert [e.event_id for e in ledger.list_events(event.project_id)[-3:]] == ["EVENT_EARLY", "EVENT_TIE", "EVENT_LATE"]


def test_database_reopens_with_identical_objects(tmp_path):
    path = tmp_path / "restart.db"
    with ResearchLedger(path) as ledger:
        expected = populate_demo(ledger)
        assert ledger.next_id("SRC") == "SRC_0002"
    with ResearchLedger(path) as ledger:
        verify_demo(ledger, expected)
        assert ledger.next_id("SRC") == "SRC_0003"


def test_new_python_process_can_read_every_type(ledger, records):
    path = ledger.database.path
    expected = []
    for model, record in records.items():
        table = TABLES[model]
        expected.append({"type": model.__name__, "id": getattr(record, table.id_field), "record": record.model_dump(mode="json")})
    ledger.close()
    # Restore fixture ownership after reopening; child uses an independent
    # Python interpreter and connection, not a cached in-process object.
    ledger.database = type(ledger.database)(path)
    code = """
import json, sys
from autolab.ledger import ResearchLedger
from autolab.ledger.repository import TABLES
with ResearchLedger(sys.argv[1]) as ledger:
    result=[]
    for model, table in TABLES.items():
        rows=ledger.list_records(model, 'PROJECT_0001')
        if rows:
            row=rows[0]
            identifier=getattr(row,table.id_field)
            assert ledger.get(model,identifier) == row
            result.append({'type':model.__name__,'id':identifier,'record':row.model_dump(mode='json')})
    print(json.dumps(result))
"""
    child = subprocess.run([sys.executable, "-c", code, path], capture_output=True, text=True, check=True, timeout=20)
    assert {r["type"]: r for r in json.loads(child.stdout)} == {r["type"]: r for r in expected}


def test_id_prefixes_and_manual_id_collision(ledger, records):
    assert ledger.next_id("PROJECT") == "PROJECT_0002"
    for prefix in ID_PREFIXES - {"PROJECT"}:
        identifier = ledger.next_id(prefix)
        assert identifier.startswith(prefix + "_") and identifier.rsplit("_", 1)[1].isdigit()
    with pytest.raises(ValueError):
        ledger.next_id("NOT_AN_ID_PREFIX")


def test_atomic_concurrent_id_generation(tmp_path):
    path = tmp_path / "concurrent.db"
    with ResearchLedger(path):
        pass
    def reserve(_):
        with ResearchLedger(path) as ledger:
            return [ledger.next_id("EVENT") for _ in range(20)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        identifiers = [identifier for batch in workers.map(reserve, range(4)) for identifier in batch]
    assert len(identifiers) == len(set(identifiers)) == 80
    assert sorted(int(identifier.split("_")[1]) for identifier in identifiers) == list(range(1, 81))


def test_cost_can_be_project_level(ledger, records):
    record = records[s.CostRecord].model_copy(update={"cost_id": "COST_PROJECT", "experiment_id": None})
    assert ledger.add_cost(record).experiment_id is None


def test_default_and_overridden_database_path(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTOLAB_LEDGER_PATH", raising=False)
    assert ledger_path() == PROJECT_ROOT / "research_state/autolab.db"
    custom = tmp_path / "nested" / "override.db"
    monkeypatch.setenv("AUTOLAB_LEDGER_PATH", str(custom))
    with ResearchLedger() as ledger:
        assert ledger.database.path == str(custom)
    assert custom.is_file()


def test_future_schema_version_rejected(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    ledger = ResearchLedger(path)
    try:
        with pytest.raises(RuntimeError, match="Unsupported ledger schema"):
            ledger.initialize()
    finally:
        ledger.close()


def test_transaction_rolls_back_on_error(ledger):
    with pytest.raises(RuntimeError):
        with ledger.database.transaction() as connection:
            connection.execute("INSERT INTO id_counters VALUES ('TEMP', 1)")
            raise RuntimeError("Rollback test")
    assert ledger.database.connection.execute("SELECT * FROM id_counters WHERE prefix='TEMP'").fetchone() is None
