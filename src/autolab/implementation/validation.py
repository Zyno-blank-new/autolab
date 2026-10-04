"""Small conservative AST gate, exact plan bindings and immutable source hashes.

This is a restricted Python profile, not a general Python security sandbox.
Unsupported constructs fail closed before the worker can load generated source.
"""
import ast
import hashlib
import json
import re
from pathlib import Path
from autolab.preparation.manifest import fingerprint
from .models import ImplementationError, ImplementationPlan, CheckReport

ALLOWED_DEPENDENCIES = {'math', 'statistics', 'json', 'random'}
ALLOWED_IMPORTS = ALLOWED_DEPENDENCIES | {'autolab.implementation.contract', 'experiment', 'helpers'}
FORBIDDEN_NAMES = {'eval', 'exec', 'compile', 'open', 'input', '__import__', 'getattr', 'setattr',
    'delattr', 'globals', 'locals', 'vars', 'dir', 'type', 'object', 'memoryview', 'breakpoint',
    'help', 'super', 'exit', 'quit'}
FORBIDDEN_ATTRIBUTES = {'system', 'popen', 'unlink', 'remove', 'rmtree', 'rmdir', 'rename',
    'replace', 'write_text', 'write_bytes', 'read_text', 'read_bytes', 'open', 'connect',
    'request', 'urlopen', 'environ', 'getenv', 'f_locals', 'f_globals', 'gi_frame', 'cr_frame',
    'tb_frame', 'with_traceback', 'mro', 'subclasses'}
ALLOWED_FILES = {'experiment.py', 'helpers.py', 'test_experiment.py'}


def parse_component(value):
    if not re.fullmatch(r'(experiment|helpers|test_experiment)\.py:[A-Za-z][A-Za-z0-9_]*(\.(?:__init__|[A-Za-z][A-Za-z0-9_]*))?', value):
        raise ImplementationError('Invalid component reference: ' + value)
    return value.split(':')


def required_requirements(spec):
    fields = ['objective', 'hypothesis_id', 'independent_variables', 'dependent_variables',
        'controls', 'dataset_requirements', 'required_resources', 'required_capabilities',
        'primary_metric', 'success_criteria', 'falsification_criteria', 'assumptions', 'potential_confounders']
    return set(fields + [f'secondary_metrics.{i}' for i, _ in enumerate(spec.secondary_metrics)])


def validate_plan(proposed, assignment, spec, manifest, contract, issues=()):
    plan = ImplementationPlan.model_validate(proposed.model_dump() if isinstance(proposed, ImplementationPlan) else proposed)
    if any(getattr(plan, k) != v for k, v in assignment.items()):
        raise ImplementationError('Implementer changed exact assigned contract/version bindings')
    if plan.input_resources != manifest.resources:
        raise ImplementationError('Plan resource paths/versions/hashes must equal current manifest')
    if plan.objective != spec.objective or plan.conditions != spec.independent_variables or plan.baseline != spec.controls:
        raise ImplementationError('Plan changed scientific objective/conditions/control contract')
    if set(plan.metrics) != {spec.primary_metric, *spec.secondary_metrics}:
        raise ImplementationError('Plan metrics differ from preregistration')
    if not required_requirements(spec) <= {r.requirement for r in plan.requirement_mapping}:
        raise ImplementationError('Incomplete requirement-to-code traceability')
    if not set(plan.dependencies) <= ALLOWED_DEPENDENCIES:
        raise ImplementationError('Dependency requires explicit allowlisting; no automatic install')
    if not {'experiment.py', 'test_experiment.py'} <= set(plan.expected_files) <= ALLOWED_FILES or len(plan.expected_files) != len(set(plan.expected_files)):
        raise ImplementationError('Files must use the constrained experiment workspace layout')
    for item in [*plan.components, *plan.metrics.values(), *(r.component for r in plan.requirement_mapping)]:
        parse_component(item)
    if contract.spec_fingerprint != plan.spec_fingerprint or contract.expected_seeds != plan.seeds:
        raise ImplementationError('Framework tests/seeds do not represent exact contract')
    if plan.metrics != contract.metric_requirements:
        raise ImplementationError('Metric components must match configured independent test adapter')
    indexes = [r.issue_index for r in plan.issue_responses]
    if len(indexes) != len(set(indexes)) or set(indexes) != set(range(len(issues))):
        raise ImplementationError('Respond to every material issue exactly once')
    if len(plan.model_dump_json()) > 50000:
        raise ImplementationError('Plan exceeds bounded context')
    return plan


