"""Real Omnigent code generation in an isolated legitimate fixture workspace."""
import argparse
import asyncio
import json
from uuid import uuid4
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.implementation.service import ImplementationService
from autolab.implementation.models import ImplementationPlan, TestContract
from autolab.implementation.harness import run_checks
from autolab.implementation.validation import read_sources
from autolab.orchestration.state_machine import current_implementation
from autolab.implementation_smoke_helpers import seed_fixture, PROJECT, assert_no_execution, verify_real_blocked


async def smoke():
    blocked = verify_real_blocked()
    root = PROJECT_ROOT/'results/phase9-artifacts'/uuid4().hex; root.mkdir(parents=True)
    db = root/'fixture.db'
    with ResearchLedger(db) as ledger:
        project, spec, contract = await seed_fixture(ledger, root)
        service = ImplementationService(ledger, root=root, contracts={contract.spec_fingerprint:contract})
        record = await service.implement(PROJECT)
        snapshot = load_snapshot(ledger, PROJECT); assert_no_execution(snapshot)
        output = {'database_path':str(db), 'root':str(root), 'implementation_id':record.implementation_id,
            'snapshot':snapshot.model_dump(mode='json'), 'actual_blocked_check':blocked}
        (PROJECT_ROOT/'results/phase9-implementation-smoke.json').write_text(json.dumps(output, indent=2))
        checks = record.metadata['checks']
        print('AUTOLAB_IMPLEMENTATION_OK' if checks['static_pass'] and checks['tests_pass'] else 'AUTOLAB_IMPLEMENTATION_CHECKS_FAILED')
        print(f'Experiment: {spec.experiment_id} v{spec.version}; Implementation: {record.implementation_id}')
        print('Harness: Omnigent openai-agents; model: gpt-6.1-sol / high')
        print('Files generated: ' + ', '.join(record.metadata['file_hashes']))
        print(json.dumps(checks, indent=2))
        print(f'Code hash: {record.code_version}; workspace: {record.code_path}')
        print('Scientific experiment executed: no')
        if not checks['static_pass'] or not checks['tests_pass']:
            raise RuntimeError('Generated implementation requires independent audit/revision; never force PASS')
        return record


async def verify_existing():
    """Recheck the actual generated/revised code without another generation call."""
    saved = json.loads((PROJECT_ROOT/'results/phase9-implementation-smoke.json').read_text())
    with ResearchLedger(saved['database_path']) as ledger:
        snapshot = load_snapshot(ledger, PROJECT); record = current_implementation(snapshot)
        report = await run_checks(read_sources(record), ImplementationPlan.model_validate(record.metadata['plan']),
            TestContract.model_validate(record.metadata['test_contract']), record.code_path)
        assert report.static_pass and report.tests_pass
        assert_no_execution(snapshot); verify_real_blocked()
        (PROJECT_ROOT/'results/phase9-implementation-revalidation.json').write_text(json.dumps({
            'implementation_id':record.implementation_id,'code_hash':record.code_version,'checks':report.model_dump(mode='json'),
            'database_path':saved['database_path'],'scientific_experiment_executed':False},indent=2))
        print('AUTOLAB_IMPLEMENTATION_OK')
        print(f'Implementation: {record.implementation_id}; code hash: {record.code_version}')
        print(report.model_dump_json(indent=2)); print('Scientific experiment executed: no')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--verify-existing',action='store_true')
    asyncio.run(verify_existing() if parser.parse_args().verify_existing else smoke())
