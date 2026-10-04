"""Domain-level insertion and reads. No updates or implicit overwrites."""
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from autolab import schemas as s
from autolab.ids import reserve_id
from .database import LedgerDatabase
from .serialization import deserialize, serialize

T = TypeVar("T", bound=s.Record)


@dataclass(frozen=True)
class Table:
    name: str
    id_field: str
    links: tuple[str, ...] = ()
    versioned: bool = False
    timestamp: str = "created_at"


EXPERIMENT_LINKS = ("experiment_id", "experiment_version")
TABLES = {
    s.ResearchCharter: Table("projects", "project_id"),
    s.SourceRecord: Table("sources", "source_id", timestamp="retrieved_at"),
    s.EvidenceRecord: Table("evidence", "evidence_id", ("source_id",)),
    s.Hypothesis: Table("hypotheses", "hypothesis_id", versioned=True),
    s.ReviewRecord: Table("reviews", "review_id", ("target_type", "target_id", "target_version")),
    s.ExperimentCandidate: Table("experiment_candidates", "candidate_id", ("hypothesis_id", "hypothesis_version"), versioned=True),
    s.ExperimentSpec: Table("experiments", "experiment_id", ("hypothesis_id", "hypothesis_version"), versioned=True),
    s.ResourceRecord: Table("resources", "resource_id", EXPERIMENT_LINKS),
    s.ReadinessReport: Table("readiness_reports", "readiness_id", EXPERIMENT_LINKS),
    s.ImplementationRecord: Table("implementations", "implementation_id", EXPERIMENT_LINKS),
    s.ExperimentRun: Table("runs", "run_id", EXPERIMENT_LINKS + ("implementation_id",), timestamp="started_at"),
    s.MetricRecord: Table("metrics", "metric_id", EXPERIMENT_LINKS + ("run_id",)),
    s.ScientificAnalysis: Table("analyses", "analysis_id", EXPERIMENT_LINKS + ("run_id",), versioned=True),
    s.NextDecision: Table("decisions", "decision_id"),
    s.CostRecord: Table("costs", "cost_id", EXPERIMENT_LINKS),
    s.EventRecord: Table("events", "event_id"),
}


