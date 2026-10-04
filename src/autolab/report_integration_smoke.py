"""Report an explicitly isolated, real offline two-round validation history."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from autolab import schemas as s
from autolab.adaptive_loop_integration_smoke import validate_offline
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.models import ProjectSnapshot
from autolab.orchestration.snapshot import load_snapshot, COLLECTIONS
from autolab.reporting.service import ReportService
from autolab.reporting.view import view_snapshot


def import_snapshot(ledger, snapshot):
    """Smoke-only explicit checkpoint import; never used by CLI/report services."""
    ledger.create_project(snapshot.charter)
    if snapshot.authorized_scope:
        ledger.create_project(snapshot.authorized_scope)
    order = [name for name in COLLECTIONS if name not in ('reviews', 'events')] + ['reviews', 'events']
    for name in order:
        ledger.add_many(getattr(snapshot, name))


def verify_report(content, snapshot):
    view = view_snapshot(snapshot)
    assert snapshot.charter.project_id in content and snapshot.charter.research_question in content
    for m in snapshot.metrics:
        assert m.metric_id in content and str(m.metric_value) in content
        row = next(x for x in content.splitlines() if x.startswith('| ' + m.metric_id + ' |'))
        assert f"| {m.metric_value} |" in row
        assert f"| {m.metadata.get('condition')} |" in row
    for a in snapshot.analyses:
        assert f'{a.analysis_id} v{a.version}' in content and a.hypothesis_assessment.value in content
    for h in snapshot.hypotheses:
        assert f'{h.hypothesis_id} v{h.version}' in content
    for e in snapshot.experiments:
        assert f'{e.experiment_id} v{e.version}' in content
    for d in snapshot.decisions:
        assert d.decision_id in content and d.action.value in content
    for source in snapshot.sources:
        assert source.source_id in content and source.title in content
    for evidence in snapshot.evidence:
        assert evidence.evidence_id in content and evidence.source_id in content
    for decision in view['human_decisions']:
        assert decision['event_id'] in content and decision['event_type'] in content
    assert 'SUPPORTED' in content and 'NOT_SUPPORTED' in content
    assert 'ROUND_0001' in content and 'ROUND_0002' in content
    assert 'Limitations and Open Questions' in content and 'UNKNOWN' in content
    assert '10×' not in content and '10x' not in content.lower()
    assert 'PROJECT_UNRELATED_SENTINEL' not in content and 'Unrelated confidential finding' not in content


def smoke(snapshot_path=None):
    if snapshot_path is None:
        validate_offline()  # explicitly runs the existing model-free scientific validation fixture
        snapshot_path = PROJECT_ROOT / 'results/phase12-deterministic-loop-smoke.json'
    snapshot = ProjectSnapshot.model_validate(json.loads(Path(snapshot_path).read_text())['snapshot'])
    root = PROJECT_ROOT / 'results' / 'phase13-artifacts' / uuid4().hex
    root.mkdir(parents=True)
    db = root / 'report.db'
    with ResearchLedger(db) as ledger:
        import_snapshot(ledger, snapshot)
        unrelated = ledger.create_project(s.ResearchCharter(project_id='PROJECT_UNRELATED_SENTINEL', title='Unrelated',
            research_question='Unrelated confidential finding', objective='Separate project', primary_outcome='Separate'))
        before = load_snapshot(ledger, snapshot.charter.project_id)
        assert before == snapshot
        receipt = ReportService(ledger).generate(snapshot.charter.project_id)
        report = Path(receipt['path']).read_text()
        verify_report(report, before)
        after = load_snapshot(ledger, snapshot.charter.project_id)
        for key in COLLECTIONS:
            if key != 'events':
                assert getattr(before, key) == getattr(after, key)
        assert ledger.get_project(unrelated.project_id) == unrelated
        (root / 'validation.json').write_text(json.dumps({'database_path': str(db), 'snapshot_source': str(snapshot_path),
            'receipt': receipt, 'numeric_values_match': True, 'analysis_status_match': True,
            'cross_project_contamination': False, 'paid_model_calls': 0}, indent=2) + '\n')
    print('AUTOLAB_REPORT_OK')
    print('Report:', receipt['path'])
    print('Fixture: explicit isolated offline scientific validation; no population inference or human baseline.')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Explicit canonical offline fixture snapshot; otherwise regenerate it with no model calls.')
    smoke(parser.parse_args().snapshot)