def components(tree):
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef): found.add(node.name)
        if isinstance(node, ast.ClassDef):
            found.add(node.name)
            found.update(f'{node.name}.{n.name}' for n in node.body if isinstance(n, ast.FunctionDef))
    return found


def static_checks(files, plan, contract):
    findings = []
    if set(files) != set(plan.expected_files) or not set(files) <= ALLOWED_FILES:
        return CheckReport(static_pass=False, findings=['Unexpected or missing generated files'])
    trees = {}
    for name, source in files.items():
        if len(source) > 40000 or sum(len(s) for s in files.values()) > 85000:
            findings.append('Source exceeds bounded audit size'); continue
        try: tree = ast.parse(source, filename=name)
        except (SyntaxError, ValueError):
            findings.append(f'{name}: syntax error'); continue
        trees[name] = tree
        if re.search(r'\b(TODO|FIXME|NotImplementedError)\b', source): findings.append(f'{name}: unresolved critical implementation')
        for node in ast.walk(tree):
            loc = f'{name}:{getattr(node, "lineno", 0)}'
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                if any(m not in ALLOWED_IMPORTS for m in modules) or getattr(node, 'level', 0):
                    findings.append(f'{loc}: forbidden import')
                if any(a.name == '*' or a.name.startswith('_') for a in node.names): findings.append(f'{loc}: unsafe import symbol')
            if isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith('__')):
                findings.append(f'{loc}: forbidden capability/reflection {node.id}')
            exception_init = (isinstance(node, ast.Attribute) and node.attr == '__init__'
                and isinstance(node.value, ast.Name) and node.value.id in {'Exception','ValueError','RuntimeError','TypeError','OverflowError','AssertionError'})
            if isinstance(node, ast.Attribute) and not exception_init and (node.attr.startswith('_') or node.attr in FORBIDDEN_ATTRIBUTES):
                findings.append(f'{loc}: forbidden attribute {node.attr}')
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                module_attributes = {'math': {'fsum','isfinite','isclose','sqrt','floor','ceil','fabs'},
                    'json': {'loads','dumps'}, 'statistics': {'mean','median','stdev'}, 'random': {'Random'}}
                if node.value.id in module_attributes and node.attr not in module_attributes[node.value.id]:
                    findings.append(f'{loc}: unsupported module capability')
            if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.With, ast.AsyncWith, ast.Global, ast.Nonlocal)) or (isinstance(node, ast.Delete) and not name.startswith('test_')):
                findings.append(f'{loc}: unsupported Python capability')
            if isinstance(node, ast.Call):
                if any(k.arg is None or k.arg == 'shell' for k in node.keywords): findings.append(f'{loc}: unsupported dynamic/shell call')
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.lower()
                approved_resource_path = node.value in {p.path for p in plan.input_resources}
                if (any(x in text for x in ('.env', 'api_key', 'http://', 'https://', 'auth.json', 'credentials'))
                    or any(x in text for x in ('/users/','/home/')) and not approved_resource_path):
                    findings.append(f'{loc}: network/credential/absolute path access')
            if isinstance(node, ast.Pass): findings.append(f'{loc}: unresolved pass')
            if isinstance(node, ast.ExceptHandler) and not name.startswith('test_'):
                explicit_error = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript)
                    and isinstance(t.slice, ast.Constant) and t.slice.value == 'error' for t in n.targets) for n in ast.walk(node))
                explicit_failure = any(isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                    and n.value.value in ('failed','failure','error') for n in ast.walk(node))
                owner = next((fn for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                    and any(n is node for n in ast.walk(fn))), None)
                error_accumulation = bool(node.name and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == 'append' and any(isinstance(v, ast.Name) and v.id == node.name
                        for arg in n.args for v in ast.walk(arg)) for n in ast.walk(node)))
                failure_fields = bool(owner and any(isinstance(n, ast.Dict)
                    and {'status','error'} <= {k.value for k in n.keys if isinstance(k,ast.Constant)}
                    for n in ast.walk(owner)))
                failed_label = bool(owner and any(isinstance(n,ast.Constant) and n.value == 'failed' for n in ast.walk(owner)))
                visible_aggregate_failure = error_accumulation and failure_fields and failed_label
                visible_helper_failure = False
                for assignment in (n for n in ast.walk(node) if isinstance(n, ast.Assign) and isinstance(n.value,ast.Call)):
                    call = assignment.value
                    if not isinstance(call.func,ast.Name) or not node.name: continue
                    if not any(isinstance(v,ast.Name) and v.id == node.name for arg in call.args for v in ast.walk(arg)): continue
                    helper = next((f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name == call.func.id), None)
                    if helper and any(isinstance(ret,ast.Return) and isinstance(ret.value,ast.Dict)
                        and any(isinstance(k,ast.Constant) and k.value == 'status' and isinstance(v,ast.Constant) and v.value == 'failed'
                            for k,v in zip(ret.value.keys,ret.value.values))
                        and any(isinstance(k,ast.Constant) and k.value == 'error' and not (isinstance(v,ast.Constant) and v.value is None)
                            for k,v in zip(ret.value.keys,ret.value.values)) for ret in ast.walk(helper)):
                        visible_helper_failure = True
                if not any(isinstance(n, ast.Raise) for n in ast.walk(node)) and not (explicit_error and explicit_failure) and not visible_aggregate_failure and not visible_helper_failure:
                    findings.append(f'{loc}: exception silently swallowed')
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.decorator_list:
                findings.append(f'{loc}: decorators unsupported')
            if isinstance(node, ast.ClassDef) and node.keywords:
                findings.append(f'{loc}: dynamic metaclasses unsupported')
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name.startswith('_') and node.name != '__init__':
                findings.append(f'{loc}: private/dunder implementation forbidden')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'run':
                findings.append(f'{loc}: Phase 10 run invocation forbidden during tests')
            if name.startswith('test_') and isinstance(node, ast.Attribute) and node.attr == 'run':
                findings.append(f'{loc}: Phase 10 run reference forbidden during tests')
            if isinstance(node, ast.FunctionDef) and not name.startswith('test_'):
                if node.name in {'run', 'collect_results'} or node.name.startswith(('compute_', 'metric_')):
                    for ret in (n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None):
                        try: literal = ast.literal_eval(ret.value)
                        except (ValueError, TypeError): continue
                        if isinstance(literal, (int, float, dict, list)):
                            findings.append(f'{loc}: hard-coded result in {node.name}')
        random_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'random']
        if random_calls and not any(n.func.attr in {'seed', 'Random'} for n in random_calls):
            findings.append(f'{name}: unseeded randomness')
    tree = trees.get('experiment.py')
    if tree:
        if not any(isinstance(n, ast.ImportFrom) and n.module == 'autolab.implementation.contract'
            and any(a.name == 'BaseExperiment' and a.asname is None for a in n.names) for n in tree.body):
            findings.append('Canonical BaseExperiment import missing')
        cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Experiment'), None)
        if not cls or not any(isinstance(b, ast.Name) and b.id == 'BaseExperiment' for b in cls.bases):
            findings.append('Experiment must inherit BaseExperiment')
        else:
            for method in ('setup', 'run', 'collect_results'):
                fn = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method), None)
                if not fn or [a.arg for a in fn.args.args] != ['self', 'context']:
                    findings.append('BaseExperiment interface missing: ' + method)
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if plan.experiment_id not in literals or plan.spec_fingerprint not in literals:
            findings.append('Missing exact experiment/spec identity constants')
        for pin in plan.input_resources:
            if pin.resource_id not in literals or pin.checksum not in literals:
                findings.append('Missing resource identity/hash binding: ' + pin.resource_id)
    for component in set([*contract.required_components, *plan.components, *plan.metrics.values(), *(r.component for r in plan.requirement_mapping)]):
        file, target = parse_component(component)
        if file not in trees or target not in components(trees[file]): findings.append('Missing required component: ' + component)
    test_tree = trees.get('test_experiment.py')
    if not test_tree or not any(isinstance(n, ast.FunctionDef) and n.name.startswith('test_') for n in test_tree.body):
        findings.append('Generated unit tests missing')
    return CheckReport(static_pass=not findings, findings=list(dict.fromkeys(findings)))


def source_hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_sources(record):
    root = Path(record.code_path)
    expected = record.metadata.get('file_hashes', {})
    if not expected or root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ImplementationError('Missing or unconfined implementation directory')
    if {p.name for p in root.iterdir()} != set(expected):
        raise ImplementationError('Implementation file set changed')
    files = {}
    for name, digest in expected.items():
        path = root / name
        if name not in ALLOWED_FILES or path.is_symlink() or not path.is_file() or path.stat().st_size > 40000:
            raise ImplementationError('Unconfined source path')
        source = path.read_text()
        if hashlib.sha256(source.encode()).hexdigest() != digest: raise ImplementationError('Implementation file hash changed')
        files[name] = source
    if source_hash(files) != record.code_version: raise ImplementationError('Implementation code hash changed')
    return files
