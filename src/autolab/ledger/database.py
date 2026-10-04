"""SQLite connections, schema initialization, and atomic transactions."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from autolab.config import ledger_path

# Scientific documents are JSON. Identity and relationships have ordinary SQL
# columns so SQLite enforces references, project boundaries, and version pins.
TABLE_COLUMNS = {
    "projects": """
        project_id TEXT PRIMARY KEY
    """,
    "sources": """
        source_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        UNIQUE(source_id, project_id)
    """,
    "evidence": """
        evidence_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        source_id TEXT NOT NULL,
        UNIQUE(evidence_id, project_id),
        FOREIGN KEY(source_id, project_id) REFERENCES sources(source_id, project_id)
    """,
    "hypotheses": """
        hypothesis_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version >= 1),
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        PRIMARY KEY(hypothesis_id, version),
        UNIQUE(hypothesis_id, version, project_id)
    """,
    "reviews": """
        review_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        target_version INTEGER NOT NULL CHECK(target_version >= 1)
    """,
    "experiment_candidates": """
        candidate_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version >= 1),
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        hypothesis_id TEXT NOT NULL,
        hypothesis_version INTEGER NOT NULL,
        PRIMARY KEY(candidate_id, version),
        FOREIGN KEY(hypothesis_id, hypothesis_version, project_id)
            REFERENCES hypotheses(hypothesis_id, version, project_id)
    """,
    "experiments": """
        experiment_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version >= 1),
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        hypothesis_id TEXT NOT NULL,
        hypothesis_version INTEGER NOT NULL,
        PRIMARY KEY(experiment_id, version),
        UNIQUE(experiment_id, version, project_id),
        FOREIGN KEY(hypothesis_id, hypothesis_version, project_id)
            REFERENCES hypotheses(hypothesis_id, version, project_id)
    """,
    "resources": """
        resource_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        FOREIGN KEY(experiment_id, experiment_version, project_id)
            REFERENCES experiments(experiment_id, version, project_id)
    """,
    "readiness_reports": """
        readiness_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        FOREIGN KEY(experiment_id, experiment_version, project_id)
            REFERENCES experiments(experiment_id, version, project_id)
    """,
    "implementations": """
        implementation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        UNIQUE(implementation_id, project_id, experiment_id, experiment_version),
        FOREIGN KEY(experiment_id, experiment_version, project_id)
            REFERENCES experiments(experiment_id, version, project_id)
    """,
    "runs": """
        run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        implementation_id TEXT NOT NULL,
        UNIQUE(run_id, project_id, experiment_id, experiment_version),
        FOREIGN KEY(experiment_id, experiment_version, project_id)
            REFERENCES experiments(experiment_id, version, project_id),
        FOREIGN KEY(implementation_id, project_id, experiment_id, experiment_version)
            REFERENCES implementations(implementation_id, project_id, experiment_id, experiment_version)
    """,
    "metrics": """
        metric_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        run_id TEXT NOT NULL,
        FOREIGN KEY(run_id, project_id, experiment_id, experiment_version)
            REFERENCES runs(run_id, project_id, experiment_id, experiment_version)
    """,
    "analyses": """
        analysis_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version >= 1),
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT NOT NULL,
        experiment_version INTEGER NOT NULL,
        run_id TEXT NOT NULL,
        PRIMARY KEY(analysis_id, version),
        FOREIGN KEY(run_id, project_id, experiment_id, experiment_version)
            REFERENCES runs(run_id, project_id, experiment_id, experiment_version)
    """,
    "decisions": """
        decision_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id)
    """,
    "costs": """
        cost_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        experiment_id TEXT,
        experiment_version INTEGER NOT NULL,
        FOREIGN KEY(experiment_id, experiment_version, project_id)
            REFERENCES experiments(experiment_id, version, project_id)
    """,
    "events": """
        event_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id)
    """,
}


class LedgerDatabase:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path if path is not None else ledger_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def initialize(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
            raise RuntimeError(f"Unsupported ledger schema version: {version}")
        statements = ["BEGIN IMMEDIATE;"]
        if version == 1:
            # Preserve every v1 document/ID/review. Rebuild just the candidate
            # table to add a composite identity; no scientific record is edited.
            for suffix in ("no_replace", "no_update", "no_delete"):
                statements.append(f"DROP TRIGGER IF EXISTS experiment_candidates_{suffix};")
            statements.append("ALTER TABLE experiment_candidates RENAME TO phase6_old_candidates;")
            statements.append(f"CREATE TABLE experiment_candidates (created_at TEXT NOT NULL, record_json TEXT NOT NULL CHECK(json_valid(record_json)), {TABLE_COLUMNS['experiment_candidates']});")
            statements.append("INSERT INTO experiment_candidates(created_at, record_json, candidate_id, version, project_id, hypothesis_id, hypothesis_version) SELECT created_at, record_json, candidate_id, 1, project_id, hypothesis_id, hypothesis_version FROM phase6_old_candidates;")
            statements.append("DROP TABLE phase6_old_candidates;")
        if version in (1, 2):
            # Preserve old JSON verbatim; defaults deserialize historical v1 analyses.
            for suffix in ("no_replace", "no_update", "no_delete"):
                statements.append(f"DROP TRIGGER IF EXISTS analyses_{suffix};")
            statements.append("ALTER TABLE analyses RENAME TO phase11_old_analyses;")
            statements.append(f"CREATE TABLE analyses (created_at TEXT NOT NULL, record_json TEXT NOT NULL CHECK(json_valid(record_json)), {TABLE_COLUMNS['analyses']});")
            statements.append("INSERT INTO analyses(created_at, record_json, analysis_id, version, project_id, experiment_id, experiment_version, run_id) SELECT created_at, record_json, analysis_id, 1, project_id, experiment_id, experiment_version, run_id FROM phase11_old_analyses;")
            statements.append("DROP TABLE phase11_old_analyses;")
        for table, columns in TABLE_COLUMNS.items():
            # SQLite requires table constraints after all column declarations.
            statements.append(f"""CREATE TABLE IF NOT EXISTS {table} (
                created_at TEXT NOT NULL,
                record_json TEXT NOT NULL CHECK(json_valid(record_json)),
                {columns}
            );""")
            if table != "projects":
                statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_project ON {table}(project_id);")
            statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_created ON {table}(created_at);")
            primary = (columns.strip().split()[0], "version") if table in ("hypotheses", "experiments", "experiment_candidates", "analyses") else (columns.strip().split()[0],)
            statements.extend(self._immutable_triggers(table, primary))
        statements.append("""CREATE TABLE IF NOT EXISTS hypothesis_evidence (
            hypothesis_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            relationship TEXT NOT NULL CHECK(relationship IN ('supports', 'contradicts')),
            PRIMARY KEY(hypothesis_id, version, evidence_id),
            FOREIGN KEY(hypothesis_id, version, project_id)
                REFERENCES hypotheses(hypothesis_id, version, project_id),
            FOREIGN KEY(evidence_id, project_id) REFERENCES evidence(evidence_id, project_id)
        );""")
        statements.extend(self._immutable_triggers("hypothesis_evidence", ("hypothesis_id", "version", "evidence_id")))
        statements.append("""CREATE TABLE IF NOT EXISTS id_counters (
            prefix TEXT PRIMARY KEY, value INTEGER NOT NULL CHECK(value >= 1)
        );""")
        statements.extend(["PRAGMA user_version = 3;", "COMMIT;"])
        try:
            self.connection.executescript("\n".join(statements))
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise

    @staticmethod
    def _immutable_triggers(table: str, primary: tuple[str, ...]) -> list[str]:
        # Guard INSERT OR REPLACE too: SQLite replacement deletes can otherwise
        # bypass delete triggers when recursive_triggers is disabled.
        match = " AND ".join(f"{column} = NEW.{column}" for column in primary)
        insert_guard = f"""CREATE TRIGGER IF NOT EXISTS {table}_no_replace
            BEFORE INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM {table} WHERE {match}) BEGIN
                SELECT RAISE(ABORT, 'Ledger record already exists');
            END;"""
        return [insert_guard] + [f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
            BEFORE {operation} ON {table} BEGIN
                SELECT RAISE(ABORT, 'Ledger records are append-only');
            END;""" for operation in ("UPDATE", "DELETE")]

    @contextmanager
    def transaction(self):
        """A write lock makes multi-row saves and ID reservations atomic."""
        if self.connection.in_transaction:
            raise RuntimeError("Nested ledger transactions are not supported.")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()
