"""Explicit, bounded repair; omissions require a successor and fresh approval."""
from autolab import schemas as s
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import selected_experiment, approval_for
from autolab.feasibility.persistence import current_assessment, human_event
from autolab.orchestration.budget import calculate_budget,calculate_time
from .manifest import current_plan,current_manifest,fingerprint,repair_attempts
from .models import PreparationError,ResourcePreparationPlan,IssueResponse


def validate_omissions(plan,previous,spec):
    """Admit only lossless visibility projections of already planned inputs.

    Mapping a new requirement to a vague spec string alone is insufficient.
    Other additions need the normal design/human flow, not this repair path.
    """
    old={r.requirement_id:r for r in previous.resource_requirements}
    added=[r for r in plan.resource_requirements if r.requirement_id not in old]
    if not added: raise PreparationError('Class B requires a missing planned resource')
    for r in added:
        parent=old.get(r.parameters.get('parent_requirement'))
        fields=r.parameters.get('fields',[])
        if (r.handler!='transform' or r.acquisition_mode not in ('TRANSFORM','DERIVE')
            or r.parameters.get('operation')!='project' or not parent
            or not fields or not set(fields)<=set(parent.criteria.required_fields)
            or parent.requirement_id not in r.dependencies
            or not set(r.spec_requirements)<=set(spec.required_resources)
            or not set(r.spec_requirements)&set(parent.spec_requirements)
            or not set(r.required_capabilities)<=set(parent.required_capabilities)
            or r.criteria.required_conditions or r.criteria.label_field
            or set(r.criteria.required_fields)!=set(fields)
            or r.criteria.min_samples!=parent.criteria.min_samples
            or r.credential_requirement):
            raise PreparationError('Scientific expansion cannot masquerade as a plan omission')
        if parent.criteria.label_field in fields:
            raise PreparationError('Visibility omission must exclude the scorer target')


def issues_and_prior(service,project):
    snap=load_snapshot(service.ledger,project);spec=service._gate(snap)
    prior=current_plan(snap);manifest=current_manifest(snap)
    report=next((r for r in reversed(snap.readiness) if r.experiment_id==spec.experiment_id and r.experiment_version==spec.version),None)
    if not prior or not manifest or not report or report.verdict!='REPAIR' or report.metadata.get('manifest_id')!=manifest.manifest_id:
        raise PreparationError('Repair requires the exact persisted REPAIR report and manifest')
    if repair_attempts(snap)>=2: raise PreparationError('Repair limit exhausted; return BLOCK')
    return snap,spec,prior,manifest,report.metadata['issues'],report


async def propose_successor(service,project,*,operator_evidence=None):
    before,spec,prior,manifest,issues,report=issues_and_prior(service,project)
    assignment={'plan_id':prior.plan_id,'version':prior.version+1,'project_id':project,
        'experiment_id':spec.experiment_id,'experiment_version':spec.version,'spec_fingerprint':prior.spec_fingerprint}
    service.ledger.add_event(service._event(project,'RESOURCE_PREPARATION_STARTED',spec,
        'Class B successor proposal; rejected invocations count toward repair limit',repair_attempt=repair_attempts(before)+1))
    context={'experiment_spec':spec.model_dump(mode='json'),'resource_catalog':service.catalog,
        'operator_read_only_evidence':operator_evidence or {},
        'capabilities':[{**c.model_dump(mode='json'),'provider':'local executable (path withheld)' if c.provider and c.provider.startswith('/') else c.provider}
            for c in service.registry.capabilities.values()],
        'remaining_budget_usd':calculate_budget(before).remaining_budget_usd,
        'remaining_time_minutes':calculate_time(before).remaining_minutes,
        'feasibility':current_assessment(before).model_dump(mode='json'),
        'approval':approval_for(before,s.PlannerAction.PREPARE_RESOURCES).model_dump(mode='json'),
        'repair_policy':{'class':'B','prior_requirements_immutable':True,
            'allowed_omission':'Lossless target-free projection of existing planned rows, mapped to the same existing ExperimentSpec requirement. Keep all original requirements and acceptance criteria exactly. No new conditions, rows, metrics, science or capabilities.',
            'approval':'Proposal only; fresh incremental feasibility and explicit human reapproval required before activation or creation.',
            'stage_boundary':'Existing CPU/framework availability and data/config contracts are readiness inputs. Generated-code isolation and fidelity require later independent Code Audit and deterministic tests. Do not demand nonexistent future code as a prepared resource. Rebut or clarify overreach with evidence; no forced verdict.'}}
    try:
        proposed=await service.agent.plan(context,assignment,previous=prior,issues=issues)
        plan=service._validate_plan(proposed,assignment,spec,prior,issues,plan_omission=True)
    except Exception as error:
        expansion=isinstance(error,PreparationError) and str(error) in (
            'Scientific expansion cannot masquerade as a plan omission',
            'Visibility omission must exclude the scorer target',
            'Plan introduced an unregistered scientific requirement')
        service.ledger.add_event(service._event(project,
            'RESOURCE_PREPARATION_BLOCKED' if expansion else 'RESOURCE_PREPARATION_FAILED',spec,
            'Class C expansion blocked; return to Planner/design and human approval' if expansion else 'Successor proposal rejected; original plan and resources retained',
            **({'status':'BLOCK','repair_class':'C','reasons':['Requested resource exceeds the admitted in-spec omission contract']} if expansion else {'repair_attempt':repair_attempts(load_snapshot(service.ledger,project))})))
        raise
    from autolab.planner.service import runtime_metadata
    event=service._event(project,'PREPARATION_PLAN_SUCCESSOR_PROPOSED',spec,
        'Immutable Class B successor proposal; pending fresh feasibility and explicit reapproval',
        plan=plan.model_dump(mode='json'),previous_plan_id=prior.plan_id,previous_plan_version=prior.version,
        previous_plan_fingerprint=fingerprint(prior),trigger_readiness_id=report.readiness_id,
        added_requirements=[r.requirement_id for r in plan.resource_requirements if r.requirement_id not in {x.requirement_id for x in prior.resource_requirements}],
        model_metadata=runtime_metadata(service.agent))
    service.ledger.add_event(event)
    return event


