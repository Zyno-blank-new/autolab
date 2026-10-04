"""Extensible declared capabilities; detection performs no access or preparation."""
import os
import sys
from pathlib import Path

from .models import Capability, CapabilityStatus as S


class CapabilityRegistry:
    def __init__(self, capabilities=()):
        self.capabilities = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability):
        capability = Capability.model_validate(capability.model_dump() if isinstance(capability, Capability) else capability)
        if capability.capability_id in self.capabilities:
            raise ValueError("Capability already registered.")
        self.capabilities[capability.capability_id] = capability

    def get(self, identifier):
        return self.capabilities.get(identifier, Capability(capability_id=identifier, status=S.UNKNOWN,
            notes=["No explicit capability configuration or verification is available."]))

    def check(self, identifiers):
        checked = {}
        def visit(identifier):
            if identifier in checked:
                return
            capability = self.get(identifier)
            checked[identifier] = capability
            for dependency in capability.requires_capabilities:
                visit(dependency)
        for identifier in identifiers:
            visit(identifier)
        return list(checked.values())

    @classmethod
    def local(cls, root: Path, environment=None):
        environment = os.environ if environment is None else environment
        credential = bool(environment.get("OPENAI_API_KEY", "").strip())
        capabilities = [
            Capability(capability_id="python_execution", status=S.AVAILABLE, provider=sys.executable,
                       notes=["Python is running; no experiment code was executed."]),
            Capability(capability_id="local_cpu", status=S.AVAILABLE if os.cpu_count() else S.UNKNOWN,
                       provider="local", notes=["CPU presence only; workload performance is unknown."]),
            Capability(capability_id="filesystem_access", status=S.AVAILABLE if os.access(root, os.R_OK | os.W_OK) else S.UNAVAILABLE,
                       provider="local", notes=["Project path permission check only; no resources created."]),
        ]
        for identifier in ("openai_api", "llm_inference"):
            capabilities.append(Capability(capability_id=identifier,
                status=S.AVAILABLE if credential else S.REQUIRES_CREDENTIAL, provider="OpenAI / Omnigent",
                configuration_requirement="Configured provider and permitted network access",
                credential_requirement="OPENAI_API_KEY",
                cost_driver="LLM/API inference",
                requires_capabilities=["network_access"],
                notes=["Credential presence only; provider reachability and model entitlement were not probed."]))
        for identifier in ("network_access", "multimodal_model_access", "image_generation", "image_understanding",
                           "local_gpu", "package_installation", "dataset_download", "hugging_face_access"):
            capabilities.append(Capability(capability_id=identifier, status=S.UNKNOWN,
                notes=["Requires explicit configuration; Phase 7 performs no network probe, download, generation or installation."]))
        return cls(capabilities)
