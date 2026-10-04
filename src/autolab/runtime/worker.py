"""Trusted Phase 10 entry point. Only admitted offline code is loaded."""
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('restricted_worker', Path(__file__).parents[1]/'implementation/worker.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def emit(message):
    sys.stdout.write(json.dumps(message, allow_nan=False, separators=(',',':'))+'\n')
    sys.stdout.flush()


def main():
    payload = json.loads(sys.stdin.read(4000000))
    load = profile.restricted_loader(payload)
    module = load('experiment')
    if payload['mode'] == 'metrics':
        values = []
        for job in payload['jobs']:
            filename, component = job['component'].split(':')
            obj = load(filename[:-3])
            for part in component.split('.'): obj = getattr(obj, part)
            values.append(obj(*job['args']))
        emit({'kind':'metrics','values':values})
        return
    context = payload['context']
    instance = module.Experiment()
    if not isinstance(instance, profile.BaseExperiment): raise TypeError('Invalid BaseExperiment')
    try:
        instance.setup(context)
        returned = instance.run(context)
        # Preserve returned observations BEFORE collection, so a collection
        # failure cannot erase raw evidence from a completed execution step.
        observations = returned.get('observations',[]) if isinstance(returned,dict) else []
        for observation in observations: emit({'kind':'observation','observation':observation})
        collected = instance.collect_results(context)
        if not isinstance(collected,dict): raise TypeError('Raw output envelope missing')
        if observations and collected.get('observations') != observations:
            raise ValueError('Run/collector raw observations disagree')
        if not observations:
            for observation in collected.get('observations',[]): emit({'kind':'observation','observation':observation})
        # Do not persist implementation-defined conclusions/comparisons.
        emit({'kind':'completed','experiment_id':collected.get('experiment_id'),
              'experiment_version':collected.get('experiment_version')})
    except BaseException:
        if not locals().get('observations'):
            # Best-effort partial evidence only; never final metric evidence.
            partial = getattr(instance,'observations',[])
            if isinstance(partial,list):
                for observation in partial: emit({'kind':'observation','observation':observation})
        raise


if __name__ == '__main__':
    try: main()
    except BaseException as exc:
        emit({'kind':'error','error_type':type(exc).__name__,'detail':str(exc)[:1000]})
        sys.exit(1)
