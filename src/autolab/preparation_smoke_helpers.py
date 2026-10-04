"""Public isolated Phase 8 protocol fixture; never substitutes for EXP_0001 science."""
import json
from pathlib import Path
from autolab import schemas as s
from autolab.feasibility.approval import ApprovalService
from autolab.feasibility.capability_registry import CapabilityRegistry
from autolab.feasibility.models import Capability, FeasibilityInputs, CostInput, EstimateRange, ResourceAccess
from autolab.feasibility.service import FeasibilityService
from autolab.orchestration.snapshot import load_snapshot
from autolab.config import PROJECT_ROOT


FIXTURE_LIMIT='Small deterministic lookup protocol fixture only. Not validation of the saved powered empirical experiment or evidence of recovery-policy benefit.'


def seed_protocol(ledger):
    project=ledger.create_project(s.ResearchCharter(project_id='PROJECT_PHASE8_PROTOCOL',title='Phase 8 isolated resource protocol smoke',
        research_question='Can frozen lookup-task resources support a matched recovery-policy protocol?',
        objective='Prepare and audit protocol inputs without running policies or drawing scientific conclusions',
        primary_outcome='Future policy-blind task completion',budget_usd=100,max_runtime_minutes=240,
        constraints={'scope':FIXTURE_LIMIT,'resources':'Small local declarative JSON only; no downloads, experiment code or execution'}))
    hypothesis=ledger.add_hypothesis(s.Hypothesis(hypothesis_id='HYP_PROTOCOL',project_id=project.project_id,
        statement='Choice of recovery policy could affect task completion under a fixed tool-call cap',
        falsifiable_prediction='Future paired task-success contrasts could differ in controlled failures',rationale=FIXTURE_LIMIT))
    spec=ledger.add_experiment_spec(s.ExperimentSpec(experiment_id='EXP_PROTOCOL',project_id=project.project_id,
        hypothesis_id=hypothesis.hypothesis_id,title='Frozen declarative lookup protocol fixture',
        objective='Prepare a bounded outcome-independent toy lookup task pool, matched faults and policy/scoring configuration for future protocol checks',
        experiment_type='matched local protocol fixture; no power or scientific effect claim',
        independent_variables={'recovery_policy':['error_aware','blind_retained','blind_clean'],
            'failure_regime':['transient','persistent_path_specific','failure_free','no_viable_path'],
            'B':8,'seed':42,'inference_ceiling':{'max_tokens_per_task':2000,'max_model_invocations_per_task':8}},
        dependent_variables={'task_success':'Future exact string equality against a hidden reference; abstention gets zero'},
        controls={'pairing':'Each held-out task is matched across every arm and fault regime; separate cloned environments, identical tools and initial state',
            'label_separation':'Inputs contain no reference answers, hidden fault labels or optimal recovery decisions',
            'scoring':'Freeze hidden reference answers separately, identical exact-match completion criterion across arms',
            'clean_context':'Restore pre-failure text only; preserve progress, environment and cumulative call count',
            'faults':'Atomic pre-output failure, fixed primary route, alternate route genuine identical lookup data, never chosen by observed outcomes',
            'budget':'All attempted and failed calls count; diagnosis consumes common inference allocation; abstention earns zero',
            'frozen_operational_protocol':{
                'tools':{'primary_lookup':'Read-only lookup_key to frozen catalog string; missing key returns KEY_NOT_FOUND',
                    'alternate_lookup':'Same read-only mapping and response schema as primary; distinct independent route identity'},
                'common_solver':'One common solver instruction: answer the task by first invoking primary_lookup with lookup_key, then use tool feedback and allowed recovery rule. Reference values and fault labels excluded from prompt.',
                'fault_trigger':'One-based eligible invocation counter per route per task and arm. Primary invocation 1 is the fixed target. Alternate is never faulted except in no_viable_path.',
                'regimes':{'transient':'Primary invocation 1 returns TOOL_UNAVAILABLE atomically before output, later primary invocations succeed',
                    'persistent_path_specific':'Every primary invocation returns TOOL_UNAVAILABLE atomically; alternate succeeds',
                    'failure_free':'Both routes always return the frozen catalog value',
                    'no_viable_path':'Both routes always return TOOL_UNAVAILABLE atomically'},
                'error_feedback':'Identical generic TOOL_UNAVAILABLE response across fault regimes; hidden regime, persistence and correct action are never supplied to policies',
                'error_aware':'After failure, consume common solver invocation/token allocation to diagnose from visible history, then retry identical arguments, choose alternate_lookup for same key, or abstain; no access to private labels or references',
                'blind_retained':'After TOOL_UNAVAILABLE, replay exactly the failed tool and arguments without diagnosis or switch until success or shared budget exhaustion; failed attempt remains in transcript',
                'blind_clean':'Same blind replay rule, but restore visible text to snapshot immediately BEFORE issuing failed tool attempt; remove messages belonging to that failed attempt. Keep all earlier completed progress, environment, private fault counters and cumulative call/inference/token counters unchanged',
                'call_accounting':'Increment common attempted-tool-call counter before each invocation, including failures and diagnostic calls. Reject invocation B+1. No calls transferred between tasks or arms.',
                'inference_accounting':'Maximum 8 model invocations and 2000 cumulative model input+output tokens per task across solving, diagnosis and terminal response. Each diagnosis is part of this shared allowance, never a free extra call; model usage must be logged in Phase 9.',
                'termination':'First terminal JSON object {answer: string} or {abstain: true}. Exact string equality to hidden reference earns 1; abstention, malformed answer, timeout, invalid key or any exhausted ceiling before a valid terminal answer earns 0. Do not retry terminal answers.',
                'initial_state':'Reset catalog, task transcript, all counters and faults independently for each matched task/arm/regime; no mutable tools, cross-task state, shared caches or policy memory.',
                'pairing_and_order':'Every one of the 8 held-out tasks is evaluated in each of 3 arms x 4 regimes with seed 42. Freeze an outcome-independent per-task/regime arm-order permutation using a seeded shuffle before any run. Development tasks are excluded.',
                'scope':'This is a fully specified small protocol fixture. No inferential precision, bootstrap, power or population-effect claim is part of this fixture; future experiment code and its tests are Phase 9.'}},
        dataset_requirements={'task_pool':'8 held-out tasks across at least four semantic lookup families with distinct wording and keys; 4 disjoint development tasks; all references resolvable from same frozen catalog through both routes',
            'schema':['task_id','family','split','prompt','lookup_key'],
            'evaluation_split':'test','minimum_heldout':8,'minimum_development':4,
            'reference_catalog':'At least 12 distinct keys and unambiguous string values, used equally by primary and alternate route',
            'generation':'Synthetic declarative fixtures explicitly allowed; vary wording and topics, never encode policy benefit or agent outputs',
            'separation':'Development/test keys, task IDs and full prompt texts disjoint; references remain separate from agent input',
            'adequacy':'Protocol mechanics only; 8 tasks are not declared adequate for inferential effect estimation'},
        required_resources=['A declarative task pool with hidden references and frozen two-route lookup catalog',
            'A matched seed/failure schedule and environment-state contract',
            'A frozen three-arm inference/budget, scoring and trajectory-logging configuration'],
        required_capabilities=['filesystem_access'],primary_metric='Future paired task-success difference, error_aware minus blind_retained',
        secondary_metrics=['Future blind_clean sensitivity','Future attempted call count'],
        success_criteria={'protocol':'Resources permit every arm and fault regime under the fixed contract; no effect claim until future measured observations and adequate design',
            'effect':'No scientific support claim is authorized by this smoke fixture'},
        falsification_criteria={'protocol':'Missing matched conditions, leaked answers, invalid route catalog or altered controls block protocol readiness',
            'effect':'This small fixture cannot falsify the scientific population hypothesis'},
        potential_confounders=['Toy lookup realism','Template shortcuts','Inference overhead'],
        assumptions=['Two-route declarative lookup semantics will be implemented and tested only in Phase 9',
            'No observed policy outcomes exist; readiness certifies resource suitability for a protocol fixture only'],
        estimated_cost_usd=None,estimated_runtime_minutes=None))
    ledger.add_review(s.ReviewRecord(review_id='ERREV_PROTOCOL',project_id=project.project_id,review_type='experiment',
        target_type='experiments',target_id=spec.experiment_id,verdict='PASS',reviewer_role='critic',
        recommendations=[FIXTURE_LIMIT],issues=[{'severity':'limitation','problem':FIXTURE_LIMIT,'blocking':False}]))
    registry=CapabilityRegistry.local(PROJECT_ROOT)
    inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement=r,status='AVAILABLE',notes=['Explicit isolated local fixture preparation scope']) for r in spec.required_resources],
        costs=[CostInput(category='Illustrative smoke pursuit envelope',unit_price_usd=1,units=EstimateRange(minimum=0,maximum=10),
            assumptions=['Explicit test spending cap, not a provider price quote'])],runtime_minutes=EstimateRange(minimum=1,maximum=60),
        compute_requirements=['Local small JSON artifacts'],storage_gb=EstimateRange(maximum=0.001),warnings=[FIXTURE_LIMIT])
    FeasibilityService(ledger,registry).assess(project.project_id,spec.experiment_id,inputs)
    approval=ApprovalService(ledger,allow_test_human=True); packet=approval.request_approval(project.project_id,spec.experiment_id)
    approval.record_human_decision(project.project_id,spec.experiment_id,1,'APPROVE',packet_id=packet.packet_id,
        actor='test-human',note='Explicit isolated protocol fixture: preparation plus gated implementation eligibility; no execution',
        max_cost_usd=10,max_runtime_minutes=60,acknowledge_unknowns=True,approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])
    return project,spec,registry


