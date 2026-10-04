"""Small deterministic intake and lifecycle services over canonical ledger state."""
from autolab import schemas as s
from autolab.feasibility.persistence import ensure_public
from autolab.orchestration.adaptive import limits
from autolab.orchestration.models import ControlStage as C, ProjectSnapshot
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.state_machine import derive_control_state


class ProjectService:
    def __init__(self, ledger, *, allow_test_human=False):
        self.ledger = ledger
        self.allow_test_human = allow_test_human

    def start(self, charter):
        charter = s.ResearchCharter.model_validate(charter)
        limits(ProjectSnapshot(charter=charter))
        ensure_public(charter)
        event = s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=charter.project_id,
            event_type='PROJECT_CREATED', actor='human', summary='Explicit research charter intake',
            target_type='projects', target_id=charter.project_id)
        self.ledger.add_many([charter, event])
        return charter

    def control(self, project_id, action, *, note=None, actor='human'):
        if actor != 'human' and not (actor == 'test-human' and self.allow_test_human):
            raise ValueError('Lifecycle controls require an explicit human command.')
        before = load_snapshot(self.ledger, project_id)
        state = derive_control_state(before)
        if state == C.COMPLETED:
            raise ValueError('Project is terminal: STOP/completion cannot be undone by pause or resume.')
        kind = {'pause': 'PROJECT_PAUSED', 'resume': 'PROJECT_RESUMED', 'stop': 'HUMAN_STOPPED'}.get(action)
        if kind is None:
            raise ValueError('Choose pause, resume or stop.')
        if action == 'resume' and state != C.PAUSED:
            raise ValueError('Project is not paused; resume does not reset blocked work or approval gates.')
        if action == 'pause' and state == C.PAUSED:
            raise ValueError('Project is already paused.')
        event = s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=project_id,
            event_type=kind, actor=actor, target_type='projects', target_id=project_id,
            summary=f'Explicit human {action}', payload={'reason': note, 'previous_state': state.value})
        ensure_public(event)
        def check():
            if load_snapshot(self.ledger, project_id) != before:
                raise ValueError('Project changed during control request; inspect status and retry explicitly.')
        self.ledger.add_many([event], check=check)
        return event