def activate_successor(service,project,proposal_id):
    """Fresh Phase 7 human decision is mandatory, even for non-material Class B."""
    snap=load_snapshot(service.ledger,project);spec=service._gate(snap);prior=current_plan(snap)
    event=next((e for e in snap.events if e.event_id==proposal_id and e.actor=='preparation'
        and e.event_type=='PREPARATION_PLAN_SUCCESSOR_PROPOSED' and e.target_id==spec.experiment_id),None)
    if not event or event.payload['previous_plan_fingerprint']!=fingerprint(prior):
        raise PreparationError('Successor lineage is missing or stale')
    plan=ResourcePreparationPlan.model_validate(event.payload['plan'])
    report=next(r for r in snap.readiness if r.readiness_id==event.payload['trigger_readiness_id'])
    assignment={'plan_id':prior.plan_id,'version':prior.version+1,'project_id':project,'experiment_id':spec.experiment_id,
        'experiment_version':spec.version,'spec_fingerprint':prior.spec_fingerprint}
    service._validate_plan(plan,assignment,spec,prior,report.metadata['issues'],plan_omission=True)
    assessment=current_assessment(snap);approval=human_event(snap)
    if (not assessment or assessment.created_at<=event.created_at or not approval or approval.created_at<=assessment.created_at
        or not approval_for(snap,s.PlannerAction.PREPARE_RESOURCES)):
        raise PreparationError('Successor requires fresh incremental feasibility and explicit reapproval')
    status,reasons=service._constraints(snap,plan)
    if status:
        service.ledger.add_event(service._event(project,'RESOURCE_PREPARATION_BLOCKED',spec,
            'Successor cannot activate outside current exact cost/risk scope',status=status,reasons=reasons))
        raise PreparationError('Successor remains blocked: '+'; '.join(reasons))
    service.ledger.add_event(service._event(project,'PREPARATION_PLAN_CREATED',spec,
        'Explicitly reapproved Class B successor; original plan retained',plan=plan.model_dump(mode='json'),
        previous_plan_id=prior.plan_id,previous_plan_version=prior.version,previous_plan_fingerprint=fingerprint(prior),
        successor_proposal_id=proposal_id,trigger_readiness_id=report.readiness_id,
        reapproval_event_id=approval.event_id,assessment_id=assessment.assessment_id))
    return service._create(plan,spec,prior,report.metadata['issues'])


def repair_in_plan(service,project,responses):
    """Class A: replace affected resources; retain the exact PreparationPlan."""
    before,spec,prior,manifest,issues,report=issues_and_prior(service,project)
    responses=[IssueResponse.model_validate(r) for r in responses]
    if sorted(r.issue_index for r in responses)!=list(range(len(issues))):
        raise PreparationError('Repair requires one ACCEPT/REBUT/CLARIFY response per issue')
    if not any(r.disposition=='ACCEPT' for r in responses):
        raise PreparationError('Resource repair requires an accepted issue; use independent reassessment for rebuttal only')
    service.ledger.add_event(service._event(project,'RESOURCE_PREPARATION_STARTED',spec,
        'Class A in-plan repair; original plan unchanged',repair_attempt=repair_attempts(before)+1))
    service.ledger.add_event(service._event(project,'PREPARATION_REPAIR_RESPONSES',spec,
        'Responses to current independent readiness findings',plan_id=prior.plan_id,plan_version=prior.version,
        trigger_readiness_id=report.readiness_id,responses=[r.model_dump(mode='json') for r in responses]))
    return service._create(prior,spec,prior,issues,responses=responses)
