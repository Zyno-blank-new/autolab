"""Conceptual dispatch destinations. This registry implements no specialists."""
from dataclasses import dataclass
from autolab.schemas import PlannerAction as A


@dataclass(frozen=True)
class Role:
    name: str
    kind: str = "agent"


DEFAULT_ROLES = (
    Role("planner"), Role("evidence"), Role("hypothesis"), Role("critic"),
    Role("experiment_designer"), Role("preparation"), Role("readiness"),
    Role("implementer"), Role("code_auditor"), Role("analyst"), Role("human", "human"),
    Role("experiment_runner", "deterministic"),
)

ACTION_TARGETS = {
    A.GATHER_EVIDENCE: ("evidence",),
    A.GENERATE_HYPOTHESES: ("hypothesis",),
    A.REFINE_HYPOTHESIS: ("hypothesis", "critic"),
    A.DESIGN_EXPERIMENT: ("experiment_designer", "critic"),
    A.SELECT_EXPERIMENT: ("planner",),
    A.PREPARE_RESOURCES: ("preparation", "readiness"),
    A.IMPLEMENT_EXPERIMENT: ("implementer", "code_auditor"),
    A.RUN_EXPERIMENT: ("experiment_runner",),
    A.ANALYZE_RESULT: ("analyst", "critic"),
    A.RUN_FOLLOWUP: ("experiment_designer",),
    A.COLLECT_MORE_DATA: ("evidence", "preparation"),
    A.REJECT_HYPOTHESIS: ("planner",),
    A.ACCEPT_HYPOTHESIS: ("planner",),
    A.REQUEST_HUMAN_APPROVAL: ("human",),
    A.STOP: (),
}


class RoleRegistry:
    def __init__(self):
        self.roles = {role.name: role for role in DEFAULT_ROLES}
        self.action_targets = dict(ACTION_TARGETS)

    def register(self, role: Role, *, actions: tuple[A, ...] = ()) -> None:
        if role.name in self.roles:
            raise ValueError(f"Role already registered: {role.name}")
        self.roles[role.name] = role
        for action in actions:
            self.action_targets[action] = (*self.action_targets[action], role.name)
