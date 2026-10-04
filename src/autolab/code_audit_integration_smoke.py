"""Independent real code audit; bounded revisions; optional one PI routing call."""
import argparse
import asyncio
import json
from pathlib import Path
from autolab.config import PROJECT_ROOT
from autolab.ledger import ResearchLedger
from autolab.orchestration.snapshot import load_snapshot
from autolab.orchestration.orchestrator import Orchestrator
from autolab.orchestration.decision_validator import DecisionValidator
from autolab.orchestration.state_machine import current_implementation, implementation_passes
from autolab.planner.service import OmnigentPlanner
from autolab.implementation.service import ImplementationService
from autolab.implementation_smoke_helpers import PROJECT, assert_no_execution, decision, approve_fixture_run_eligibility, verify_real_blocked


async def smoke(*, planner=False, revalidate=False):
    saved = json.loads((PROJECT_ROOT/'results/phase9-implementation-smoke.json').read_text())
    with ResearchLedger(saved['database_path']) as ledger:
        snapshot = load_snapshot(ledger, PROJECT); record = current_implementation(snapshot)
        contract = record.metadata['test_contract']
        service = ImplementationService(ledger, root=Path(saved['root']), contracts={contract['spec_fingerprint']:contract})
        if revalidate:
            report = await service.revalidate(PROJECT)
            if not report.static_pass or not report.tests_pass: raise RuntimeError('Fresh validation did not PASS; no audit authorization')
        assert not DecisionValidator().validate(decision(snapshot,'RUN_EXPERIMENT','experiment_runner'), snapshot).valid
        result = await service.run(PROJECT, audit_only=True)
        snapshot = load_snapshot(ledger, PROJECT); record = current_implementation(snapshot)
        assert_no_execution(snapshot)
        if result.status != 'READY':
            print('AUTOLAB_CODE_AUDIT_BLOCKED'); print(result.model_dump_json(indent=2))
            raise RuntimeError('Independent audit or deterministic checks legitimately blocked; no forced PASS')
        assert implementation_passes(snapshot)
        approve_fixture_run_eligibility(ledger, record)
        snapshot = load_snapshot(ledger, PROJECT)
        assert DecisionValidator().validate(decision(snapshot,'RUN_EXPERIMENT','experiment_runner'), snapshot).valid
        route = await Orchestrator(ledger, OmnigentPlanner(timeout_seconds=360)).decide(PROJECT) if planner else None
        snapshot = load_snapshot(ledger, PROJECT); assert_no_execution(snapshot)
        verify_real_blocked()
        output = {'database_path': saved['database_path'], 'root':saved['root'], 'result':result.model_dump(mode='json'),
            'snapshot':snapshot.model_dump(mode='json'), 'planner_route':route.model_dump(mode='json') if route else None}
        (PROJECT_ROOT/'results/phase9-code-audit-smoke.json').write_text(json.dumps(output, indent=2))
        print('AUTOLAB_CODE_AUDIT_OK')
        print(result.model_dump_json(indent=2))
        print('Static checks: PASS; tests: PASS; Code Auditor: PASS; implementation hash pinned: yes')
        print('RUN_EXPERIMENT eligible: yes (explicit isolated test-human scope)')
        if route: print('Planner routing boundary: ' + route.action.value + '; legal: yes')
        print('Scientific experiment executed: no; Phase 10 executed: no')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--planner', action='store_true')
    parser.add_argument('--revalidate',action='store_true',help='Append fresh offline check evidence before independent audit')
    args=parser.parse_args(); asyncio.run(smoke(planner=args.planner,revalidate=args.revalidate))
