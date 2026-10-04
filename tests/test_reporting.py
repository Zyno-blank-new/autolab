"""Ledger-grounded reports, isolation, calibration, reproducibility and output safety."""
import json
from datetime import timedelta
from pathlib import Path
import pytest

from autolab import schemas as s
from autolab.cli import main
from autolab.interface import ProjectService
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot, COLLECTIONS
from autolab.reporting.markdown import render_markdown
from autolab.reporting.service import ReportService
from autolab.reporting.view import build_view, view_snapshot, snapshot_fingerprint
from autolab.report_integration_smoke import import_snapshot, verify_report
from phase13_helpers import charter, science


def report(ledger, project, root, *, now=None):
    receipt = ReportService(ledger, root=root).generate(project.project_id, now=now)
    return Path(receipt['path']).read_text(), receipt


@pytest.fixture(scope='module')
def two_rounds(tmp_path_factory):
    # Real production services + restricted child execution, all agents scripted
    # offline. Reuse Phase 12's complete verified slice, not console claims.
    from test_runtime import ready_runtime as runtime_fixture
    from test_adaptive import reviewed as reviewed_fixture
    from test_adaptive import test_full_two_round_vertical_slice_reuses_every_downstream_service as complete_slice
    root = tmp_path_factory.mktemp('report-two-rounds')
    with ResearchLedger(root/'ledger.db') as ledger:
        runtime = runtime_fixture.__wrapped__(ledger, root)
        reviewed = reviewed_fixture.__wrapped__(runtime)
        complete_slice(reviewed, root)
        project = ledger.get_project(runtime[2].project_id)
        snapshot = load_snapshot(ledger, project.project_id)
        yield ledger, project, snapshot


def test_charter_only_and_missing_science(ledger, tmp_path):
    project = charter(ledger)
    content, _ = report(ledger, project, tmp_path)
    assert project.research_question in content
    assert 'No experiment executed yet' in content and 'No hypothesis recorded' in content
    assert 'No scientific analysis recorded' in content


def test_evidence_citations_exactly_canonical(ledger, tmp_path):
    project, source, evidence, *_ = science(ledger)
    content, _ = report(ledger, project, tmp_path)
    for value in (source.source_id, source.title, source.authors[0], str(source.year), source.doi, source.url,
                  source.metadata['arxiv_id'], evidence.evidence_id, evidence.claim, evidence.supporting_text, evidence.location):
        assert value in content
    assert 'EVID_CONTRADICT' in content and 'Canonical contradictory finding' in content


def test_hypothesis_version_and_rejection(ledger, tmp_path):
    project, _, _, h, *_ = science(ledger)
    content, _ = report(ledger, project, tmp_path)
    assert f'{h.hypothesis_id} v1' in content and h.falsifiable_prediction in content
    assert '**Canonical status:** REJECTED' in content
    assert 'Contradicting evidence IDs' in content and 'EVID_CONTRADICT' in content


def test_blocked_experiment_no_fabricated_fields(ledger, tmp_path):
    project, *_, experiment = science(ledger, blocked=True)
    content, _ = report(ledger, project, tmp_path)
    assert f'{experiment.experiment_id} v1 — BLOCKED / NOT EXECUTED' in content
    assert 'HREV_BLOCK BLOCK' in content and 'No measured result exists' in content
    assert 'METRIC_' not in content and 'RUN_A' not in content


@pytest.mark.parametrize('assessment', ['SUPPORTED', 'PARTIALLY_SUPPORTED', 'NOT_SUPPORTED', 'INCONCLUSIVE'])
def test_assessment_preserved_exactly_no_upgrade(ledger, tmp_path, assessment):
    project, *_, analysis = science(ledger, assessment=assessment)
    content, _ = report(ledger, project, tmp_path)
    assert f'{analysis.analysis_id} v1 — {assessment}' in content
    assert 'Frozen cohort only' in content
    assert 'hypothesis proven' not in content.lower()
    assert '**Current reviewed eligibility:** False' in content  # unpinned historical test record grants no authority


