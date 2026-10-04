"""One Omnigent model turn; no specialists or discovery loop.

Uses Omnigent 0.16.0's own YAML loader and OpenAI harness executor.
These are internal Python APIs, so the installed Omnigent version is pinned.
JSON is requested in the prompt and validated afterward, rather than claiming
provider-enforced structured output support in Omnigent's current adapter.
"""
import argparse
import asyncio
import json
import os
import sys
import yaml
from importlib.metadata import version

from autolab.config import PROJECT_ROOT, configure
from autolab.smoke_schemas import NextDecision, ResearchQuestion

SPECIALISTS = ["evidence", "hypothesis", "experiment_designer", "experiment_runner", "analyst", "critic"]

def load_planner():
    from omnigent.inner.loader import load_agent_def
    return load_agent_def(PROJECT_ROOT / "agents/planner/planner.yaml")

async def run_planner() -> NextDecision:
    from omnigent.inner.executor import ExecutorConfig, ExecutorError, TurnComplete
    from omnigent.inner.openai_agents_sdk_executor import OpenAIAgentsSDKExecutor
    planner = load_planner()
    settings = yaml.safe_load((PROJECT_ROOT / "agents/planner/planner.yaml").read_text())["executor"]
    question = ResearchQuestion(
        question="Does error-aware recovery improve tool-using AI agent reliability compared with blind retry?",
        domain="AI agent reliability",
        objective="Compare recovery strategies using measurable evidence.",
    )
    request = {
        "research_question": question.model_dump(),
        "current_research_state": {"evidence": [], "hypotheses": []},
        "available_specialist_agents": SPECIALISTS,
        "previous_experiment_results": [],
    }
    executor = OpenAIAgentsSDKExecutor(model=planner.executor.model)
    response = None
    try:
        async with asyncio.timeout(60):
            async for event in executor.run_turn(
                messages=[{"role": "user", "content": json.dumps(request)}],
                tools=[],
                system_prompt=(planner.prompt or "") + "\nJSON schema: " + json.dumps(NextDecision.model_json_schema()),
                config=ExecutorConfig(extra={"max_tokens": 2048, "reasoning_effort": settings["reasoning_effort"]}),
            ):
                if isinstance(event, ExecutorError):
                    # Do not print provider exception payloads or headers.
                    raise RuntimeError("Omnigent reported a model error. Check API access, billing, model availability, and network.")
                if isinstance(event, TurnComplete):
                    response = event.response
        if not response:
            raise RuntimeError("Omnigent returned no final response.")
        decision = NextDecision.model_validate_json(response)
        if decision.target_agent is not None and decision.target_agent not in SPECIALISTS:
            raise RuntimeError("Planner selected an unavailable specialist.")
        return decision
    finally:
        await executor.close()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate imports, YAML and parser without a model call.")
    args = parser.parse_args()
    configure()
    from omnigent.inner.openai_agents_sdk_executor import OpenAIAgentsSDKExecutor
    planner = load_planner()
    assert planner.name == "planner" and planner.executor.harness == "openai-agents"
    print(f"Python environment and Omnigent {version('omnigent')} OpenAI harness: OK")
    present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    print("OpenAI key configured: " + ("yes (value hidden)" if present else "no"))
    if args.check:
        NextDecision.model_validate_json('{"action":"gather_evidence","reason":"Parser fixture only","next_question":null,"target_agent":"evidence"}')
        print("Planner YAML and structured-output parser: OK (offline fixture; no model call)")
        return 0
    if not present:
        print("LIVE TEST BLOCKED: add OPENAI_API_KEY to .env and rerun. No model request was made.", file=sys.stderr)
        return 2
    try:
        decision = asyncio.run(run_planner())
    except Exception as exc:
        print(f"LIVE TEST FAILED ({type(exc).__name__}); no successful decision was validated. Check key, network, billing, and model access.", file=sys.stderr)
        return 1
    print(decision.model_dump_json(indent=2))
    print("PASS: Omnigent model request completed and NextDecision parsed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
