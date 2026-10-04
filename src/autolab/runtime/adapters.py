"""Operator-owned adapters bind raw coverage and metric arguments to a spec.

No generic metric is inferred from a metric name or from an LLM response.
Unsupported scientific protocols require a reviewed adapter before execution.
"""
from abc import ABC, abstractmethod


class RuntimeAdapter(ABC):
    adapter_id: str
    spec_hash: str
    seed: int
    deterministic: bool = True

    def validate_spec(self, spec, plan):
        from .models import RuntimeErrorRecord
        registered={spec.primary_metric,*spec.secondary_metrics}
        if set(plan.metrics)!=registered: raise RuntimeErrorRecord('Incomplete preregistered metric bindings')

    @abstractmethod
    def context(self, spec, resources, hashes): ...

    @abstractmethod
    def observation_limit(self, resources): ...

    @abstractmethod
    def metric_jobs(self, observations, resources, implementation_plan):
        """Reject incomplete coverage/failures unless the exact contract resolves them."""

    @abstractmethod
    def independently_recompute(self, job, observations): ...


class ScalarFixtureAdapter(RuntimeAdapter):
    """Only the preregistered paired scalar fixture; not a universal MAE policy."""
    adapter_id = 'paired-scalar-fixture-v1'
    seed = 19
    supported_metrics = {'mean_absolute_error'}

    def __init__(self, spec_hash): self.spec_hash = spec_hash

    def validate_spec(self,spec,plan):
        from .models import RuntimeErrorRecord
        super().validate_spec(spec,plan)
        if (not set(plan.metrics)<=self.supported_metrics or spec.independent_variables!=
            {'condition':['baseline','clipped'],'seed':19,'max_calls_per_sample':1}):
            raise RuntimeErrorRecord('Scalar fixture adapter does not support this metric/condition contract')

    def context(self, spec, resources, hashes):
        return {'experiment_id':spec.experiment_id,'experiment_version':spec.version,
                'seed':self.seed,'resources':resources,'resource_hashes':hashes}

    def observation_limit(self, resources):
        from .models import RuntimeErrorRecord
        rows=next(iter(resources.values()))
        if not isinstance(rows,list) or len(rows)!=4: raise RuntimeErrorRecord('Scalar fixture requires exactly four approved samples')
        return 2*len(rows)

    def metric_jobs(self, observations, resources, implementation_plan):
        import math
        from .models import MetricJob, RuntimeErrorRecord
        rows = next(iter(resources.values()))
        expected = [(condition,row) for condition in ('baseline','clipped') for row in rows]
        if len(observations) != len(expected): raise RuntimeErrorRecord('Missing/extra paired sample observations')
        for observation,(condition,row) in zip(observations,expected):
            if (observation.condition,observation.sample_id) != (condition,row['sample_id']):
                raise RuntimeErrorRecord('Missing, duplicate or misordered sample/condition')
            if observation.status != 'success':
                raise RuntimeErrorRecord('Failed sample retained; this MAE contract forbids a successful-only denominator')
            out = observation.outputs
            if out.get('target') != row['target']: raise RuntimeErrorRecord('Scoring reference mismatch')
            wanted = row['prediction'] if condition=='baseline' else min(1.,max(0.,row['prediction']))
            value=out.get('prediction')
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value != wanted:
                raise RuntimeErrorRecord('Raw prediction violates approved rule')
            calls=observation.counts.get('rule_calls',observation.counts.get('calls'))
            if calls != 1 or observation.failure_category is not None: raise RuntimeErrorRecord('Budget/status mismatch')
        jobs=[]
        for name,component in implementation_plan.metrics.items():
            # A secondary metric is admitted only with an explicit adapter oracle.
            if name != 'mean_absolute_error': raise RuntimeErrorRecord('Unsupported preregistered metric adapter')
            for condition in ('baseline','clipped'):
                group=[o for o in observations if o.condition==condition]
                args=[[o.outputs['prediction'] for o in group],[o.outputs['target'] for o in group]]
                jobs.append(MetricJob(metric_name=name,role='primary',condition=condition,component=component,
                    args=args,denominator=len(rows),support={'absolute_error_sum':math.fsum(abs(p-t) for p,t in zip(*args)),
                    'failed_samples':0,'expected_samples':len(rows)},unit='prediction units'))
        return jobs

    def independently_recompute(self, job, observations):
        import math
        if job.metric_name != 'mean_absolute_error': raise ValueError('Independent oracle missing')
        group=[o for o in observations if o.condition==job.condition]
        if len(group)!=job.denominator: raise ValueError('Denominator mismatch')
        return math.fsum(abs(o.outputs['prediction']-o.outputs['target']) for o in group)/job.denominator
