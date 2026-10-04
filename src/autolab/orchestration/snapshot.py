"""Coherent SQLite read snapshot using existing domain-level ledger APIs."""
from contextlib import nullcontext
from autolab import schemas as s
from autolab.ledger import ResearchLedger
from .models import ProjectSnapshot

COLLECTIONS = {
    "sources": s.SourceRecord, "evidence": s.EvidenceRecord, "hypotheses": s.Hypothesis,
    "reviews": s.ReviewRecord, "candidates": s.ExperimentCandidate,
    "experiments": s.ExperimentSpec, "resources": s.ResourceRecord,
    "readiness": s.ReadinessReport, "implementations": s.ImplementationRecord,
    "runs": s.ExperimentRun, "metrics": s.MetricRecord, "analyses": s.ScientificAnalysis,
    "decisions": s.NextDecision, "costs": s.CostRecord, "events": s.EventRecord,
}


def load_snapshot(ledger: ResearchLedger, project_id: str) -> ProjectSnapshot:
    # BEGIN IMMEDIATE provides a coherent read and can also be reused inside
    # the orchestrator's final validation-and-insert transaction.
    scope = nullcontext() if ledger.database.connection.in_transaction else ledger.database.transaction()
    with scope:
        charter = ledger.get_project(project_id)
        if charter is None:
            raise KeyError(f"Unknown project: {project_id}")
        fields = {name: ledger.list_records(model, project_id) for name, model in COLLECTIONS.items()}
        from autolab.preparation.manifest import fingerprint
        authorized = None
        for event in fields['events']:
            if event.event_type != 'LINKED_RESEARCH_SCOPE_AUTHORIZED':
                continue
            if event.actor not in ('human', 'test-human'):
                raise ValueError('Linked charter scope requires explicit human authorization')
            linked = ledger.get_project(event.payload.get('linked_project_id'))
            if (not linked or linked.constraints.get('parent_project') != project_id
                or event.payload.get('parent_charter_fingerprint') != fingerprint(charter)
                or event.payload.get('linked_charter_fingerprint') != fingerprint(linked)):
                raise ValueError('Linked charter authorization identity/fingerprint mismatch')
            authorized = linked
        return ProjectSnapshot(charter=charter, authorized_scope=authorized, **fields)
