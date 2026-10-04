class ProvenanceValidator:
    def validate(self, resource, criteria, evidence, data):
        m=resource.metadata
        keys=['plan_id','plan_version','requirement_id','spec_fingerprint','acquisition_mode','creation_tool','configuration','criteria']
        good=bool(resource.checksum and len(resource.checksum)==64 and all(k in m for k in keys))
        if m.get('acquisition_mode') in ('GENERATE','SYNTHESIZE'):
            good=good and all(k in m for k in ('generator','seed','specification','generation_parameters','intended_role'))
        if m.get('acquisition_mode') in ('TRANSFORM','DERIVE'):
            good=good and bool(m.get('parent_ids') and m.get('parent_checksums'))
        evidence.add(resource,'provenance',good,'Creation, source, parameters, parents and exact contract are traceable','resource')
