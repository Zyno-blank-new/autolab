import json
from collections import Counter

TYPES={'string':str,'number':(int,float),'integer':int,'boolean':bool,'object':dict,'array':list}


class DatasetValidator:
    def validate(self, resource, criteria, evidence, data):
        needs_rows=bool(criteria.required_fields or criteria.min_samples or criteria.required_conditions)
        if not needs_rows:
            sample=data if isinstance(data,dict) else str(data)[:1800]
            evidence.summaries.append({'resource_id':resource.resource_id,'kind':'configuration','sample':sample})
            return
        rows=data if isinstance(data,list) else data.get('records',[data]) if isinstance(data,dict) else None
        good=isinstance(rows,list) and all(isinstance(r,dict) for r in rows)
        evidence.add(resource,'dataset_schema',good,'Structured row collection required')
        if not good: return
        evidence.add(resource,'sample_count',len(rows)>=criteria.min_samples,f'{len(rows)} rows; minimum {criteria.min_samples}')
        fields=criteria.required_fields
        evidence.add(resource,'required_fields',all(all(k in r and r[k] not in (None,'') for k in fields) for r in rows),'Required nonmissing fields')
        def correct(row):
            return all(k in row and isinstance(row[k],TYPES[t]) and not (t in ('number','integer') and isinstance(row[k],bool)) for k,t in criteria.field_types.items())
        evidence.add(resource,'field_types',all(correct(r) for r in rows),'Declared field types')
        keys=criteria.unique_fields
        normalized=[json.dumps({k:r.get(k) for k in keys} if keys else r,sort_keys=True) for r in rows]
        duplicates=len(rows)-len(set(normalized))
        evidence.add(resource,'duplicates',duplicates==0,f'{duplicates} duplicate rows/groups','quality')
        counts=Counter(str(r.get(criteria.condition_field)) for r in rows) if criteria.condition_field else {}
        if criteria.required_conditions:
            evidence.add(resource,'condition_coverage',all(counts.get(c,0)>=criteria.min_per_condition for c in criteria.required_conditions),str(dict(counts)),'scientific')
        suspicious=[]
        if criteria.label_field:
            forbidden=(set(criteria.forbidden_input_fields)|{criteria.label_field})&set(criteria.input_fields)
            matches=[r for r in rows if any(k in r and criteria.label_field in r and r[k]==r[criteria.label_field]
                for k in criteria.input_fields if k!=criteria.label_field)]
            # A correct numeric prediction can equal its target. Equality does
            # not establish access to the scoring label; retain it for semantic
            # review instead of claiming a deterministic leakage observation.
            categorical_copies=[k for k in criteria.input_fields if k!=criteria.label_field and rows
                and all(isinstance(r.get(criteria.label_field),str) and k in r
                    and r[k]==r[criteria.label_field] for r in rows)]
            suspicious=matches[:4]
            evidence.add(resource,'target_leakage',not forbidden and not categorical_copies,
                f'Forbidden input fields {sorted(forbidden)}; categorical label-copy fields {categorical_copies}; '
                f'{len(matches)} rows have equal input/target values (equality alone does not establish numeric target access)','scientific')
        # Reproducible stratified reservoir, bounded across all resources by service.
        representatives=[]
        for condition in sorted(counts) if counts else [None]:
            pool=[r for r in rows if condition is None or str(r.get(criteria.condition_field))==condition]
            for row in (pool[:1]+pool[-1:]):
                if row not in representatives: representatives.append(row)
        if isinstance(data,dict) and 'records' not in data:
            evidence.summaries.append({'resource_id':resource.resource_id,'kind':'configuration','sample':data,'count':1,'schema':sorted(data)})
            return
        evidence.summaries.append({'resource_id':resource.resource_id,'count':len(rows),
            'schema':sorted({k for r in rows for k in r}), 'condition_counts':dict(counts),'duplicates':duplicates,
            'samples':rows if len(rows)<=12 else representatives[:12],'suspicious_samples':suspicious,
            'sampling_limit':'Complete rows for at most twelve samples; otherwise bounded deterministic strata endpoints. Overall audit sample limits still apply.'})