def test_numeric_metrics_ids_denominators_and_execution_separate(ledger, tmp_path):
    project, _, _, _, experiment, run, metrics, analysis = science(ledger)
    content, _ = report(ledger, project, tmp_path)
    assert 'RUN_A — COMPLETED' in content and 'ANALYSIS_A v1 — NOT_SUPPORTED' in content
    for metric in metrics:
        row = next(x for x in content.splitlines() if x.startswith('| '+metric.metric_id+' |'))
        assert str(metric.metric_value) in row and '| 4 | 0 |' in row
    assert f'{experiment.experiment_id} v1' in content and 'HREV_A PASS' in content
    assert 'observations' in content.lower() and 'separate from scientific assessments' in content


def test_unknown_cost_not_fabricated(ledger, tmp_path):
    project, *_ = science(ledger)
    ledger.add_cost(s.CostRecord(cost_id='COST_UNKNOWN', project_id=project.project_id, category='Actual not measured',
        estimated_usd=3, actual_usd=None))
    content, _ = report(ledger, project, tmp_path)
    assert '**Actual cost USD:** UNKNOWN' in content
    assert 'Actual cost UNKNOWN: COST_UNKNOWN' in content
    assert '**Recorded estimates USD (separate from actual):** 3.0' in content
    assert '**Known actual spend USD:** 0.0' in content
    assert '**Remaining allocation after known actuals USD:** 100.0' in content


def test_report_does_not_create_science(ledger, tmp_path):
    project, *_ = science(ledger)
    before = load_snapshot(ledger, project.project_id)
    _, receipt = report(ledger, project, tmp_path)
    after = load_snapshot(ledger, project.project_id)
    assert before.model_dump(exclude={'events'}) == after.model_dump(exclude={'events'})
    assert len(after.events) == len(before.events)+1 and after.events[-1].event_type == 'REPORT_GENERATED'
    assert after.events[-1].payload['snapshot_sha256'] == receipt['generation']['snapshot_sha256']


@pytest.mark.parametrize('other_type', ['charter', 'source', 'science', 'smoke'])
def test_cross_project_contamination_excluded(ledger, tmp_path, other_type):
    project, *_ = science(ledger)
    other = charter(ledger, 'PROJECT_PHASE10_SENTINEL' if other_type == 'smoke' else 'PROJECT_B')
    source = ledger.add_source(s.SourceRecord(source_id='SRC_OTHER', project_id=other.project_id, title='Unrelated secret finding'))
    evidence = ledger.add_evidence(s.EvidenceRecord(evidence_id='EVID_OTHER', project_id=other.project_id,
        source_id=source.source_id, claim='Other project claim'))
    h = ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_OTHER', project_id=other.project_id,
        statement='Other hypothesis', falsifiable_prediction='Other prediction'))
    ledger.add_experiment_spec(s.ExperimentSpec(experiment_id='EXP_PHASE10_OTHER', project_id=other.project_id,
        hypothesis_id=h.hypothesis_id, title='Other experiment', objective='Other test', experiment_type='Other', primary_metric='other_metric'))
    content, _ = report(ledger, project, tmp_path)
    for forbidden in (other.project_id, source.source_id, evidence.evidence_id, h.hypothesis_id, 'EXP_PHASE10_OTHER', source.title):
        assert forbidden not in content
    assert 'other_metric' not in content


def test_same_project_namespace_different_ledgers_different_paths(tmp_path):
    with ResearchLedger(tmp_path/'one.db') as a, ResearchLedger(tmp_path/'two.db') as b:
        pa, pb = charter(a), charter(b)
        ra = ReportService(a, root=tmp_path/'reports').generate(pa.project_id)
        rb = ReportService(b, root=tmp_path/'reports').generate(pb.project_id)
        assert ra['path'] != rb['path']
        assert 'one.db' in Path(ra['path']).read_text() and 'two.db' not in Path(ra['path']).read_text()


def test_stable_regeneration_and_fingerprint(ledger, tmp_path):
    project, *_ = science(ledger)
    now = s.utc_now()
    first, receipt1 = report(ledger, project, tmp_path, now=now)
    second, receipt2 = report(ledger, project, tmp_path, now=now)
    assert first == second and receipt1['generation']['snapshot_sha256'] == receipt2['generation']['snapshot_sha256']
    third, _ = report(ledger, project, tmp_path, now=now+timedelta(seconds=1))
    strip_time = lambda x: '\n'.join(row for row in x.splitlines() if 'Generated timestamp' not in row)
    assert strip_time(third) == strip_time(first)