def check_no_execution(snapshot):
    assert not snapshot.implementations and not snapshot.runs and not snapshot.metrics and not snapshot.analyses
    assert not any(e.event_type in ('IMPLEMENTATION_STARTED','EXPERIMENT_STARTED') for e in snapshot.events)


def save_phase8(name,ledger,project_id,**extra):
    snapshot=load_snapshot(ledger,project_id); check_no_execution(snapshot)
    path=PROJECT_ROOT/'results'/name
    path.write_text(json.dumps({'snapshot':snapshot.model_dump(mode='json'),**extra},indent=2,allow_nan=False)+'\n')
    return path,snapshot


def renew_protocol_approval(ledger, project, spec, registry, plan):
    """Explicit TEST-HUMAN response to newly surfaced fixture risks; never production."""
    inputs=FeasibilityInputs(resource_access=[ResourceAccess(requirement=r,status='AVAILABLE',notes=['Isolated local JSON handlers only']) for r in spec.required_resources],
        costs=[CostInput(category='Unpriced bounded model/preparation fixture work',unit_price_usd=None,
            units=EstimateRange(minimum=0,maximum=4),assumptions=['Provider billing unavailable; $10 is a human cap, not a measured or estimated price'])],
        runtime_minutes=EstimateRange(minimum=1,maximum=60),compute_requirements=['Local CPU JSON preparation'],
        storage_gb=EstimateRange(maximum=0.01),execution_risks=plan.additional_risks,
        warnings=[FIXTURE_LIMIT,'Explicit test-human acknowledges discovered preparation risks; no production approval granted'])
    assessment=FeasibilityService(ledger,registry).assess(project.project_id,spec.experiment_id,inputs)
    approval=ApprovalService(ledger,allow_test_human=True); packet=approval.request_approval(project.project_id,spec.experiment_id)
    approval.record_human_decision(project.project_id,spec.experiment_id,spec.version,'APPROVE',packet_id=packet.packet_id,
        actor='test-human',note='Explicit isolated fixture reapproval after reviewing Preparation-discovered risks and unknown model cost; no scientific redesign or execution',
        max_cost_usd=10,max_runtime_minutes=60,acknowledge_unknowns=True,approved_actions=['PREPARE_RESOURCES','IMPLEMENT_EXPERIMENT'])
    return assessment,packet


