"""Trusted offline worker for a conservative Python subset, launched with -I -S.

No real resource paths or secrets are supplied. This is defense in depth for
statically admitted small files, not isolation for arbitrary hostile Python.
"""
import builtins
import json
import math
import os
import random
import statistics
import sys
import types
import resource

progress={'framework_count':0,'generated_count':0,'stage':'startup'}
validation_environment={}


class BaseExperiment:
    def setup(self, context): raise RuntimeError('setup missing')
    def run(self, context): raise RuntimeError('Phase 10 execution forbidden')
    def collect_results(self, context): raise RuntimeError('collect_results missing')


def restricted_loader(payload):
    # macOS inserts this non-secret CoreFoundation flag even with an explicit
    # exec environment. Remove it before admitting any generated source.
    os.environ.pop('__CF_USER_TEXT_ENCODING', None)
    assert set(os.environ) <= {'PYTHONHASHSEED','LANG','LC_ALL','LC_CTYPE'}, 'Unexpected environment inheritance'
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    safe_names = ('abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'float', 'int', 'isinstance',
        'len', 'list', 'max', 'min', 'range', 'repr', 'reversed', 'round', 'set', 'sorted',
        'str', 'sum', 'tuple', 'zip', 'ValueError', 'RuntimeError', 'KeyError', 'TypeError',
        'AssertionError', 'Exception', 'ZeroDivisionError', 'OverflowError', 'IndexError',
        'StopIteration', 'ArithmeticError', 'ImportError', '__build_class__')
    safe = {name: getattr(builtins, name) for name in safe_names}
    proxies = {
        'math': types.SimpleNamespace(**{n: getattr(math, n) for n in ('fsum', 'isfinite', 'isclose', 'sqrt', 'floor', 'ceil', 'fabs')}),
        'statistics': types.SimpleNamespace(mean=statistics.mean, median=statistics.median, stdev=statistics.stdev),
        'json': types.SimpleNamespace(loads=json.loads, dumps=json.dumps),
        'random': types.SimpleNamespace(Random=random.Random),
        'autolab.implementation.contract': types.SimpleNamespace(BaseExperiment=BaseExperiment),
    }
    modules = {}

    def load(name):
        if name in modules: return modules[name]
        filename = name + '.py'
        if filename not in payload['files']: raise ImportError('Unknown generated module')
        module = types.ModuleType(name)
        modules[name] = module
        scope = module.__dict__
        scope['__builtins__'] = safe
        exec(compile(payload['files'][filename], filename, 'exec'), scope)
        return module

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level: raise ImportError('Relative import forbidden')
        if name in proxies: return proxies[name]
        if name in ('experiment', 'helpers'): return load(name)
        raise ImportError('Import capability denied')

    safe['__import__'] = guarded_import

    def audit(event, args):
        if event == 'open' or event.startswith(('socket.', 'subprocess.', 'ctypes.', 'os.', 'shutil.', 'urllib.', 'http.')):
            raise PermissionError('Offline worker denied filesystem/network/system capability')
    sys.addaudithook(audit)
    return load


def main():
    payload = json.loads(sys.stdin.read(200000))
    validation_environment.update({'python_version':sys.version.split()[0],
        'framework_source_sha256':payload.get('framework_source_sha256'),
        'framework_version':'autolab-phase9-restricted-profile-v1'})
    load = restricted_loader(payload)
    experiment = load('experiment')
    instance = experiment.Experiment()
    assert isinstance(instance, BaseExperiment), 'BaseExperiment inheritance required'
    # Smoke setup uses toy values only; no run() or actual resources are supplied.
    context = payload['contract']['setup_context']
    context['resources'] = payload['contract']['fixture_resources']
    instance.setup(context)
    for key, expected in payload['contract']['expected_setup'].items():
        assert getattr(instance, key) == expected, 'Framework setup invariant failed: ' + key
    assert callable(instance.run) and callable(instance.collect_results), 'Missing interface'
    count = 1
    progress['framework_count']=count
    for probe in payload['contract']['probes']:
        progress['stage']='framework: '+probe['requirement']
        filename, component = probe['component'].split(':')
        obj = load(filename[:-3])
        for part in component.split('.'): obj = getattr(obj, part)
        if probe.get('raises'):
            try: obj(*probe['args'])
            except Exception as exc:
                assert isinstance(exc, getattr(builtins, probe['raises'])), 'Wrong failure type'
            else: raise AssertionError('Missing expected failure for ' + probe['requirement'])
        else:
            actual = obj(*probe['args'])
            expected = probe['expected']
            assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12) if isinstance(expected, float) else actual == expected, 'Framework probe failed: ' + probe['requirement']
        count += 1
        progress['framework_count']=count
    tests = load('test_experiment')
    generated_count = 0
    for name, function in list(vars(tests).items()):
        if name.startswith('test_') and callable(function):
            progress['stage']='generated: '+name
            function()
            generated_count += 1
            progress['generated_count']=generated_count
    assert generated_count > 0, 'No generated tests'
    sys.stdout.write(json.dumps({'framework_count': count, 'generated_count': generated_count, 'status': 'PASS',
        'environment_sanitized': True, 'network_policy': 'offline', 'scientific_run': False,
        'validation_environment':validation_environment}))


if __name__ == '__main__':
    try: main()
    except BaseException as exc:
        # Bounded public diagnostics; never dump locals, environments or source.
        sys.stdout.write(json.dumps({'status': 'FAIL', 'error': type(exc).__name__, 'detail': str(exc)[:1200],
            **progress,'validation_environment':validation_environment}))
        sys.exit(1)
