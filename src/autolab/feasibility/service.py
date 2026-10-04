"""Assess execution requirements without changing science or acquiring resources."""
from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.orchestration.budget import calculate_budget, calculate_time
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import latest_review, selected_experiment
from .capability_registry import CapabilityRegistry
from .cost_estimator import budget_status, estimate_cost, time_status
from .models import (BudgetStatus, CapabilityStatus as S, CostInput, EstimateRange, FeasibilityAssessment,
                     FeasibilityInputs, FeasibilityStatus as F, ResourceAccess, TimeStatus)
from .persistence import ensure_public, selected_is_current, spec_fingerprint


class FeasibilityError(ValueError):
    pass


def require_selected(snapshot, experiment_id, version=None):
    experiment = selected_experiment(snapshot)
    if experiment and not selected_is_current(snapshot, experiment):
        current = max((e.version for e in snapshot.experiments if e.experiment_id == experiment.experiment_id), default=experiment.version)
        raise FeasibilityError(f'{experiment.experiment_id} is selected at v{experiment.version}, but the current specification is v{current}; '
            'explicitly select/review the amendment and request fresh feasibility and approval.')
    if (not experiment or experiment.project_id != snapshot.charter.project_id
        or experiment.experiment_id != experiment_id or (version is not None and experiment.version != version)
        or not selected_is_current(snapshot, experiment)):
        raise FeasibilityError("Requires the exact currently selected ExperimentSpec; amendments need explicit selection and new approval.")
    review = latest_review(snapshot, s.ExperimentSpec, experiment.experiment_id, experiment.version)
    if not review or review.verdict != s.ReviewVerdict.PASS:
        raise FeasibilityError("Selected ExperimentSpec requires its exact scientific PASS review.")
    return experiment


