"""Explicit paid Analyst smoke using actual completed Phase 10 checkpoint evidence."""
import asyncio
from autolab.config import configure
from autolab.ledger import ResearchLedger
from autolab.analysis.service import AnalysisService
from autolab.analysis.result_summary import build_result_summary
from autolab.orchestration.snapshot import load_snapshot
from autolab.analysis_smoke_helpers import create_fixture, PROJECT, save

async def smoke():
    configure();info=create_fixture()
    with ResearchLedger(info['database_path']) as ledger:
        workflow=AnalysisService(ledger)
        a=await workflow.analyze(PROJECT)
        summary=build_result_summary(load_snapshot(ledger,PROJECT))
        artifact=save('phase11-analysis-smoke.json',ledger,{'result_summary':summary.model_dump(mode='json'),
            'model_calls':{'analyst':workflow.agent.calls,'critic':0},'scientific_critique_performed':False})
        print('AUTOLAB_ANALYSIS_OK')
        print('Experiment:',a.experiment_id,'Run:',a.run_id)
        print('Primary result:',[(m['condition'],m['value']) for m in summary.metrics if m['role']=='primary'])
        print('Analysis:',a.analysis_id,'Support:',a.hypothesis_assessment.value)
        print('Scientific Critique performed: no')
        print('Artifact:',artifact)

if __name__=='__main__':asyncio.run(smoke())