def test_ordering_matches_canonical_chronology(ledger, tmp_path):
    project, *_ = science(ledger)
    ledger.add_source(s.SourceRecord(source_id='SRC_LATER', project_id=project.project_id, title='Later publication'))
    content, _ = report(ledger, project, tmp_path)
    refs = content.split('## References')[1]
    assert refs.index('SRC_A') < refs.index('SRC_LATER')


def test_atomic_replace_failure_preserves_existing_report(ledger, tmp_path, monkeypatch):
    project = charter(ledger)
    content, receipt = report(ledger, project, tmp_path)
    count = len(ledger.list_events(project.project_id))
    def fail(*_):
        raise OSError('Injected replace failure')
    monkeypatch.setattr('autolab.reporting.service.os.replace', fail)
    with pytest.raises(OSError):
        report(ledger, project, tmp_path)
    path = Path(receipt['path'])
    assert path.read_text() == content and len(ledger.list_events(project.project_id)) == count
    assert not list(path.parent.glob('.research_report-*'))


def test_concurrent_science_rejects_report_publication(ledger, tmp_path, monkeypatch):
    project = charter(ledger)
    import autolab.reporting.service as module
    original = module.render_markdown
    def changed(*args, **kwargs):
        ledger.add_cost(s.CostRecord(cost_id='COST_CHANGE', project_id=project.project_id, category='Concurrent actual', actual_usd=5))
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'render_markdown', changed)
    with pytest.raises(ValueError, match='Ledger changed'):
        report(ledger, project, tmp_path)
    assert not list(tmp_path.rglob('research_report.md'))
    assert not any(e.event_type == 'REPORT_GENERATED' for e in ledger.list_events(project.project_id))


def test_project_id_cannot_escape_report_root(ledger, tmp_path):
    project = charter(ledger, '../../escape')
    with pytest.raises(ValueError, match='project ID'):
        report(ledger, project, tmp_path)


@pytest.mark.parametrize('terminal', ['human', 'planner', 'budget', 'time'])
def test_stopped_partial_project_report(ledger, tmp_path, terminal):
    project = charter(ledger)
    if terminal == 'human':
        ProjectService(ledger).control(project.project_id, 'stop', note='Human stop scope')
    else:
        ledger.add_decision(s.NextDecision(decision_id='DEC_STOP', project_id=project.project_id, action='STOP',
            reason='Stop because '+terminal+' constraint prevents further work'))
    content, _ = report(ledger, project, tmp_path)
    assert '**Status:** COMPLETED' in content and '**Stopped:** True' in content
    if terminal == 'human':
        assert 'HUMAN_STOPPED / human' in content and 'Human stop scope' in content
    else:
        assert 'Stop because '+terminal in content


def test_multi_round_real_service_report(two_rounds, tmp_path):
    ledger, project, before = two_rounds
    content, _ = report(ledger, project, tmp_path)
    verify_report(content, before)
    assert content.index('### ROUND_0001') < content.index('### ROUND_0002')
    assert '0.175' in content and '0.07500000000000001' in content and '0.15000000000000005' in content
    assert 'SUPPORTED' in content and 'NOT_SUPPORTED' in content
    assert len(before.runs) == 2 and len(before.analyses) == 2


def test_run_analysis_pairing_and_followup_lineage(two_rounds):
    ledger, project, before = two_rounds
    view = build_view(ledger, project.project_id)
    for row, run in zip(view['research_history'], before.runs):
        assert row['run_id'] == run.run_id
        assert row['analysis']['id'] == next(a.analysis_id for a in before.analyses if a.run_id == run.run_id)
    selection = view['experiments'][-1]['selection']
    assert selection['parent_run_id'] == before.runs[0].run_id
    assert selection['parent_analysis_id'] == before.analyses[0].analysis_id
    assert selection['selection_decision_id']
    selected = next(e for e in view['milestones'] if e['event_type'] == 'EXPERIMENT_SELECTED')
    assert selected['decision_id'] == selection['selection_decision_id']


def test_factual_telemetry_no_acceleration_baseline(two_rounds, tmp_path):
    ledger, project, before = two_rounds
    content, _ = report(ledger, project, tmp_path)
    counters = build_view(ledger, project.project_id)['telemetry']['counts']
    assert counters['experiments_executed'] == len(before.runs) == 2
    assert counters['human_approvals'] == 4 and counters['planner_decisions'] == 7
    assert counters['papers_screened'] == 0 and counters['deep_evidence_records'] == 0
    assert '10×' not in content and '10x' not in content.lower()
    assert 'No measured human comparison baseline' in content


