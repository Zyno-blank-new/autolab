"""Offline regressions for existing utilities; never send model requests."""
import asyncio
import json
import subprocess
import sys

from autolab.config import PROJECT_ROOT


def test_existing_omnigent_cli_launch_path():
    result = subprocess.run(
        [sys.executable, "-m", "autolab.launch", "--version"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=20,
    )
    assert "omnigent 0.16.0" in result.stdout


def test_existing_planner_check_still_works():
    result = subprocess.run(
        [sys.executable, "-m", "autolab.planner_smoke", "--check"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=20,
    )
    assert "Planner YAML and structured-output parser: OK" in result.stdout
    assert "offline fixture; no model call" in result.stdout


def test_original_planner_adapter_uses_original_contract(monkeypatch):
    from autolab.planner_smoke import run_planner
    from omnigent.inner.executor import TurnComplete
    from omnigent.inner import openai_agents_sdk_executor as adapter

    observed = {}
    class FixtureExecutor:
        def __init__(self, **kwargs):
            observed["constructor"] = kwargs
        async def run_turn(self, **kwargs):
            observed["request"] = kwargs
            yield TurnComplete(response=json.dumps({
                "action": "gather_evidence", "reason": "Synthetic adapter regression",
                "next_question": None, "target_agent": "evidence",
            }))
        async def close(self):
            observed["closed"] = True
    monkeypatch.setattr(adapter, "OpenAIAgentsSDKExecutor", FixtureExecutor)
    result = asyncio.run(run_planner())
    assert result.action == "gather_evidence"
    assert result.target_agent == "evidence"
    assert observed["closed"]
    assert observed["request"]["tools"] == []
    assert json.loads(observed["request"]["messages"][0]["content"])["research_question"]["question"]


def test_existing_deterministic_experiment_smoke():
    result = subprocess.run(
        [sys.executable, "tools/experiment_runner.py"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True, timeout=20,
    )
    assert "PASS: deterministic experiment metric" in result.stdout


def test_secrets_and_generated_databases_remain_ignored():
    paths = [".env", ".venv/bin/python", ".omnigent/config.yaml",
             "research_state/autolab.db", "research_state/autolab.db-shm",
             "research_state/autolab.db-wal", "research_state/autolab.db-journal"]
    result = subprocess.run(["git", "check-ignore", *paths], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, check=True)
    assert set(result.stdout.splitlines()) == set(paths)
    for name in (".env.example", "research_state/.gitkeep"):
        assert subprocess.run(["git", "check-ignore", "-q", name], cwd=PROJECT_ROOT).returncode == 1
    tracked = subprocess.run(["git", "ls-files", "--", *paths], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, check=True)
    assert not tracked.stdout.strip()
