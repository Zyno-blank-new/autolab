"""Explicit paid actual Phase 5 handoff → Omnigent Designer/existing Critic."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.experiment_design.agent import OmnigentExperimentDesigner
from autolab.hypotheses.agent import OmnigentScientificCritic
from autolab.experiment_design.service import ExperimentDesignPipeline
from autolab.experiment_design_smoke_helpers import seed_hypothesis, verify_design, artifact, print_candidates
from autolab.orchestration.orchestrator import Orchestrator


async def smoke():
    configure()
    with TemporaryDirectory(prefix='autolab-experiment-design-') as directory:
        path = Path(directory)/'design.db'
        with ResearchLedger(path) as ledger:
            project, route = seed_hypothesis(ledger)
            designer, critic = OmnigentExperimentDesigner(), OmnigentScientificCritic(timeout_seconds=300)
            # This executor never calls the supplied planner; control returns
            # for a separate, real Planner comparison after design inspection.
            control = Orchestrator(ledger, None)
            result = await control.execute_experiment_design(route, ExperimentDesignPipeline(ledger, designer, critic))
            snapshot = verify_design(ledger, project.project_id, result)
            output = artifact('phase6-experiment-design-smoke.json', ledger, project.project_id, result,
                model_calls={'designer': designer.calls, 'critic': critic.calls, 'planner': 0},
                scientific_input='Real Phase 5 evidence, hypotheses, critique and PI-selected exact-version handoff')
            print_candidates(snapshot)
        with ResearchLedger(path) as reopened:
            assert verify_design(reopened, project.project_id, result) == snapshot
        print('AUTOLAB_EXPERIMENT_DESIGN_OK')
        print(f'Project: {project.project_id}')
        print(f'Selected hypothesis: {result.hypothesis_id} version {result.hypothesis_version}')
        print(f'Candidates generated: {len(result.candidate_ids)}')
        print('Candidate designs available for manual scientific diversity/quality inspection')
        print('Reviews persisted: yes')
        print('No experiment executed: yes')
        print(f'Model calls: designer={designer.calls}, critic={critic.calls}, total={designer.calls+critic.calls}')
        print(f'Scientific output: {output}')


if __name__ == '__main__':
    asyncio.run(smoke())