class ResearchLedger:
    def __init__(self, path: str | Path | None = None):
        self.database = LedgerDatabase(path)

    def initialize(self) -> None:
        self.database.initialize()

    def close(self) -> None:
        self.database.close()

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *_):
        self.close()

    def next_id(self, prefix: str) -> str:
        with self.database.transaction() as connection:
            # Manually supplied demo IDs should never collide with generated
            # IDs. Reserve again if a caller has previously supplied one.
            while True:
                identifier = reserve_id(connection, prefix)
                if not self._id_exists(connection, identifier):
                    return identifier

    @staticmethod
    def _id_exists(connection, identifier: str) -> bool:
        # Phase 7 typed objects live in canonical event payloads, not new tables.
        # Preserve collision avoidance for manually imported payload identities.
        if identifier.startswith(("FEAS_", "APKT_", "PPLAN_", "MANIFEST_")) and connection.execute(
            "SELECT 1 FROM events WHERE json_extract(record_json, '$.payload.assessment.assessment_id') = ? "
            "OR json_extract(record_json, '$.payload.packet.packet_id') = ? "
            "OR json_extract(record_json, '$.payload.plan.plan_id') = ? "
            "OR json_extract(record_json, '$.payload.manifest.manifest_id') = ? LIMIT 1", (identifier, identifier, identifier, identifier)
        ).fetchone():
            return True
        return any(connection.execute(
            f"SELECT 1 FROM {table.name} WHERE {table.id_field} = ? LIMIT 1", (identifier,)
        ).fetchone() for table in TABLES.values())

    @staticmethod
    def _table(model: type[s.Record]) -> Table:
        try:
            return TABLES[model]
        except KeyError:
            raise TypeError(f"Not a canonical ledger record: {model.__name__}") from None

    def add(self, record: T) -> T:
        return self.add_many([record])[0]

    def add_many(self, records, *, check=None):
        """Atomically save a batch; optional deterministic check runs under lock.

        The control plane uses this to recheck fresh state before saving a
        NextDecision and EventRecord together. Failure rolls back the batch.
        """
        with self.database.transaction() as connection:
            if check is not None:
                check()
            return [self._insert(connection, record) for record in records]

    def _insert(self, connection, record: T) -> T:
        table = self._table(type(record))
        payload = serialize(record)
        record = deserialize(type(record), payload)
        keys = [table.id_field]
        if table.name != "projects":
            keys.append("project_id")
        if table.versioned:
            keys.append("version")
        keys.extend(table.links)
        values = [getattr(record, key) for key in keys]
        keys.extend(["created_at", "record_json"])
        values.extend([getattr(record, table.timestamp).isoformat(timespec="microseconds"), payload])
        if table.versioned:
            previous = connection.execute(
                f"SELECT project_id, MAX(version) AS version FROM {table.name} WHERE {table.id_field} = ? GROUP BY project_id",
                (getattr(record, table.id_field),),
            ).fetchone()
            expected = previous["version"] + 1 if previous else 1
            if previous and previous["project_id"] != record.project_id:
                raise ValueError("An object's project cannot change between versions.")
            if record.version != expected:
                raise ValueError(f"Expected the next version {expected}; got {record.version}.")
        if isinstance(record, s.ReviewRecord):
            self._validate_review_target(connection, record)
        connection.execute(
            f"INSERT INTO {table.name} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})", values,
        )
        if isinstance(record, s.Hypothesis):
            for relationship, ids in (("supports", record.supporting_evidence_ids), ("contradicts", record.contradicting_evidence_ids)):
                connection.executemany(
                    "INSERT INTO hypothesis_evidence(hypothesis_id, version, project_id, evidence_id, relationship) VALUES (?, ?, ?, ?, ?)",
                    [(record.hypothesis_id, record.version, record.project_id, evidence_id, relationship) for evidence_id in ids],
                )
        return record

    @staticmethod
    def _validate_review_target(connection, record: s.ReviewRecord) -> None:
        # Polymorphic review targets cannot have a single SQL foreign key.
        # Accept canonical class or table names, and validate inside the save
        # transaction, including the project and exact target version.
        matches = [table for model, table in TABLES.items()
                   if record.target_type in (model.__name__, table.name)]
        if not matches:
            raise ValueError("Unknown review target type; use a canonical model or table name.")
        table = matches[0]
        sql = f"SELECT 1 FROM {table.name} WHERE {table.id_field} = ? AND project_id = ?"
        args = [record.target_id, record.project_id]
        if table.versioned:
            sql += " AND version = ?"
            args.append(record.target_version)
        elif record.target_version != 1:
            raise ValueError("Unversioned review targets have target_version 1.")
        if not connection.execute(sql, args).fetchone():
            raise sqlite3.IntegrityError("Review target does not exist in the specified project/version.")

    def get(self, model: type[T], identifier: str, *, version: int | None = None) -> T | None:
        table = self._table(model)
        sql = f"SELECT record_json FROM {table.name} WHERE {table.id_field} = ?"
        args = [identifier]
        if table.versioned:
            if version is not None:
                sql += " AND version = ?"
                args.append(version)
            sql += " ORDER BY version DESC"
        elif version is not None:
            raise ValueError("This record type is not versioned.")
        row = self.database.connection.execute(sql + " LIMIT 1", args).fetchone()
        return deserialize(model, row["record_json"]) if row else None

    def list_records(self, model: type[T], project_id: str) -> list[T]:
        """Chronological records; versioned models include every stored version."""
        table = self._table(model)
        rows = self.database.connection.execute(
            f"SELECT record_json FROM {table.name} WHERE project_id = ? ORDER BY created_at, rowid", (project_id,),
        ).fetchall()
        return [deserialize(model, row["record_json"]) for row in rows]

    def create_project(self, record: s.ResearchCharter) -> s.ResearchCharter:
        return self.add(record)

    def add_source(self, record: s.SourceRecord) -> s.SourceRecord:
        return self.add(record)

    def add_evidence(self, record: s.EvidenceRecord) -> s.EvidenceRecord:
        return self.add(record)

    def add_hypothesis(self, record: s.Hypothesis) -> s.Hypothesis:
        return self.add(record)

    def add_review(self, record: s.ReviewRecord) -> s.ReviewRecord:
        return self.add(record)

    def add_experiment_candidate(self, record: s.ExperimentCandidate) -> s.ExperimentCandidate:
        return self.add(record)

    def add_experiment_spec(self, record: s.ExperimentSpec) -> s.ExperimentSpec:
        return self.add(record)

    def add_resource(self, record: s.ResourceRecord) -> s.ResourceRecord:
        return self.add(record)

    def add_readiness_report(self, record: s.ReadinessReport) -> s.ReadinessReport:
        return self.add(record)

    def add_implementation(self, record: s.ImplementationRecord) -> s.ImplementationRecord:
        return self.add(record)

    def add_run(self, record: s.ExperimentRun) -> s.ExperimentRun:
        return self.add(record)

    def add_metric(self, record: s.MetricRecord) -> s.MetricRecord:
        return self.add(record)

    def add_analysis(self, record: s.ScientificAnalysis) -> s.ScientificAnalysis:
        return self.add(record)

    def add_decision(self, record: s.NextDecision) -> s.NextDecision:
        return self.add(record)

    def add_cost(self, record: s.CostRecord) -> s.CostRecord:
        return self.add(record)

    def add_event(self, record: s.EventRecord) -> s.EventRecord:
        return self.add(record)

    def get_project(self, project_id: str) -> s.ResearchCharter | None:
        return self.get(s.ResearchCharter, project_id)

    def get_hypothesis(self, hypothesis_id: str, *, version: int | None = None) -> s.Hypothesis | None:
        return self.get(s.Hypothesis, hypothesis_id, version=version)

    def get_experiment(self, experiment_id: str, *, version: int | None = None) -> s.ExperimentSpec | None:
        return self.get(s.ExperimentSpec, experiment_id, version=version)

    def get_run(self, run_id: str) -> s.ExperimentRun | None:
        return self.get(s.ExperimentRun, run_id)

    def list_sources(self, project_id: str) -> list[s.SourceRecord]:
        return self.list_records(s.SourceRecord, project_id)

    def list_evidence(self, project_id: str) -> list[s.EvidenceRecord]:
        return self.list_records(s.EvidenceRecord, project_id)

    def list_hypotheses(self, project_id: str) -> list[s.Hypothesis]:
        return self.list_records(s.Hypothesis, project_id)

    def list_reviews(self, project_id: str) -> list[s.ReviewRecord]:
        return self.list_records(s.ReviewRecord, project_id)

    def list_experiment_candidates(self, project_id: str) -> list[s.ExperimentCandidate]:
        return self.list_records(s.ExperimentCandidate, project_id)

    def list_experiments(self, project_id: str) -> list[s.ExperimentSpec]:
        return self.list_records(s.ExperimentSpec, project_id)

    def list_resources(self, project_id: str) -> list[s.ResourceRecord]:
        return self.list_records(s.ResourceRecord, project_id)

    def list_readiness_reports(self, project_id: str) -> list[s.ReadinessReport]:
        return self.list_records(s.ReadinessReport, project_id)

    def list_implementations(self, project_id: str) -> list[s.ImplementationRecord]:
        return self.list_records(s.ImplementationRecord, project_id)

    def list_runs(self, project_id: str) -> list[s.ExperimentRun]:
        return self.list_records(s.ExperimentRun, project_id)

    def list_metrics(self, project_id: str) -> list[s.MetricRecord]:
        return self.list_records(s.MetricRecord, project_id)

    def list_analyses(self, project_id: str) -> list[s.ScientificAnalysis]:
        return self.list_records(s.ScientificAnalysis, project_id)

    def list_decisions(self, project_id: str) -> list[s.NextDecision]:
        return self.list_records(s.NextDecision, project_id)

    def list_costs(self, project_id: str) -> list[s.CostRecord]:
        return self.list_records(s.CostRecord, project_id)

    def list_events(self, project_id: str) -> list[s.EventRecord]:
        return self.list_records(s.EventRecord, project_id)
