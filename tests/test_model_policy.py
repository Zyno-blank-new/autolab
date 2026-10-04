"""Model policy, API wiring, and reproducibility checks; no live requests."""
import asyncio
import json
from types import SimpleNamespace

import pytest
import yaml

from autolab import schemas as s
from autolab.config import PROJECT_ROOT, DEFAULT_REASONING_MODEL
from autolab.planner import service


@pytest.mark.parametrize("role,effort", [
    ("planner", "high"), ("evidence", "medium"), ("hypothesis", "high"),
    ("critic", "high"), ("experiment_designer", "high"),
    ("preparation", "high"), ("readiness", "high"),
    ("implementer", "high"), ("code_auditor", "high"), ("analyst", "high"),
])
def test_production_policy_survives_actual_omnigent_loading(role, effort, tmp_path):
    from omnigent.spec import load
    path = PROJECT_ROOT / "agents" / role / (role + ".yaml")
    definition = yaml.safe_load(path.read_text())
    assert definition["executor"]["harness"] == "openai-agents"
    assert definition["executor"]["model"] == DEFAULT_REASONING_MODEL == "gpt-6.1-sol"
    assert definition["executor"]["reasoning_effort"] == effort
    # The exact bundle passed to the official CLI/server must retain effort.
    bundle = service.prepare_agent_bundle(path, tmp_path / "bundle")
    uploaded = load(bundle, expand_env=False)
    assert uploaded.executor.model == "gpt-6.1-sol"
    assert uploaded.executor.reasoning_effort == effort
    assert uploaded.executor.type == "omnigent"
    assert uploaded.executor.config["harness"] == "openai-agents"
    from omnigent.runtime.workflow import _config_flag_is_true
    assert _config_flag_is_true(uploaded.executor.config["use_responses"])
    assert uploaded.instructions == definition["prompt"]


def test_ad_hoc_default_is_pinned_without_overriding_explicit_config(monkeypatch):
    from autolab import config
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("OMNIGENT_MODEL", raising=False)
    config.configure()
    assert config.os.environ["OMNIGENT_MODEL"] == "gpt-6.1-sol"
    monkeypatch.setenv("OMNIGENT_MODEL", "explicit-user-model")
    config.configure()
    assert config.os.environ["OMNIGENT_MODEL"] == "explicit-user-model"


@pytest.mark.parametrize("effort", ["medium", "high"])
def test_installed_harness_uses_responses_and_preserves_reasoning(effort):
    import inspect
    from agents import OpenAIProvider
    from agents.models.openai_responses import OpenAIResponsesModel
    from omnigent.inner.openai_agents_sdk_executor import (
        OpenAIAgentsSDKExecutor, _build_reasoning_model_settings,
    )
    assert inspect.signature(OpenAIAgentsSDKExecutor).parameters["use_responses"].default is True
    # Inject a non-network client; resolving a model makes no request.
    provider = OpenAIProvider(openai_client=object(), use_responses=True)
    model = provider.get_model("gpt-6.1-sol")
    assert isinstance(model, OpenAIResponsesModel)
    assert model.model == "gpt-6.1-sol"
    assert _build_reasoning_model_settings(effort)["reasoning"].effort == effort


def test_installed_function_tool_bridge_returns_to_omnigent():
    import agents
    from omnigent.inner.openai_agents_sdk_executor import OpenAIAgentsSDKExecutor
    executor = object.__new__(OpenAIAgentsSDKExecutor)
    received = []

    async def dispatch(name, arguments):
        received.append((name, arguments))
        return {"answer": arguments["value"] + 1}

    executor._tool_executor = dispatch
    tools = executor._build_tools(agents, [{"name": "fixture_increment",
        "description": "Offline compatibility fixture",
        "parameters": {"type": "object", "properties": {"value": {"type": "integer"}},
                       "required": ["value"], "additionalProperties": False}}])
    assert len(tools) == 1
    result = asyncio.run(tools[0].on_invoke_tool(None, '{"value":7}'))
    assert result == {"answer": 8}
    assert received == [("fixture_increment", {"value": 7})]


@pytest.mark.parametrize("override", [None, "explicit-user-model"])
def test_transport_records_requested_model_and_explicit_override(monkeypatch, tmp_path, override):
    captured = []
    monkeypatch.setattr(service, "configure", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture-credential")
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))

    class Process:
        returncode = 0
        async def communicate(self):
            return b'{"status":"ok"}', b""

    async def spawn(*args, **kwargs):
        captured.append(args)
        return Process()

    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", spawn)
    client = service.OmnigentPlanner(model=override)
    path = PROJECT_ROOT / "agents/evidence/evidence.yaml"
    assert asyncio.run(client.invoke_agent(path, "fixture", project_id="PROJECT_0001", role="evidence"))
    metadata = service.runtime_metadata(client)
    assert metadata["model"] == (override or "gpt-6.1-sol")
    assert metadata["reasoning_effort"] == "medium"
    assert metadata["harness"] == "openai-agents"
    assert metadata["omnigent_version"] == "0.16.0"
    assert metadata["source"] == "invocation_configuration"
    assert metadata["role"] == "evidence" and metadata["invocation"] == 1
    assert "offline-fixture-credential" not in json.dumps(metadata)
    if override:
        assert captured[0][captured[0].index("--model") + 1] == override
    else:
        assert "--model" not in captured[0]  # YAML owns the exact model.
    metadata["model"] = "changed copy"
    assert client.last_model_metadata["model"] == (override or "gpt-6.1-sol")


