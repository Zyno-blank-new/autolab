"""Offline reset, approval and receipt checks for the thin final-demo scripts."""
import asyncio
import json
from pathlib import Path
from datetime import timedelta

import pytest
from autolab import schemas as s
from autolab import final_demo as demo
from autolab.final_e2e_integration_smoke import ObservedTransport, test_authorize_run as authorize
from autolab.final_demo_audit import audit, final_telemetry
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.planner.service import OmnigentPlanner, PlannerInvocationError


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(demo,'PROJECT_ROOT',tmp_path)
    monkeypatch.setattr(demo,'DEMO_ROOT',tmp_path/'results'/'final-demo')
    return tmp_path


def test_two_preparations_are_fresh_charters_only(isolated):
    first=demo.create_demo()
    before=(isolated/first['db']).read_bytes()
    second=demo.create_demo()
    assert first['db']!=second['db']
    assert (isolated/first['db']).read_bytes()==before
    for receipt in (first,second):
        with ResearchLedger(isolated/receipt['db']) as ledger:
            snapshot=load_snapshot(ledger,demo.PROJECT)
            assert not any((snapshot.sources,snapshot.evidence,snapshot.hypotheses,snapshot.experiments,
                snapshot.resources,snapshot.implementations,snapshot.runs,snapshot.metrics,snapshot.analyses))
            assert not any(e.event_type=='HUMAN_APPROVED' for e in snapshot.events)
            assert snapshot.charter.constraints['max_experiments']==1
            assert snapshot.charter.stop_conditions


def test_reset_preserves_unrelated_data(isolated):
    unrelated=isolated/'research_state'/'real.db'
    unrelated.parent.mkdir()
    unrelated.write_bytes(b'An unrelated historical file')
    report=isolated/'reports'/'old.md'
    report.parent.mkdir()
    report.write_text('Unrelated report')
    demo.create_demo()
    assert unrelated.read_bytes()==b'An unrelated historical file'
    assert report.read_text()=='Unrelated report'


def test_wrong_ledger_and_external_symlink_rejected(isolated):
    wrong=isolated/'wrong.db'
    with ResearchLedger(wrong) as ledger:
        ledger.create_project(s.ResearchCharter(project_id=demo.PROJECT,title='Test',research_question=demo.QUESTION,objective='Test isolation',primary_outcome='Test'))
    with pytest.raises(ValueError,match='Select an existing'):
        demo.require_demo(wrong)
    demo.DEMO_ROOT.mkdir(parents=True)
    linked=demo.DEMO_ROOT/'demo.db'
    linked.symlink_to(wrong)
    with pytest.raises(ValueError,match='Select an existing'):
        demo.require_demo(linked)


def test_missing_or_wrong_charter_rejected(isolated):
    receipt=demo.create_demo()
    assert demo.require_demo(isolated/receipt['db']).is_file()
    path=demo.DEMO_ROOT/'unrelated'/'demo.db'
    with ResearchLedger(path) as ledger:
        ledger.create_project(s.ResearchCharter(project_id=demo.PROJECT,title='Test',research_question='Different science',objective='Test isolation',primary_outcome='Test'))
    with pytest.raises(ValueError,match='Not an explicit'):
        demo.require_demo(path)


def spec(**updates):
    values=dict(experiment_id='EXP_DEMO',project_id=demo.PROJECT,hypothesis_id='HYP_DEMO',title='Test',objective='Test',experiment_type='Test',
        independent_variables={'condition':['baseline','clipped'],'seed':19,'max_calls_per_sample':1},
        dataset_requirements={'frozen_rows':demo.COHORTS['bounded']},
        primary_metric='mean_absolute_error',required_capabilities=['filesystem_access'],required_resources=['Frozen data'])
    values.update(updates)
    return s.ExperimentSpec(**values)


@pytest.mark.parametrize('changes',[
    {'independent_variables':{'condition':['baseline','clipped'],'seed':20,'max_calls_per_sample':1}},
    {'secondary_metrics':['unconfigured_metric']},
    {'primary_metric':'invented_metric'},
    {'dataset_requirements':{'frozen_rows':[{'sample_id':'posthoc','prediction':1,'target':1}]}},
    {'required_capabilities':['network_access']},
    {'required_resources':['one','two']},
])
def test_unsupported_science_is_not_rewritten(changes):
    value=spec(**changes)
    before=value.model_dump_json()
    with pytest.raises(ValueError):
        demo.supported_spec(value)
    assert value.model_dump_json()==before


@pytest.mark.parametrize('cohort',['bounded','range_shift'])
def test_both_preregistered_cohorts_admitted(cohort):
    assert demo.supported_spec(spec(dataset_requirements={'frozen_rows':demo.COHORTS[cohort]}))==demo.COHORTS[cohort]


