"""Shared demo-only charter and durable provenance assertions."""
from autolab import schemas as s
from autolab.literature.provenance import validate_evidence, validate_source


def create_project(ledger):
    return ledger.create_project(s.ResearchCharter(project_id=ledger.next_id("PROJECT"), title="Agent recovery reliability",
        research_question="Do error-aware recovery mechanisms improve the reliability of tool-using AI agents compared with blind retry under a fixed tool-call budget?",
        objective="Assess prior evidence on agent recovery reliability under fixed tool-call budgets.",
        primary_outcome="Task success rate", budget_usd=10, max_runtime_minutes=30))


def verify_records(ledger, project_id):
    sources = ledger.list_sources(project_id)
    evidence = ledger.list_evidence(project_id)
    for source in sources:
        validate_source(source)
    for record in evidence:
        validate_evidence(record, ledger.get(s.SourceRecord, record.source_id))
    return sources, evidence