class FeasibilityService:
    def __init__(self, ledger, registry=None):
        self.ledger = ledger
        self.registry = registry or CapabilityRegistry.local(PROJECT_ROOT)

    def assess(self, project_id, experiment_id, inputs=None, *, experiment_version=None, now=None):
        inputs = FeasibilityInputs.model_validate((inputs or FeasibilityInputs()).model_dump()
            if isinstance(inputs, FeasibilityInputs) or inputs is None else inputs)
        ensure_public(inputs)
        before = load_snapshot(self.ledger, project_id)
        experiment = require_selected(before, experiment_id, experiment_version)
        if set(inputs.capability_mapping) - set(experiment.required_capabilities):
            raise FeasibilityError("Capability mapping does not match an ExperimentSpec requirement.")
        capabilities = self.registry.check([identifier for requirement in experiment.required_capabilities
            for identifier in inputs.capability_mapping.get(requirement, [requirement])] + inputs.external_api_requirements)
        for capability in capabilities:
            ensure_public(capability)
        assessment_id = self.ledger.next_id("FEAS")
        self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
            event_type="FEASIBILITY_ASSESSMENT_STARTED", actor="feasibility", target_type="experiments",
            target_id=experiment_id, summary="Inspecting declared execution requirements; no resources prepared",
            payload={"assessment_id": assessment_id, "experiment_id": experiment_id, "experiment_version": experiment.version}))
        checkpoint = load_snapshot(self.ledger, project_id)
        try:
            budget, time = calculate_budget(checkpoint), calculate_time(checkpoint, now)
            cost_inputs = list(inputs.costs)
            covered = {c.category for c in cost_inputs}
            for capability in capabilities:
                if capability.cost_driver and capability.cost_driver not in covered:
                    cost_inputs.append(CostInput(category=capability.cost_driver,
                        assumptions=["Required capability has no explicitly configured complete price/quantity estimate."]))
                    covered.add(capability.cost_driver)
            cost = estimate_cost(cost_inputs, spec_estimate=experiment.estimated_cost_usd)
            runtime = inputs.runtime_minutes or EstimateRange(expected=experiment.estimated_runtime_minutes)
            unknown_runtime = list(inputs.unknown_runtime_drivers)
            if inputs.runtime_minutes is None:
                unknown_runtime.append("Total preparation, implementation, execution and audit duration is not established.")
            blockers, warnings, questions = [], list(inputs.warnings), list(inputs.user_input_required)
            for capability in capabilities:
                if capability.status == S.UNAVAILABLE:
                    blockers.append(f"Required capability unavailable: {capability.capability_id}")
                elif capability.status in (S.UNKNOWN, S.REQUIRES_CREDENTIAL):
                    questions.append(f"Resolve required capability {capability.capability_id}: {capability.status.value}")
                if capability.status == S.AVAILABLE and capability.notes:
                    warnings.extend(f"{capability.capability_id}: {note}" for note in capability.notes)
            declarations = {r.requirement: r for r in inputs.resource_access}
            if set(declarations) - set(experiment.required_resources):
                raise FeasibilityError("Resource declaration does not match an ExperimentSpec requirement.")
            resources = [declarations.get(r, ResourceAccess(requirement=r)) for r in experiment.required_resources]
            for resource in resources:
                if resource.status == S.UNAVAILABLE:
                    blockers.append(f"Required resource cannot be accessed: {resource.requirement}")
                elif resource.status != S.AVAILABLE:
                    questions.append(f"Resolve resource access/choice: {resource.requirement}")
                warnings.extend(resource.notes)
            bstatus, tstatus = budget_status(cost.estimate_usd, budget.remaining_budget_usd), time_status(runtime, time.remaining_minutes)
            if bstatus == BudgetStatus.OVER_BUDGET:
                blockers.append("Known minimum cost exceeds remaining project budget.")
            elif bstatus != BudgetStatus.WITHIN_BUDGET:
                warnings.append(f"Budget assessment: {bstatus.value}; a human spending cap is required.")
            if tstatus == TimeStatus.OVER_TIME:
                blockers.append("Known minimum pursuit duration exceeds remaining project time.")
            elif tstatus != TimeStatus.WITHIN_TIME:
                warnings.append(f"Time assessment: {tstatus.value}; a human duration cap is required.")
            if cost.unknown_cost_drivers:
                warnings.append("Unknown costs are unresolved estimates, not zero-cost or actual-spend claims.")
            if unknown_runtime:
                warnings.append("Runtime uncertainty remains; estimates cover pursuit rather than measured execution.")
            if inputs.storage_gb is None:
                warnings.append("Storage quantity is unknown; no storage has been provisioned.")
            if not inputs.compute_requirements:
                warnings.append("Compute workload requirements have not been quantified.")
            planning_notes = experiment.dataset_requirements.get("planning_limitations", [])
            planning_notes = planning_notes if isinstance(planning_notes, list) else []
            if planning_notes:
                warnings.append("Inherited ExperimentSpec planning notes may cite historical constraints; the current charter budget/time shown here govern this assessment.")
            # Credential names are visible. Explicit extra credential requirements
            # must be represented by an assessed capability, never by a secret.
            credentials = list(dict.fromkeys(inputs.credential_requirements + [c.credential_requirement
                for c in capabilities if c.credential_requirement]))
            represented = {c.credential_requirement for c in capabilities if c.status == S.AVAILABLE}
            questions.extend(f"Confirm credential requirement: {name}" for name in credentials if name not in represented)
            status = F.BLOCKED if blockers else (F.NEEDS_USER_INPUT if questions else
                (F.FEASIBLE_WITH_WARNINGS if warnings else F.FEASIBLE))
            assessment = FeasibilityAssessment(assessment_id=assessment_id, project_id=project_id,
                experiment_id=experiment_id, experiment_version=experiment.version, spec_fingerprint=spec_fingerprint(experiment),
                status=status, required_capabilities=[c.capability_id for c in capabilities], capabilities=capabilities,
                available_capabilities=[c.capability_id for c in capabilities if c.status == S.AVAILABLE],
                missing_capabilities=[c.capability_id for c in capabilities if c.status != S.AVAILABLE],
                required_resources=experiment.required_resources, resource_access=resources,
                unresolved_resource_requirements=[r.requirement for r in resources if r.status != S.AVAILABLE],
                credential_requirements=credentials, external_api_requirements=inputs.external_api_requirements,
                compute_requirements=inputs.compute_requirements, storage_gb=inputs.storage_gb,
                cost=cost, runtime_minutes=runtime, runtime_assumptions=inputs.runtime_assumptions,
                unknown_runtime_drivers=unknown_runtime, remaining_budget_usd=budget.remaining_budget_usd,
                budget_status=bstatus, remaining_time_minutes=time.remaining_minutes, time_status=tstatus,
                implementation_complexity=inputs.implementation_complexity, execution_risks=list(dict.fromkeys(
                    inputs.execution_risks + ["Inherited ExperimentSpec planning limitation: " + x
                                              for x in planning_notes if isinstance(x, str)])),
                blockers=list(dict.fromkeys(blockers)), warnings=list(dict.fromkeys(warnings)),
                user_input_required=list(dict.fromkeys(questions)))
            ensure_public(assessment)
            costs = [s.CostRecord(cost_id=self.ledger.next_id("COST"), project_id=project_id,
                experiment_id=experiment_id, experiment_version=experiment.version, category=c.category,
                estimated_usd=c.estimate_usd.expected or c.estimate_usd.minimum or 0, actual_usd=0,
                metadata={"assessment_id": assessment_id, "estimate_only": True, "actual_known": False,
                          **c.model_dump(mode="json")}) for c in cost.categories]
            events = [s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                event_type="FEASIBILITY_ASSESSED", actor="feasibility", target_type="experiments", target_id=experiment_id,
                summary=f"Execution feasibility: {status.value}; estimates and unknowns retained",
                payload={"assessment": assessment.model_dump(mode="json")}),
                s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id, event_type="COST_ESTIMATE_CREATED",
                actor="feasibility", target_type="experiments", target_id=experiment_id,
                summary="Explicit planning cost categories saved; no actual spend recorded",
                payload={"assessment_id": assessment_id, "cost_ids": [c.cost_id for c in costs]})]
            def recheck():
                fresh = load_snapshot(self.ledger, project_id)
                if fresh != checkpoint:
                    raise FeasibilityError("Research state changed during assessment; reassess before persistence.")
                require_selected(fresh, experiment_id, experiment.version)
            self.ledger.add_many([*costs, *events], check=recheck)
            return assessment
        except Exception:
            self.ledger.add_event(s.EventRecord(event_id=self.ledger.next_id("EVENT"), project_id=project_id,
                event_type="FEASIBILITY_ASSESSMENT_FAILED", actor="feasibility", target_type="experiments", target_id=experiment_id,
                summary="Assessment did not complete; previous scientific and approval records preserved",
                payload={"assessment_id": assessment_id, "experiment_version": experiment.version}))
            raise
