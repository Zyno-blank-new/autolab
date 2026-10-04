# Phase 9 implementation boundary

Phase 9 translates an exact approved ExperimentSpec into code and independently
audits it. It does not execute `Experiment.run()`, create ExperimentRun or
MetricRecord observations, perform analysis, or dispatch a Phase 10 route.

## Harness decision

The installed Omnigent distribution is pinned to 0.16.0. Its official
[agent specification](https://github.com/omnigent-ai/omnigent/blob/main/docs/AGENT_YAML_SPEC.md)
supports both `codex` and `openai-agents`. Local inspection covered
`inner/codex_harness.py`, `inner/codex_executor.py`,
`inner/openai_agents_sdk_executor.py` and the existing AutoLab bundle adapter.
Codex CLI 0.159.2 is present and authenticated through ChatGPT. Omnigent's Codex
wrapper defaults to `caller_process` with sandbox `none`; its source maps this
to `danger-full-access`. A native coding workspace therefore requires explicit
OS isolation rather than assuming an isolated default.

The current managed shell rejected a harmless Seatbelt launch with
`sandbox_apply: Operation not permitted`. AutoLab consequently uses the
already-supported Omnigent `openai-agents` / Responses coding path with
`gpt-6.1-sol` and high reasoning. Two structured invocations separate planning
from generation. The agent has no filesystem, shell or network tools; a
deterministic writer admits only the validated flat source names inside a
fresh experiment-specific implementation directory. The independently invoked
Code Auditor uses the same model/effort through a separate Omnigent agent.
No direct external coding-agent or OpenAI API call bypasses Omnigent.

## Stable interfaces and focused context

`implementation.contract.BaseExperiment` adds interface declarations alongside
the preserved Phase 1 `tools/experiment_runner.py` utility. Implementations
provide `setup(context)`, `run(context)` and `collect_results(context)`.
`ExperimentRawOutput` and `RawObservation` define generic structured raw
observations for a future runner. No scientific runtime is introduced here.

The Implementer gets the exact spec/version, concise selected hypothesis,
current manifest and resource paths/hashes, readiness PASS, bounded resource
schema summaries, coding/interface conventions, allowed dependencies and
execution constraints. The Planner gets compact implementation/review/test
status; it never receives complete generated source. The Code Auditor gets
complete bounded relevant files and deterministic findings, without private
Implementer reasoning.

## Test isolation and limits

Generated code is admitted through a conservative AST profile before loading.
Only small Python files and a short standard-library allowlist are supported.
Shell, arbitrary imports, networking, direct filesystem access, credential
paths, reflection, dynamic code execution, unresolved critical placeholders,
silent production exception swallowing and obvious literal result returns
are rejected. Unsupported requirements block/escalate; nothing is installed.

The worker starts with Python `-I -S`, an explicit non-secret environment,
experiment-specific working directory, a wall-clock timeout, CPU/file-size
limits and bounded pipe capture. macOS's automatic non-secret CoreFoundation
environment flag is removed. Only curated module proxies and restricted
builtins are exposed. An audit hook additionally denies filesystem, socket,
subprocess and other system operations. Smoke setup receives toy in-memory
data, never actual resource paths. The worker never invokes `run()`.

This is defense in depth for the admitted restricted Python profile, **not an
OS sandbox or a guarantee for arbitrary malicious Python**. Native Seatbelt
was unavailable inside this session. Broader dependencies, direct I/O,
networking and general Python constructs require a separately reviewed future
execution scope. Real scientific network access belongs to Phase 10.

Independent, framework-owned TestContracts are operator-configured and pinned
to the spec. Missing metric/invariant adapters block before any model call.
The included adapter belongs only to the isolated scalar prediction fixture;
it is not hard-coded into production prompts or orchestration. It tests the
identity baseline, clipping, one-call budget, missing/duplicate inputs,
denominator edge cases and hand-computable plus varied toy MAE values.

## Immutable provenance and gates

The canonical ImplementationRecord and ReviewRecord gain optional metadata;
there are no duplicate schemas or new ledger tables. A plan is recorded before
generation. Every immutable revision retains source, plan, tests, hashes and
its predecessor. Source hashes include the complete file set and generated
tests. Reviews pin exact code, spec, manifest/resources, readiness, plan and
framework-test-contract and current check-report hashes. Trusted deterministic test and approval events
are also required. A bare legacy APPROVED string or unpinned PASS cannot grant
execution eligibility.

ImplementationRecord stays append-only with AUDIT_PENDING registration status;
effective READY is derived from independent PASS plus trusted successful
checks/approval events. ACCEPT, REJECT and NEEDS_CLARIFICATION responses are
auditable; the independent auditor can accept or maintain rebuttals. At most
two revisions occur. Block/reject/exhaustion returns control to the Planner.
Changes to code, file set, plan, checks, spec, resources or readiness invalidate
execution eligibility, as does a later failed independent audit.

Fresh validation is append-only: it creates a separate report and trusted
IMPLEMENTATION_TESTED event, leaving the initial checks and implementation
record intact. A changed check receipt requires a matching independent review
and approval; a failed retest immediately revokes readiness. Identical passing
receipts preserve existing pins. The Code Auditor cannot edit checker results.

## Explicit smokes

```sh
python -m autolab.implementation_integration_smoke
python -m autolab.code_audit_integration_smoke --planner
python -m autolab.implementation_integration_smoke --verify-existing
python -m autolab.code_audit_integration_smoke --revalidate --planner
python -m pytest -q
```

Live smokes make paid model calls through Omnigent and write ignored artifacts
under `results/phase9-artifacts/<unique-id>/`. The separate approved/readiness
fixture concerns identity versus clipping of four frozen scalar AI predictions.
It is an implementation mechanics check with no claim of effect, power or
generalization. The source is inspected before certification. Code audit may
legitimately revise or block; PASS is never forced. The optional Planner call
accepts any legal action and returns only its route.

Future RUN_EXPERIMENT eligibility is demonstrated with an explicit isolated
test-human scope pinned to the exact implementation. The production approval
interface is not expanded to authorize runs. The saved real EXP_0001 is read
only and must remain BLOCKED with zero implementations, runs and metrics.
Normal pytest makes no model or network calls.

## Verified isolated run

The live implementation history retains IMPL_0001, IMPL_0004 (revision 1) and
IMPL_0005 (revision 2), plus plan-only failed/clarification attempts. Independent
reviews retained REVISE and BLOCK rather than overriding failed checks.
Source inspection identified narrow checker false positives involving exact
manifest provenance, permitted exception initialization and visible failed
aggregates. Regression-tested checker corrections and fresh offline validation
enabled HREV_0005 to independently PASS unchanged IMPL_0005; no third code
revision occurred.

The final source hash is
`f080b1ddf8950030e4eab5e7911910913858ec043911eb076f177d711ea8f4fb`.
It passes 17 framework checks (setup plus 16 metric/invariant probes) and 11
generated tests. The entire offline suite passes 704 tests. One post-audit
Planner call legally chose STOP, completing the fixture charter. Future run
eligibility was asserted before STOP with exact isolated test-human scope;
the completed state does not dispatch a run. The real saved EXP_0001 remained
unchanged, with zero implementations, runs and metrics. No scientific outputs
were produced by Phase 9.
