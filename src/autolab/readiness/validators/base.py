from dataclasses import dataclass, field
from typing import Protocol
from autolab import schemas as s


@dataclass
class ValidationEvidence:
    findings: list[dict] = field(default_factory=list)
    summaries: list[dict] = field(default_factory=list)

    def add(self, resource, check, passed, detail, gate='technical'):
        self.findings.append({'resource_id':resource.resource_id,'check':check,'passed':bool(passed),'detail':detail,'gate':gate})


class Validator(Protocol):
    def validate(self, resource: s.ResourceRecord, criteria, evidence: ValidationEvidence, data): ...
