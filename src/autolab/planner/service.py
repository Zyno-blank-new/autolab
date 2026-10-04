"""Invoke the actual Omnigent CLI/server, never an OpenAI client directly."""
import asyncio
import logging
import os
import re
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from autolab.config import PROJECT_ROOT, configure
from autolab.orchestration.models import PlannerContext
from .prompt import planner_request

log = logging.getLogger(__name__)


class PlannerOutputError(RuntimeError):
    pass


class PlannerInvocationError(RuntimeError):
    pass


def runtime_metadata(client) -> dict:
    """Identify a completed invocation without storing credentials or prompts."""
    transport = getattr(client, "transport", client)
    metadata = getattr(transport, "last_model_metadata", {})
    return dict(metadata) if isinstance(metadata, dict) else {}


def prepare_agent_bundle(agent_path: Path, destination: Path) -> Path:
    """Use Omnigent's supported bundle format to preserve reasoning effort.

    Omnigent 0.16.0's standalone YAML adapter drops the effort setting.
    Its config.yaml parser and server/session path preserve it. This narrow
    adapter supports the existing tool-free AutoLab agents, without changing
    their prompts or replacing Omnigent's harness or dispatch.
    """
    definition = yaml.safe_load(agent_path.read_text())
    executor = definition.get("executor", {})
    if (set(definition) - {"name", "executor", "prompt", "tools", "async"}
        or set(executor) - {"harness", "model", "reasoning_effort"}
        or executor.get("harness") != "openai-agents"
        or definition.get("tools") or definition.get("async")):
        raise PlannerInvocationError("Agent configuration exceeds the supported AutoLab model-policy adapter; use an explicit compatible Omnigent bundle.")
    if not executor.get("model") or executor.get("reasoning_effort") not in {"medium", "high"}:
        raise PlannerInvocationError("Agent must declare an explicit model and supported reasoning effort; no fallback is permitted.")
    destination.mkdir(parents=True, exist_ok=True)
    config = {"spec_version": 1, "name": definition["name"],
        "instructions": definition["prompt"], "executor": {
            "type": "omnigent", "model": executor["model"],
            "reasoning_effort": executor["reasoning_effort"],
            "config": {"harness": "openai-agents", "use_responses": True}}, "tools": {}}
    (destination / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return destination


def scrub_cached_credentials(data_dir: Path, key: str) -> int:
    """Redact resolved credentials in Omnigent's generated bundle copies.

    The CLI uploads a fresh copy of the source YAML for each invocation, so
    these diagnostic cache copies need no reusable credential after completion.
    Never touch .env or the source agent configuration.
    """
    count = 0
    if not key:
        return count
    for path in (data_dir / "artifacts" / ".cache").rglob("*.yaml"):
        content = path.read_bytes()
        if key.encode() in content:
            path.chmod(0o600)
            path.write_bytes(content.replace(key.encode(), b"[REDACTED]"))
            count += 1
    return count


class OmnigentPlanner:
    def __init__(self, *, timeout_seconds: float = 180, model: str | None = None):
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.calls = 0
        self.last_model_metadata = {}

    async def propose(self, context: PlannerContext, decision_id: str, feedback: dict | None = None) -> str:
        return await self.invoke_agent(PROJECT_ROOT / "agents/planner/planner.yaml",
                                       planner_request(context, decision_id, feedback),
                                       project_id=context.charter.project_id, role="planner")

    async def invoke_agent(self, agent_path: Path, prompt: str, *, project_id: str, role: str) -> str:
        configure()
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise PlannerInvocationError("OPENAI_API_KEY is missing; add it privately to .env.")
        # Public CLI matches the proven Phase 1 path; the agent remains named
        # planner and runs inside Omnigent's local control/server architecture.
        command = [sys.executable, "-m", "autolab.launch", "run", str(agent_path),
                   "--server", "local", "--no-log", "-p", prompt]
        if self.model:
            command.extend(["--model", self.model])
        executor = yaml.safe_load(agent_path.read_text())["executor"]
        requested_model = self.model or executor.get("model")
        if not requested_model:
            raise PlannerInvocationError("Agent configuration must declare an explicit model; no fallback is permitted.")
        self.calls += 1
        # These are the exact requested settings, not provider-reported snapshot
        # metadata. Omnigent receives the YAML and any explicit model override.
        self.last_model_metadata = {"model": requested_model,
            "reasoning_effort": executor.get("reasoning_effort"),
            "harness": executor.get("harness"), "omnigent_version": version("omnigent"),
            "role": role, "invocation": self.calls, "source": "invocation_configuration"}
        log.info("%s_INVOKED project=%s attempt=%d transport=omnigent-cli", role.upper(), project_id, self.calls)
        with TemporaryDirectory(prefix="autolab-agent-config-") as directory:
            command[4] = str(prepare_agent_bundle(agent_path, Path(directory)))
            process = await asyncio.create_subprocess_exec(*command, cwd=PROJECT_ROOT,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
            except (TimeoutError, asyncio.CancelledError):
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.communicate(), timeout=5)
                    except TimeoutError:
                        process.kill()
                        await process.communicate()
                raise PlannerInvocationError("Omnigent Planner timed out or was cancelled.") from None
            finally:
                scrub_cached_credentials(Path(os.environ["OMNIGENT_DATA_DIR"]), os.environ.get("OPENAI_API_KEY", ""))
        if process.returncode:
            # Do not surface provider headers, key fragments, or full prompts.
            # Redact the configured key before exposing a compact error summary.
            detail = stderr.decode(errors="replace")
            key = os.environ.get("OPENAI_API_KEY", "")
            if key:
                detail = detail.replace(key, "[REDACTED]")
            detail = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", detail)
            # Transport errors are not decision errors; the orchestrator will
            # not use its repair budget to blindly retry an API/network failure.
            raise PlannerInvocationError(f"Omnigent CLI failed (exit {process.returncode}): {detail[-1500:]}")
        output = stdout.decode(errors="replace").strip()
        # The CLI may prepend its session URL. Only this documented transport
        # notice is removed; arbitrary prose still fails strict JSON parsing.
        output = "\n".join(line for line in output.splitlines()
                           if not line.startswith("Omnigent session: http")).strip()
        log.info("%s_OUTPUT_RECEIVED project=%s", role.upper(), project_id)
        return output
