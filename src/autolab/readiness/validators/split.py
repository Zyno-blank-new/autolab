import json


class SplitValidator:
    def validate(self, resource, criteria, evidence, data):
        if not criteria.split_field: return
        rows=data if isinstance(data,list) else data.get('records',[]) if isinstance(data,dict) else []
        groups={}; content={}; overlap=False
        for row in rows:
            if not isinstance(row,dict): continue
            split=row.get(criteria.split_field)
            key=json.dumps([row.get(k) for k in criteria.split_group_fields],sort_keys=True)
            if criteria.split_group_fields:
                groups.setdefault(key,set()).add(str(split))
            if criteria.input_fields:
                key=json.dumps([row.get(k) for k in criteria.input_fields],sort_keys=True)
                content.setdefault(key,set()).add(str(split))
            if split is None: overlap=True
        overlap=overlap or any(len(v)>1 for v in (*groups.values(),*content.values()))
        evidence.add(resource,'split_independence',not overlap,'Group and content separation across declared splits','scientific')
