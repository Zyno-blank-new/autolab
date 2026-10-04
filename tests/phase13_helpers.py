"""Explicit small canonical test projects; no network or model outputs."""
from autolab import schemas as s
from datetime import timedelta


def charter(ledger, identifier='PROJECT_A', **updates):
    return ledger.create_project(s.ResearchCharter(project_id=identifier, title='Controlled error study',
        research_question='Does the constrained rule reduce error within a frozen cohort?',
        objective='Compare a preregistered rule with its control', primary_outcome='Mean absolute error',
        budget_usd=100, success_criteria={'criterion': 'Lower paired error'}, constraints={'max_rounds': 2}, **updates))


def science(ledger, *, assessment='NOT_SUPPORTED', blocked=False):
    p = charter(ledger)
    source = ledger.add_source(s.SourceRecord(source_id='SRC_A', project_id=p.project_id, title='Stored source title',
        authors=['Stored Author'], year=2024, doi='10.0000/test-fixture', url='https://example.org/test-fixture',
        metadata={'arxiv_id': 'test-fixture-id'}))
    evidence = ledger.add_evidence(s.EvidenceRecord(evidence_id='EVID_SUPPORT', project_id=p.project_id,
        source_id=source.source_id, claim='Canonical publication claim', supporting_text='Recorded passage', location='Abstract', tags=['relevant']))
    contradiction = ledger.add_evidence(s.EvidenceRecord(evidence_id='EVID_CONTRADICT', project_id=p.project_id,
        source_id=source.source_id, claim='Canonical contradictory finding'))
    h = ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_A', project_id=p.project_id, statement='Scoped comparison hypothesis',
        falsifiable_prediction='Frozen intervention MAE is lower than control MAE', supporting_evidence_ids=[evidence.evidence_id],
        contradicting_evidence_ids=[contradiction.evidence_id], status='REJECTED' if assessment == 'NOT_SUPPORTED' else 'PROPOSED'))
    e = ledger.add_experiment_spec(s.ExperimentSpec(experiment_id='EXP_A', project_id=p.project_id,
        hypothesis_id=h.hypothesis_id, title='Frozen rule comparison', objective='Test a condition difference',
        experiment_type='Offline fixture', independent_variables={'conditions': ['control', 'intervention']},
        controls={'baseline': 'control'}, primary_metric='mean_absolute_error',
        success_criteria={'criterion': 'Lower intervention error'}, falsification_criteria={'criterion': 'No lower intervention error'}))
    if blocked:
        ledger.add_review(s.ReviewRecord(review_id='HREV_BLOCK', project_id=p.project_id, review_type='experiment',
            target_type='experiments', target_id=e.experiment_id, verdict='BLOCK', reviewer_role='critic',
            issues=[{'finding': 'Missing frozen data; no execution permitted'}]))
        return p, source, evidence, h, e
    impl = ledger.add_implementation(s.ImplementationRecord(implementation_id='IMPL_A', project_id=p.project_id,
        experiment_id=e.experiment_id, code_path='/fixture/absent/experiment.py', code_version='stored-fixture-hash'))
    run = ledger.add_run(s.ExperimentRun(run_id='RUN_A', project_id=p.project_id, experiment_id=e.experiment_id,
        implementation_id=impl.implementation_id, started_at=s.utc_now()-timedelta(seconds=1),
        completed_at=s.utc_now(), status='COMPLETED', cost_usd=None))
    metrics = [ledger.add_metric(s.MetricRecord(metric_id='METRIC_'+condition.upper(), project_id=p.project_id,
        experiment_id=e.experiment_id, run_id=run.run_id, metric_name='mean_absolute_error', metric_value=value,
        metadata={'condition': condition, 'role': 'primary', 'denominator': 4, 'failure_count': 0}))
        for condition, value in [('control', 0.15), ('intervention', 0.15)]]
    a = ledger.add_analysis(s.ScientificAnalysis(analysis_id='ANALYSIS_A', project_id=p.project_id,
        experiment_id=e.experiment_id, run_id=run.run_id, hypothesis_id=h.hypothesis_id,
        metric_ids=[m.metric_id for m in metrics], hypothesis_assessment=assessment,
        interpretation='Scoped descriptive assessment within this fixture only', generalization_scope='Frozen cohort only',
        limitations=['Small frozen cohort; no population generalization'], remaining_uncertainties=['Other cohorts unknown'],
        criteria_evaluation={'success': {'met': False}}))
    ledger.add_review(s.ReviewRecord(review_id='HREV_A', project_id=p.project_id, review_type='analysis',
        target_type='analyses', target_id=a.analysis_id, verdict='PASS', reviewer_role='critic'))
    return p, source, evidence, h, e, run, metrics, a
