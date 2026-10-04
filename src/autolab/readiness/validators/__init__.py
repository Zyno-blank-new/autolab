from .base import ValidationEvidence
from .files import FileValidator
from .dataset import DatasetValidator
from .split import SplitValidator
from .provenance import ProvenanceValidator


class ValidatorRegistry:
    def __init__(self, validators=None):
        self.files=FileValidator()
        self.validators=list(validators) if validators is not None else [DatasetValidator(),SplitValidator(),ProvenanceValidator()]

    def register(self, validator):
        self.validators.append(validator)

    def validate(self, snapshot, manifest):
        evidence=ValidationEvidence()
        for pin in manifest.resources:
            record=next((r for r in snapshot.resources if r.resource_id==pin.resource_id),None)
            if record is None:
                evidence.findings.append({'resource_id':pin.resource_id,'check':'resource_resolves','passed':False,'detail':'Missing canonical resource','gate':'resource'})
                continue
            data=self.files.load(record,evidence)
            if data is not None:
                for validator in self.validators:
                    if hasattr(validator,"validate"):
                        validator.validate(record,manifest.validation_requirements[pin.requirement_id],evidence,data)
        for validator in self.validators:
            if hasattr(validator,'validate_collection'):
                validator.validate_collection(snapshot,manifest,evidence)
        return evidence
