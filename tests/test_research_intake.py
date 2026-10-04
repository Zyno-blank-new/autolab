"""Real intake and dispatch boundaries exercised offline, without provider calls."""
from autolab import schemas as s
from autolab.cli import main
from autolab.ledger import ResearchLedger
from autolab.orchestration.orchestrator import Orchestrator


def supplied(path):
    return ['research', 'Does intervention X reduce error?', '--objective', 'Compare X with baseline',
            '--primary-outcome', 'Mean error', '--success-criterion', 'Strictly lower error', '--db', str(path)]


def test_cancelled_intake_creates_nothing(tmp_path):
    path=tmp_path/'research.db'
    assert main(supplied(path), input_fn=lambda _: 'cancel')==0
    assert not path.exists()


def test_interactive_topic_preserves_user_science_and_no_approval(tmp_path):
    path=tmp_path/'research.db'
    answers=iter(['My exact topic', 'My exact objective', 'My metric', 'My criterion', 'START'])
    assert main(['research','--db',str(path),'--create-only'], input_fn=lambda _:next(answers))==0
    with ResearchLedger(path) as ledger:
        rows=ledger.database.connection.execute('SELECT project_id FROM projects').fetchall()
        charter=ledger.get_project(rows[0][0])
        assert (charter.research_question,charter.objective,charter.primary_outcome,charter.success_criteria['criterion'])==('My exact topic','My exact objective','My metric','My criterion')
        assert not ledger.list_decisions(charter.project_id)
        assert not any(e.event_type=='HUMAN_APPROVED' for e in ledger.list_events(charter.project_id))


def test_existing_ledger_not_reused(tmp_path):
    path=tmp_path/'research.db';path.write_bytes(b'existing research')
    assert main(supplied(path)+['--yes','--create-only'])==2
    assert path.read_bytes()==b'existing research'


def test_missing_science_noninteractive_creates_nothing(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr(sys.stdin,'isatty',lambda:False)
    path=tmp_path/'research.db'
    assert main(['research','A topic','--db',str(path),'--yes'])==2
    assert not path.exists()


def test_live_intake_uses_real_orchestrator_and_does_not_force_action(tmp_path,capsys):
    class Planner:
        calls=0
        async def propose(self,context,decision_id,feedback=None):
            self.calls+=1
            assert context.charter.research_question=='Does intervention X reduce error?'
            return s.NextDecision(decision_id=decision_id,project_id=context.charter.project_id,
                action='STOP',reason='No justified further action within this test scope').model_dump_json()
    planner=Planner();path=tmp_path/'research.db'
    assert main(supplied(path)+['--yes'],orchestrator_factory=lambda l:Orchestrator(l,planner))==0
    assert planner.calls==1
    assert 'stopped=True' in capsys.readouterr().out
    assert 'PLANNER_DECISION' not in (path.parent/'process.log').read_text() # Actual action is rendered.
    assert 'STOP' in (path.parent/'process.log').read_text()


def test_invalid_live_allocation_creates_nothing(tmp_path):
    path=tmp_path/'research.db'
    assert main(supplied(path)+['--yes','--budget-usd','0'])==2
    assert not path.exists()