def test_run_authorization_requires_explicit_opt_in(isolated):
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        before=ledger.list_events(demo.PROJECT)
        with pytest.raises(ValueError,match='explicit test-human'):
            authorize(ledger,None)
        assert ledger.list_events(demo.PROJECT)==before


def test_explicit_opt_in_does_not_bypass_missing_audit(isolated):
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        with pytest.raises(ValueError,match='Independent exact code audit'):
            authorize(ledger,None,explicit_test_human=True)
        assert not any(e.event_type=='HUMAN_APPROVED' for e in ledger.list_events(demo.PROJECT))


def test_charter_cannot_be_certified_as_completed_e2e(isolated):
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        assert audit(ledger,require_complete=False)['status']=='INCOMPLETE'
        with pytest.raises(ValueError,match='incomplete'):
            audit(ledger)


def test_receipts_count_actual_attempts_and_do_not_blind_retry(isolated,monkeypatch):
    receipt=demo.create_demo()
    path=isolated/receipt['db']
    calls=[]
    async def fail(self,*args,**kwargs):
        calls.append(kwargs['role'])
        raise PlannerInvocationError('Do not store private exception text')
    monkeypatch.setattr(OmnigentPlanner,'invoke_agent',fail)
    transport=ObservedTransport(path.parent/'model_calls.json',cap=1)
    with pytest.raises(PlannerInvocationError):
        asyncio.run(transport.invoke_agent(Path('unused'), 'public fixture',project_id=demo.PROJECT,role='planner'))
    assert calls==['planner']
    assert 'private exception text' not in transport.path.read_text()
    with pytest.raises(RuntimeError,match='cap reached'):
        asyncio.run(transport.invoke_agent(Path('unused'),'public fixture',project_id=demo.PROJECT,role='planner'))
    with ResearchLedger(path) as ledger:
        transport.flush(ledger)
        transport.flush(ledger)
        receipts=[e for e in ledger.list_events(demo.PROJECT) if e.event_type=='DEMO_MODEL_INVOCATION']
        assert len(receipts)==1 and receipts[0].payload['status']=='FAILED'
        assert not ledger.list_decisions(demo.PROJECT)
        counts=final_telemetry(load_snapshot(ledger,demo.PROJECT))['counts']
        assert counts['model_calls_attempted']==1 and counts['model_calls_completed']==0 and counts['model_calls_failed']==1


def test_unknown_timings_remain_unknown_and_zero_not_acceleration(isolated):
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        measured=final_telemetry(load_snapshot(ledger,demo.PROJECT))
        assert measured['durations_seconds']['observed_control_and_specialist_active_wall'] is None
        assert measured['durations_seconds']['observed_model_wait_wall'] is None
        assert measured['durations_seconds']['spec_to_approval_request']==[]
        assert 'human comparison baseline' in ' '.join(measured['measurement_limits'])


def test_active_receipt_uses_only_completed_measured_intervals(isolated):
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        now=s.utc_now()
        ledger.add_event(s.EventRecord(event_id='EVENT_TIMING',project_id=demo.PROJECT,
            event_type='DEMO_ACTION_TIMING',actor='demo_observer',summary='Controlled test receipt',
            payload={'started_at':now.isoformat(),'completed_at':(now+timedelta(seconds=2)).isoformat(),
                'duration_seconds':2.,'decision_ids':[],'status':'STOP'}))
        measured=final_telemetry(load_snapshot(ledger,demo.PROJECT))
        assert measured['durations_seconds']['observed_control_and_specialist_active_wall']==2
        assert measured['timing_receipts']['control_steps'][0]['event_id']=='EVENT_TIMING'


def test_planner_distinguishes_round_labels_and_actual_record_ids(isolated):
    from autolab.orchestration.context_builder import ContextBuilder
    from autolab.planner.prompt import planner_request
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        context=ContextBuilder().build(load_snapshot(ledger,demo.PROJECT))
        context.summaries['research_rounds']=[{'round_id':'ROUND_0001','trigger_decision':'DEC_UNKNOWN'}]
        payload=json.loads(planner_request(context,'DEC_ASSIGNED'))
        assert demo.PROJECT in payload['allowed_visible_context_ids']
        assert 'ROUND_0001' not in payload['allowed_visible_context_ids']
        assert 'DEC_UNKNOWN' not in payload['allowed_visible_context_ids']
        assert 'No general mathematical proof checker' in payload['specialist_capabilities']['evidence']
        assert 'RUN_FOLLOWUP' not in payload['instructions']
        assert payload['planner_context']['available_actions']==[a.value for a in context.available_actions]


