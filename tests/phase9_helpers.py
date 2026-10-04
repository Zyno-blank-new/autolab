"""Offline source and independent role doubles; no model/network requests."""
import asyncio
from autolab import schemas as s
from autolab.implementation.models import ImplementationPlan, SourceBundle
from autolab.implementation.validation import required_requirements


def run(awaitable): return asyncio.run(awaitable)


def sources(plan):
    pin = plan.input_resources[0]
    source = '''from autolab.implementation.contract import BaseExperiment
import math
EXPERIMENT_ID = "EXP_PHASE9"
SPEC_HASH = "SPEC_PLACEHOLDER"
RESOURCE_ID = "RESOURCE_PLACEHOLDER"
RESOURCE_HASH = "HASH_PLACEHOLDER"

def validate_number(value):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
        raise ValueError("Finite number required")
    return value

def validate_samples(rows):
    if not isinstance(rows,list) or not rows:
        raise ValueError("No samples")
    seen = set()
    for row in rows:
        if not isinstance(row,dict) or not all(key in row for key in ("sample_id","prediction","target")):
            raise ValueError("Missing sample fields")
        if not isinstance(row["sample_id"],str) or row["sample_id"] in seen:
            raise ValueError("Invalid or duplicate sample identity")
        seen.add(row["sample_id"])
        validate_number(row["prediction"])
        validate_number(row["target"])
        if row["target"] < 0 or row["target"] > 1:
            raise ValueError("Target outside range")
    return rows

def compute_mae(predictions, targets):
    if not predictions or len(predictions) != len(targets):
        raise ValueError("Missing or unequal samples")
    for value in list(predictions) + list(targets):
        validate_number(value)
    return math.fsum(abs(p-t) for p,t in zip(predictions,targets)) / len(targets)

def predict(value, condition, max_calls):
    if max_calls < 1:
        raise RuntimeError("Budget exhausted")
    validate_number(value)
    if condition == "baseline":
        prediction = value
    elif condition == "clipped":
        prediction = min(1.0,max(0.0,value))
    else:
        raise ValueError("Unknown condition")
    return {"prediction":prediction,"calls":1}

class Experiment(BaseExperiment):
    def setup(self, context):
        if context["experiment_id"] != EXPERIMENT_ID or context["experiment_version"] != 1:
            raise ValueError("Wrong experiment")
        if context["resource_hashes"][RESOURCE_ID] != RESOURCE_HASH:
            raise ValueError("Resource changed")
        self.rows = validate_samples(context["resources"][RESOURCE_ID])
        self.sample_count = len(self.rows)
        self.seed = context["seed"]
        if self.seed != 19:
            raise ValueError("Wrong seed")
        self.observations = []

    def run(self, context):
        observations = []
        for condition in ("baseline","clipped"):
            for row in self.rows:
                result = predict(row["prediction"],condition,1)
                observations.append({"condition":condition,"sample_id":row["sample_id"],
                    "outputs":{"prediction":result["prediction"],"target":row["target"]},
                    "status":"success","counts":{"calls":result["calls"]}})
        self.observations = observations
        return self.collect_results(context)

    def collect_results(self, context):
        return {"experiment_id":EXPERIMENT_ID,"experiment_version":1,"observations":self.observations,"metadata":{"seed":self.seed}}
'''
    source = source.replace('SPEC_PLACEHOLDER',plan.spec_fingerprint).replace('RESOURCE_PLACEHOLDER',pin.resource_id).replace('HASH_PLACEHOLDER',pin.checksum)
    tests = '''from experiment import compute_mae, predict, validate_samples
import math
def test_metric():
    assert math.isclose(compute_mae([1.,2.,3.],[1.,4.,3.]),2/3)
def test_control():
    assert predict(1.2,"baseline",1) == {"prediction":1.2,"calls":1}
def test_intervention():
    assert predict(1.2,"clipped",1) == {"prediction":1.,"calls":1}
def test_reproducibility():
    assert predict(-0.2,"clipped",1) == predict(-0.2,"clipped",1)
'''
    return {'experiment.py':source,'test_experiment.py':tests}


class Implementer:
    def __init__(self, *, mutate_plan=None, mutate_source=None, response='ACCEPT'):
        self.mutate_plan = mutate_plan; self.mutate_source = mutate_source; self.response = response
        self.plan_calls = 0; self.code_calls = 0; self.contexts = []
    async def plan(self, context, assignment, *, previous=None, review=None):
        self.plan_calls += 1; self.contexts.append(context)
        spec = s.ExperimentSpec.model_validate(context['experiment_spec'])
        from autolab.implementation.models import ReviewResponse
        plan = ImplementationPlan(**assignment, objective=spec.objective,
            input_resources=context['resource_manifest']['resources'], expected_files=['experiment.py','test_experiment.py'],
            components=context['framework_adapter']['required_components'], conditions=spec.independent_variables,
            baseline=spec.controls, metrics=context['framework_adapter']['metric_components'],
            reproducibility=['Frozen ordering, resource hashes and seed19; no external inference'], seeds=[19],
            output_schema=context['raw_output_schema'], dependencies=['math'], tests=['Toy metric, control, intervention, budget, input validation'],
            limitations=['Four-row mechanics fixture is not generalization evidence'],
            requirement_mapping=[{'requirement':field,'component':'experiment.py:Experiment.setup','rationale':'Exact frozen contract validated and represented'} for field in required_requirements(spec)],
            issue_responses=[ReviewResponse(issue_index=i, disposition=self.response,
                evidence='Objective source evidence at predict; preserve exact scientific contract') for i,_ in enumerate(review.issues if review else [])])
        return self.mutate_plan(plan) if self.mutate_plan else plan
    async def generate(self, context, plan, **kwargs):
        self.code_calls += 1
        files = sources(plan)
        return SourceBundle(files=self.mutate_source(files) if self.mutate_source else files)


ISSUE = {'severity':'major','component':'experiment.py:predict','requirement':'controls.baseline',
    'problem':'Review fixture concern','impact':'Could change matched comparison','correction':'Verify identity control with source evidence'}


class Auditor:
    def __init__(self, *, sequence=('PASS',), mutate=None):
        self.sequence=list(sequence); self.calls=0; self.contexts=[]; self.mutate=mutate
    async def audit(self, context, assignment):
        self.calls+=1; self.contexts.append(context)
        verdict=self.sequence.pop(0) if len(self.sequence)>1 else self.sequence[0]
        record = s.ReviewRecord(**assignment, verdict=verdict, issues=[] if verdict=='PASS' else [ISSUE])
        return self.mutate(record) if self.mutate else record