def test_scope_matched_duration_receipts(two_rounds):
    ledger, project, _ = two_rounds
    measured = build_view(ledger, project.project_id)['telemetry']
    for label in ('preparation', 'implementation', 'analysis'):
        assert len(measured['duration_records'][label]) == 2
        assert len(measured['durations_seconds'][label]) == 2
        for row in measured['duration_records'][label]:
            a = ledger.get(s.EventRecord, row['start_event'])
            b = ledger.get(s.EventRecord, row['end_event'])
            assert row['seconds'] == (b.created_at-a.created_at).total_seconds()
    assert len(measured['durations_seconds']['approval_waiting']) == 2
    assert len(measured['durations_seconds']['result_to_decision']) == 2


def test_local_result_inspection_preserved_without_citation_invention(ledger, tmp_path):
    project, *_ = science(ledger)
    ledger.add_event(s.EventRecord(event_id='EVENT_INSPECTION', project_id=project.project_id,
        event_type='LOCAL_RESULT_EVIDENCE_INSPECTED', actor='evidence', summary='Recorded fixture coverage inspection',
        payload={'run_id': 'RUN_A', 'analysis_id': 'ANALYSIS_A', 'raw_sha256': 'fixture-raw-hash',
            'matched_identity_and_order': True, 'scope': 'Exact observations only',
            'observations': [{'condition': 'control', 'sample_id': 'fixture-0',
                'outputs': {'prediction': 0.2}, 'status': 'success'}]}))
    content, _ = report(ledger, project, tmp_path)
    assert 'EVENT_INSPECTION' in content and 'fixture-raw-hash' in content and 'Exact observations only' in content
    assert '| control | fixture-0 |' in content
    assert len(ledger.list_sources(project.project_id)) == 1


def test_implementation_test_counts_and_provenance_rendered(two_rounds, tmp_path):
    ledger, project, _ = two_rounds
    content, _ = report(ledger, project, tmp_path)
    view = build_view(ledger, project.project_id)
    assert all(i['test_status']['status'] == 'PASS' and i['test_status']['framework_check_count'] > 0 for i in view['implementations'])
    assert 'framework_check_count' in content and 'creation_tool' in content


@pytest.mark.parametrize('environment_name', ['OPENAI_API_KEY', 'HF_TOKEN', 'PRIVATE_SERVICE_PASSWORD'])
def test_secrets_redacted_from_status_report_and_cli(ledger, tmp_path, monkeypatch, capsys, environment_name):
    secret = 'test-secret-value-that-must-never-appear'
    monkeypatch.setenv(environment_name, secret)
    project = charter(ledger)
    ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_SECRET', project_id=project.project_id,
        statement='Legacy record containing '+secret, falsifiable_prediction='No exposure '+secret,
        rationale='OPENAI_API_KEY=literal-legacy-value PRIVATE_SERVICE_PASSWORD=other-legacy-value'))
    content, _ = report(ledger, project, tmp_path)
    view = json.dumps(build_view(ledger, project.project_id))
    assert secret not in content and secret not in view
    assert 'literal-legacy-value' not in content and 'other-legacy-value' not in content
    assert main(['status', '--db', ledger.database.path, '--project', project.project_id, '--json']) == 0
    assert secret not in capsys.readouterr().out


def test_actual_configured_env_values_never_exported(ledger, tmp_path, capsys):
    from autolab.config import configure
    import os
    configure()
    project = charter(ledger)
    content, _ = report(ledger, project, tmp_path)
    main(['status', '--db', ledger.database.path, '--project', project.project_id])
    output = capsys.readouterr().out
    for name in ('OPENAI_API_KEY', 'HF_TOKEN', 'HUGGINGFACE_HUB_TOKEN'):
        value = os.environ.get(name)
        if value:
            assert value not in content and value not in output
    assert 'OpenAI credential:' in output


def test_recognizable_unconfigured_secret_redacted(ledger, tmp_path):
    project = charter(ledger)
    secret = 'sk-'+('A'*30)
    ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_LEGACY', project_id=project.project_id,
        statement=secret, falsifiable_prediction='Prediction'))
    content, _ = report(ledger, project, tmp_path)
    assert secret not in content


