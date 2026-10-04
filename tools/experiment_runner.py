"""Deterministic numeric-array comparison. No arbitrary code execution."""
import math
from typing import Mapping
from autolab.smoke_schemas import ExperimentResult, ExperimentSpec


async def run_approved_experiment(ledger, project_id, *, adapters, root=None, **limits):
    """Canonical Phase 10 entry point, preserving the Phase 1 array smoke API.

    The runtime itself enforces exact approval, readiness and audited code;
    this deterministic tool never dispatches an LLM or interprets measurements.
    """
    from autolab.runtime.service import ExperimentRuntime
    options={'adapters':adapters}
    if root is not None: options['root']=root
    return await ExperimentRuntime(ledger,**options).run(project_id,**limits)

def run_experiment(experiment_spec: ExperimentSpec | Mapping) -> ExperimentResult:
    spec = experiment_spec if isinstance(experiment_spec, ExperimentSpec) else ExperimentSpec.model_validate(experiment_spec)
    try:
        if spec.experiment_type != "compare_arrays":
            raise ValueError("Only compare_arrays is supported for this setup.")
        if spec.tool != "experiment_runner":
            raise ValueError("Unsupported tool.")
        arrays = []
        for name in ("a", "b"):
            values = spec.variables.get(name)
            if not isinstance(values, list) or not values:
                raise ValueError(f"{name} must be a nonempty numeric list.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError(f"{name} must contain finite numbers only.")
            arrays.append(values)
        a, b = arrays
        if len(a) != len(b):
            raise ValueError("Arrays must have equal length.")
        metrics = {"mean_absolute_error": math.fsum(abs(x-y) for x,y in zip(a,b)) / len(a)}
        if not math.isfinite(metrics["mean_absolute_error"]):
            raise ValueError("Metric overflowed.")
        return ExperimentResult(experiment_id=spec.id, status="success", metrics=metrics, observations=[f"Compared {len(a)} pairs."])
    except (ValueError, OverflowError) as exc:
        return ExperimentResult(experiment_id=spec.id, status="error", errors=[str(exc)])

def smoke_test() -> None:
    spec = ExperimentSpec(id="setup-001", hypothesis_id="setup-hypothesis", experiment_type="compare_arrays", variables={"a": [1,2,3], "b": [1,4,3]}, metrics=["mean_absolute_error"])
    result = run_experiment(spec)
    assert result.status == "success"
    assert math.isclose(result.metrics["mean_absolute_error"], 2/3)
    assert result == run_experiment(spec.model_dump())
    for variables in ({"a": [], "b": []}, {"a": [1], "b": [1,2]}, {"a": [float("nan")], "b": [1]}, {"a": [True], "b": [1]}):
        assert run_experiment(spec.model_copy(update={"variables": variables})).status == "error"
    assert run_experiment(spec.model_copy(update={"experiment_type": "unsupported"})).status == "error"
    print(result.model_dump_json(indent=2))
    print("PASS: deterministic experiment metric and invalid-input checks.")

if __name__ == "__main__":
    smoke_test()