class ProtocolFixtureValidator:
    """Demo-only mechanical checks; no domain rules enter core validators/prompts."""
    def validate_collection(self, snapshot, manifest, evidence):
        from itertools import product
        from collections import Counter
        from random import Random
        records={r.resource_type:r for r in snapshot.resources if r.resource_id in {p.resource_id for p in manifest.resources}}
        types=['declarative_task_pool','hidden_reference_and_lookup_catalog','matched_condition_order_schedule','frozen_declarative_protocol_configuration']
        if not all(t in records for t in types):
            # A scientifically equivalent schema should not be silently judged:
            # fixture adapter must be configured to the actual returned contract.
            raise ValueError('Protocol fixture adapter expects inspected resource schema')
        tasks,catalog,schedule,config=[json.loads(Path(records[t].path_or_uri).read_text()) for t in types]
        task=records[types[0]]; ref=records[types[1]]; sched=records[types[2]]; cfg=records[types[3]]
        splits=Counter(r['split'] for r in tasks)
        evidence.add(task,'fixture_split_counts',splits=={'development':4,'test':8},str(dict(splits)))
        evidence.add(task,'fixture_unique_identifiers',all(len({r[k] for r in tasks})==len(tasks) for k in ('task_id','lookup_key','prompt')),'Distinct IDs, keys and wording across both splits','scientific')
        expected={(r['task_id'],r['lookup_key']) for r in tasks}
        evidence.add(ref,'fixture_reference_join',{(r['task_id'],r['lookup_key']) for r in catalog}==expected and len(catalog)==12,'All 12 hidden references join exactly to task inputs','scientific')
        references={r['lookup_key']:r['reference_value'] for r in catalog}
        evidence.add(task,'fixture_no_answer_leak',all(references[r['lookup_key']] not in r['prompt'] for r in tasks),'Answers excluded from prompts','scientific')
        arms=['error_aware','blind_retained','blind_clean']; regimes=['transient','persistent_path_specific','failure_free','no_viable_path']
        expected=set(product((r['task_id'] for r in tasks if r['split']=='test'),regimes,arms))
        actual={(r['task_id'],r['failure_regime'],r['recovery_policy']) for r in schedule}
        evidence.add(sched,'fixture_matched_coverage',actual==expected and len(schedule)==96,'Exactly 8 held-out tasks x 4 regimes x 3 arms, all tuples once','scientific')
        replay=list(sched.metadata['generation_parameters']['data']); Random(42).shuffle(replay)
        evidence.add(sched,'fixture_seed_replay',replay==schedule,'Real recorded seed-42 shuffle reproduces frozen order')
        spec=next(e for e in snapshot.experiments if e.experiment_id==manifest.experiment_id and e.version==manifest.experiment_version)
        evidence.add(cfg,'fixture_scientific_fidelity',config['operational_protocol']==spec.controls['frozen_operational_protocol'] and config['independent_variables']==spec.independent_variables,
            'Faults, policies, counters, metrics and ceilings copied from exact fixture spec','scientific')
        evidence.summaries.append({'resource_id':sched.resource_id,'joint_coverage':{'independent_tasks':8,'arms':3,'fault_regimes':4,'matched_conditions':96},
            'reference_join_complete':True,'scope':FIXTURE_LIMIT})