def test_markdown_handles_unsafe_markup_without_extra_claims(ledger, tmp_path):
    project = charter(ledger)
    ledger.add_source(s.SourceRecord(source_id='SRC_MARKUP', project_id=project.project_id,
        title='<script>alert(1)</script> | # injected heading'))
    content, _ = report(ledger, project, tmp_path)
    assert '<script>' not in content and '&lt;script&gt;' in content


def test_analysis_versions_and_unfavorable_review_retained(ledger, tmp_path):
    project, *_, analysis = science(ledger, assessment='SUPPORTED')
    revision = ledger.add_analysis(analysis.model_copy(update={'version': 2, 'hypothesis_assessment': s.HypothesisAssessment.INCONCLUSIVE,
        'interpretation': 'Revised assessment retains unresolved limitations'}))
    ledger.add_review(s.ReviewRecord(review_id='HREV_REVISE', project_id=project.project_id, review_type='analysis',
        target_type='analyses', target_id=revision.analysis_id, target_version=2, verdict='REVISE', reviewer_role='critic'))
    content, _ = report(ledger, project, tmp_path)
    assert 'ANALYSIS_A v1 — SUPPORTED' in content and 'ANALYSIS_A v2 — INCONCLUSIVE' in content
    assert 'HREV_REVISE REVISE' in content


def test_missing_analysis_does_not_assign_support(ledger, tmp_path):
    project, *_, experiment = science(ledger, blocked=True)
    impl = ledger.add_implementation(s.ImplementationRecord(implementation_id='IMPL_NO_ANALYSIS', project_id=project.project_id,
        experiment_id=experiment.experiment_id, code_path='/fixture/missing', code_version='fixture'))
    ledger.add_run(s.ExperimentRun(run_id='RUN_NO_ANALYSIS', project_id=project.project_id, experiment_id=experiment.experiment_id,
        implementation_id=impl.implementation_id, status='FAILED', error_message='Visible fixture failure', cost_usd=None))
    content, _ = report(ledger, project, tmp_path)
    assert 'RUN_NO_ANALYSIS — FAILED' in content and 'Visible fixture failure' in content
    assert 'No scientific analysis recorded' in content and '— SUPPORTED' not in content


def test_pending_run_is_not_rendered_as_executed_science(ledger, tmp_path):
    project, *_, experiment = science(ledger, blocked=True)
    impl = ledger.add_implementation(s.ImplementationRecord(implementation_id='IMPL_PENDING', project_id=project.project_id,
        experiment_id=experiment.experiment_id, code_path='/fixture/missing', code_version='fixture'))
    ledger.add_run(s.ExperimentRun(run_id='RUN_PENDING', project_id=project.project_id,
        experiment_id=experiment.experiment_id, implementation_id=impl.implementation_id, status='PENDING', cost_usd=None))
    content, _ = report(ledger, project, tmp_path)
    assert 'EXP_A v1 — PENDING / NOT EXECUTED' in content and 'RUN_PENDING — PENDING' in content
    assert 'METRIC_' not in content and '— SUPPORTED' not in content
    counters = build_view(ledger, project.project_id)['telemetry']['counts']
    assert counters['experiments_executed'] == 0 and counters['completed_runs'] == 0 and counters['pending_run_records'] == 1


def test_real_saved_blocked_project_unchanged_and_fixture_isolation(tmp_path):
    from autolab.config import PROJECT_ROOT
    from autolab.orchestration.models import ProjectSnapshot
    from autolab.runtime_smoke_helpers import verify_real_run_blocked
    path = PROJECT_ROOT/'results/phase8-actual-spec-preparation-smoke.json'
    if not path.exists():
        pytest.skip('Historical actual saved project is not part of a clean checkout')
    original = path.read_bytes()
    snapshot = ProjectSnapshot.model_validate(json.loads(original)['snapshot'])
    with ResearchLedger(tmp_path/'read-only-science-copy.db') as ledger:
        import_snapshot(ledger, snapshot)
        content, _ = report(ledger, snapshot.charter, tmp_path/'reports')
        assert 'EXP_0001 v1' in content and 'BLOCKED / NOT EXECUTED' in content
        assert 'EXP_PHASE10' not in content and 'RUN_0002' not in content and '0.075' not in content
        assert not ledger.list_runs(snapshot.charter.project_id) and not ledger.list_metrics(snapshot.charter.project_id)
    assert path.read_bytes() == original
    assert verify_real_run_blocked()['rejected']