def test_unavailable_model_fails_once_without_fallback(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(service, "configure", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture-credential")
    monkeypatch.setenv("OMNIGENT_DATA_DIR", str(tmp_path))

    class Process:
        returncode = 1
        async def communicate(self):
            return b"", b"model_not_found: gpt-6.1-sol unavailable offline-fixture-credential"

    async def spawn(*args, **kwargs):
        captured.append(args)
        return Process()

    monkeypatch.setattr(service.asyncio, "create_subprocess_exec", spawn)
    client = service.OmnigentPlanner()
    with pytest.raises(service.PlannerInvocationError, match="model_not_found") as error:
        asyncio.run(client.invoke_agent(PROJECT_ROOT / "agents/planner/planner.yaml",
            "fixture", project_id="PROJECT_0001", role="planner"))
    assert len(captured) == client.calls == 1
    assert "offline-fixture-credential" not in str(error.value)
    assert client.last_model_metadata["model"] == "gpt-6.1-sol"
    assert not any("gpt-5.4" in part for part in captured[0])


def test_planner_model_metadata_is_persisted_with_its_decision(ledger):
    from autolab.orchestration.orchestrator import Orchestrator
    ledger.create_project(s.ResearchCharter(project_id="PROJECT_0001", title="Policy fixture",
        research_question="Which method is more reliable?", objective="Measure reliability",
        primary_outcome="Success", budget_usd=10, max_runtime_minutes=60))

    class Planner:
        last_model_metadata = {"model": "gpt-6.1-sol", "reasoning_effort": "high", "role": "planner"}
        async def propose(self, context, decision_id, feedback=None):
            return s.NextDecision(decision_id=decision_id, project_id="PROJECT_0001",
                action="GATHER_EVIDENCE", target_agent="evidence", reason="Gather real sources",
                remaining_budget_usd=10).model_dump_json()

    route = asyncio.run(Orchestrator(ledger, Planner()).decide("PROJECT_0001"))
    event = ledger.list_events("PROJECT_0001")[0]
    assert event.payload["decision_id"] == route.decision_id
    assert event.payload["model_metadata"] == Planner.last_model_metadata


def test_specialist_events_keep_model_identity_and_review_role(ledger):
    from autolab.literature.service import EvidencePipeline
    from autolab.hypotheses.service import HypothesisPipeline
    hypothesis = SimpleNamespace(transport=SimpleNamespace(last_model_metadata={"model": "gpt-6.1-sol", "role": "hypothesis"}))
    critic = SimpleNamespace(transport=SimpleNamespace(last_model_metadata={"model": "gpt-6.1-sol", "role": "critic"}))
    evidence = SimpleNamespace(transport=SimpleNamespace(last_model_metadata={"model": "gpt-6.1-sol", "role": "evidence", "reasoning_effort": "medium"}))
    pipeline = HypothesisPipeline(ledger, hypothesis, critic)
    proposal = pipeline._event("PROJECT_0001", "HYPOTHESIS_CREATED", "Fixture")
    review = pipeline._event("PROJECT_0001", "HYPOTHESIS_REVIEWED", "Fixture")
    assert proposal.payload["model_metadata"]["role"] == "hypothesis"
    assert review.payload["model_metadata"]["role"] == "critic"
    output = EvidencePipeline(ledger, evidence)._event("PROJECT_0001", "EVIDENCE_ADDED", "Fixture")
    assert output.payload["model_metadata"]["reasoning_effort"] == "medium"
    started = pipeline._event("PROJECT_0001", "HYPOTHESIS_GENERATION_STARTED", "Fixture")
    assert "model_metadata" not in started.payload


def test_designer_output_contract_disallows_scores_its_existing_gate_rejects():
    from autolab.experiment_design.models import CandidateBatch, CandidateRevision
    from autolab.experiment_design.validation import proposal_output_schema
    for envelope in (CandidateBatch, CandidateRevision):
        candidate = proposal_output_schema(envelope)["$defs"]["ExperimentCandidate"]
        for field in ("expected_information_gain", "feasibility_score"):
            assert field in candidate["required"]
            assert candidate["properties"][field]["type"] == "number"
            assert candidate["properties"][field]["minimum"] == 0
            assert candidate["properties"][field]["maximum"] == 1
        assert "major_risks" in candidate["required"]
        assert candidate["properties"]["major_risks"]["minItems"] == 1
    # Historical canonical records are not migrated or made incompatible.
    canonical = s.ExperimentCandidate.model_json_schema()["properties"]
    assert {x.get("type") for x in canonical["expected_information_gain"]["anyOf"]} == {"number", "null"}