def test_shared_call_cap_preserves_separate_role_metadata(isolated,monkeypatch):
    from autolab.final_e2e_integration_smoke import observed
    from autolab.hypotheses.agent import OmnigentHypothesisAgent, OmnigentScientificCritic
    async def complete(self,*args,**kwargs):
        self.last_model_metadata={'role':kwargs['role']}
        return '{}'
    monkeypatch.setattr(OmnigentPlanner,'invoke_agent',complete)
    journal=ObservedTransport(isolated/'calls.json',cap=2)
    hypothesis=observed(OmnigentHypothesisAgent(),journal)
    critic=observed(OmnigentScientificCritic(),journal)
    for client,role in ((hypothesis,'hypothesis'),(critic,'critic')):
        asyncio.run(client.transport.invoke_agent(Path('unused'),'public',project_id=demo.PROJECT,role=role))
    assert hypothesis.transport.last_model_metadata=={'role':'hypothesis'}
    assert critic.transport.last_model_metadata=={'role':'critic'}
    with pytest.raises(RuntimeError,match='cap reached'):
        asyncio.run(journal.invoke_agent(Path('unused'),'public',project_id=demo.PROJECT,role='planner'))
    assert [r['index'] for r in json.loads(journal.path.read_text())]==[1,2]


def published_test_receipt():
    # Explicit local arithmetic fixture, never persisted as a scientific run.
    import math
    rows=demo.COHORTS['range_shift']
    observations=[{'sample_id':r['sample_id'],'condition':condition,'status':'success',
        'outputs':{'prediction':r['prediction'] if condition=='baseline' else min(1,max(0,r['prediction'])),
            'target':r['target']}} for condition in ('baseline','clipped') for r in rows]
    metrics=[{'metric_id':f'METRIC_TEST_{i}','metric_name':'mean_absolute_error',
        'metric_value':math.fsum(abs(o['outputs']['prediction']-o['outputs']['target']) for o in observations if o['condition']==condition)/4,
        'metadata':{'condition':condition,'denominator':4}} for i,condition in enumerate(('baseline','clipped'))]
    return {'schema':'autolab.final-demo-receipt.v1','project_id':demo.PROJECT,'observations':observations,'metrics':metrics}


def test_portable_fallback_recomputes_negative_intervention_outcome():
    from autolab.final_demo_audit import verify_receipt
    receipt=published_test_receipt()
    assert receipt['metrics'][1]['metric_value']>receipt['metrics'][0]['metric_value']
    verified=verify_receipt(receipt)
    assert verified['status']=='PASS' and verified['metrics_recomputed']==2
    assert 'no live call' in verified['scope']


@pytest.mark.parametrize('change',['metric','pairing','target','missing','failed','duplicate_metric'])
def test_portable_fallback_rejects_invented_measurement_or_incomplete_evidence(change):
    from autolab.final_demo_audit import verify_receipt
    receipt=published_test_receipt()
    if change=='metric':receipt['metrics'][0]['metric_value']=999
    if change=='pairing':receipt['observations'][4]['sample_id']='wrong-sample'
    if change=='target':receipt['observations'][4]['outputs']['target']=99
    if change=='missing':receipt['observations'].pop()
    if change=='failed':receipt['observations'][0]['status']='failed'
    if change=='duplicate_metric':receipt['metrics'].append(receipt['metrics'][0])
    with pytest.raises(ValueError):verify_receipt(receipt)


def test_packet_convenience_helper_cannot_approve_without_opt_in(isolated):
    from autolab.final_e2e_integration_smoke import test_approve as approve
    receipt=demo.create_demo()
    with ResearchLedger(isolated/receipt['db']) as ledger:
        before=ledger.list_events(demo.PROJECT)
        with pytest.raises(ValueError,match='explicit isolated test-human'):
            approve(ledger,None)
        assert ledger.list_events(demo.PROJECT)==before


def test_demo_adapter_keeps_environment_resource_out_of_scoring():
    from types import SimpleNamespace
    from autolab.implementation.contract import RawObservation
    adapter=demo.FinalDemoAdapter('explicit-test-spec-hash')
    resources={'ENV_TEST':{'python_version':'test-only'},'DATA_TEST':demo.COHORTS['range_shift']}
    assert adapter.observation_limit(resources)==8
    observations=[RawObservation(sample_id=row['sample_id'],condition=condition,status='success',
        outputs={'prediction':row['prediction'] if condition=='baseline' else min(1,max(0,row['prediction'])),
            'target':row['target']},counts={'rule_calls':1})
        for condition in ('baseline','clipped') for row in resources['DATA_TEST']]
    jobs=adapter.metric_jobs(observations,resources,SimpleNamespace(metrics={'mean_absolute_error':'experiment.py:compute_mae'}))
    assert len(jobs)==2 and all(j.denominator==4 and j.support['metric_direction']=='lower' for j in jobs)
    measured={j.condition:adapter.independently_recompute(j,observations) for j in jobs}
    assert measured['clipped']>measured['baseline']
    with pytest.raises(ValueError,match='Exactly one'):
        adapter.observation_limit({'first':demo.COHORTS['bounded'],'second':demo.COHORTS['range_shift']})
