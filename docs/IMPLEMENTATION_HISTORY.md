# AutoLab

AutoLab is an Omnigent-powered autonomous lab for computational AI research.

Current status: **Phase 13 complete — CLI Polish + Living Research Report.** Phases 1–12 remain verified. The CLI calls existing scientific services; status and deterministic Markdown reports read the same project-scoped ledger view. The saved empirical EXP_0001 remains unchanged and BLOCKED on missing resources and scientific settings. Phase 14 has not started.

## Quickstart

AutoLab moves from a research charter through evidence, competing hypotheses,
reviewed experiments, explicit human approval, preparation/readiness, audited
implementation, deterministic measurements and reviewed interpretation. The
Planner chooses the next action after new evidence. SQLite preserves scientific
versions, result provenance, approvals and decisions.

Use Python 3.12+ and the existing virtual environment, or install the package:

```sh
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[test]'
cp .env.example .env
```

Set `OPENAI_API_KEY` privately in `.env` before using reasoning agents. Status,
lifecycle controls, approval and report generation need no model/network calls.
`continue` can make paid calls through the existing Omnigent agents.

```sh
autolab start --db research_state/my-study.db \
  --question 'Does a constrained rule improve held-out prediction error?' \
  --objective 'Compare a preregistered intervention with its control' \
  --primary-outcome 'Held-out error' \
  --success-criterion 'Lower error within the explicitly defined test' \
  --budget-usd 10 --time-minutes 120 --max-rounds 2

# Use the PROJECT ID printed by start; every command scopes both ledger and project.
autolab status --db research_state/my-study.db --project PROJECT_0001
autolab continue --db research_state/my-study.db --project PROJECT_0001 --max-steps 4
autolab report --db research_state/my-study.db --project PROJECT_0001
```

`start --charter charter.json --db ...` accepts a canonical ResearchCharter.
Explicit intake requires the question, objective, primary outcome and success
criterion. Omitted budget defaults to **0 USD**, time to **unconfigured**, and
rounds to **1**. These defaults allocate no consequential spending. Supplied
charter files retain their own canonical fields; missing metadata is not inferred.

## CLI and human controls

`autolab ...`, `python -m autolab ...` and `python -m autolab.cli ...` expose the
same interface. Existing smoke modules and `autolab.approval` remain available.

| Command | Behavior |
| --- | --- |
| `start` | Persist an explicit charter; print its ID |
| `status [--json]` | Derived state, current science/results, next decision, human gates, blockers, known actual spend versus estimates, time and rounds |
| `continue [--max-steps 1..20]` | Existing bounded adaptive orchestration; halt at pause, STOP, approval, active execution or block |
| `approve --packet APKT_ID [--yes]` | Confirm the exact current packet; preparation scope by default |
| `reject --packet APKT_ID [--note ...]` | Persist exact scoped rejection |
| `modify --packet APKT_ID [--note ...]` | Request modification while preserving the scientific contract |
| `pause / resume [--note ...]` | Persist lifecycle controls without resetting science, rounds or allocation |
| `stop [--note ...]` | Terminal human STOP with actor/reason distinct from Planner STOP |
| `history` | Chronological scientific milestones |
| `report [--json] [--reports-dir PATH]` | Atomic Markdown report plus ledger fingerprint/generation receipt |

Each command requires `--db`; each existing-project command also requires
`--project`. No command discovers or merges saved smoke/validation ledgers.
Use `--help` for exact options. Exit codes are 0 for success (including a halted
continuation), 2 for invalid input/state, and 1 for internal failures.

When an experiment reaches human input, use the existing feasibility interface
to assess the exact selected spec and inspect its packet. Capability mappings,
resource access, estimates and caps must be explicit public planning declarations:

```sh
python -m autolab.approval --db research_state/my-study.db assess \
  --project PROJECT_0001 --experiment EXP_0001 --version 1 --config public-planning.json
python -m autolab.approval --db research_state/my-study.db show \
  --project PROJECT_0001 --experiment EXP_0001 --version 1
autolab approve --db research_state/my-study.db --project PROJECT_0001 --packet APKT_0001
autolab continue --db research_state/my-study.db --project PROJECT_0001 --max-steps 4
```

Approval requires typed `APPROVE APKT_ID` or an explicit human `--yes` command.
Unknown estimates require `--acknowledge-unknowns`, `--max-cost-usd` and
`--max-runtime-minutes`. `--include-implementation` explicitly adds implementation
eligibility. The Phase 7 service permits preparation/implementation scope only;
this CLI does not grant execution scope. Current readiness, independent code
audit, exact implementation execution authorization and operator-configured
framework/runtime adapters remain necessary. Unsupported science/capabilities
block. `continue` uses existing services and never guesses adapters or approves
work. A terminal STOP cannot be resumed; interrupted work requires explicit
operator reconciliation. Pause prevents new continuation and does not kill an
already running child process.

## Living research report

Reports are generated without an LLM from canonical project records:
charter, evidence/source citations, hypotheses, contracts, approvals, resources,
audits, run-scoped metrics, all analysis versions, adaptive decisions, lineage,
limitations and factual process telemetry. Numeric values and assessments retain
their IDs and scope. Negative/null outcomes, contradictions, blocked work and
UNKNOWN costs stay visible. No human comparison baseline or acceleration factor
is invented.

Default path: `reports/<project_id>/<ledger-path-digest>/research_report.md`.
The ledger digest keeps identical project IDs in different fixture databases
separate. Generation uses atomic replacement and records `REPORT_GENERATED`
with project, path, UTC timestamp, snapshot hash and report hash. Repeated
generation preserves content except its generation timestamp. Reports and smoke
artifacts are ignored by Git; no editor/browser opens automatically.

Offline integration checks:

```sh
python -m autolab.cli_integration_smoke
python -m autolab.cli_approval_integration_smoke
python -m autolab.report_integration_smoke
python -m pytest -q
```

The report smoke explicitly regenerates the existing offline two-round fixture
and reports its separate ledger. Its test-human approvals and synthetic results
are validation evidence. They grant no production authority or population claim.
See [Phase 13 validation notes](docs/PHASE13_VALIDATION.md).

Current runtime model policy: **`gpt-6.1-sol`** for all implemented agents. Planner, Hypothesis, Scientific Critic, Experiment Designer, Preparation, Readiness Auditor, Implementer, Code Auditor, and Analyst use **high** reasoning; Evidence uses **medium**. Future reasoning-heavy agents default to high. No silent model fallback is used.

Role settings remain in the agent YAML files, with offline regression tests against the actual Omnigent-loaded runtime bundles. Omnigent 0.16.0 drops reasoning effort in its standalone YAML adapter; AutoLab's existing transport submits the same names, prompts, and empty tool sets using the supported `config.yaml` bundle format so the server preserves the requested effort. The ad-hoc CLI model default is also pinned through `OMNIGENT_MODEL`; explicit user overrides remain explicit.

Phase 1 Omnigent/OpenAI connectivity remains verified; the existing launcher is unchanged.

Requirements: Python 3.12+, Git, and uv. The local environment uses Python 3.12.13 and Omnigent 0.16.0. Node.js 22+ and npm are required for coding harnesses; this Mac has Node 24.11.1 and npm 11.6.2. The selected pure Python `openai-agents` harness does not require tmux.

Omnigent was installed in `.venv` with `uv pip install "omnigent[agents-sdk]" python-dotenv pydantic`, using the [official Python package installation option](https://github.com/omnigent-ai/omnigent#quick-start). The existing install was reused; the current release was confirmed as 0.16.0. The AutoLab editable package is installed. No Databricks extra was added.

From the VS Code terminal:

```sh
cd autolab
source .venv/bin/activate
```

Keep your API key in `.env`. Omnigent's launcher loads it privately using python-dotenv, following [OpenAI's environment-based authentication guidance](https://developers.openai.com/api/reference/overview). To load it into zsh manually without printing it:

```sh
set -a
source .env
set +a
```

Start Omnigent with the OpenAI-backed model confirmed available to this API key:

```sh
python -m autolab.launch run --harness openai-agents --model gpt-6.1-sol --server local
```

The launcher wraps the official CLI, loads `.env`, and keeps Omnigent's own runtime state under ignored `.omnigent/`. Direct environment credentials are supported; no additional credential wizard was required.

Phase 1 originally verified connectivity with `gpt-5.4`. That historical test used:

```sh
python -m autolab.launch run --harness openai-agents --model gpt-5.4 --server local --no-log -p 'Reply with exactly: AUTOLAB_OMNIGENT_OK'
```

It returned exactly `AUTOLAB_OMNIGENT_OK` on October 3, 2026. The local server was stopped afterward. `.env`, `.venv/`, and runtime state are ignored by Git; `.env.example` is available for commit. No commits were made. Existing scaffold files from the earlier setup were preserved; this phase added no application behavior.


## Research Ledger

The SQLite source of truth defaults to `research_state/autolab.db`. Override it with `AUTOLAB_LEDGER_PATH` or `ResearchLedger(path)`. Generated databases and their journal files are ignored by Git.

Run the isolated ledger smoke test (temporary database, no LLM calls):

```sh
python -m autolab.ledger_smoke
```

Install test dependencies when setting up a new environment and run the tests:

```sh
uv pip install -e '.[test]'
python -m pytest -q
```

Canonical Pydantic records are in `src/autolab/schemas.py`. Use `ResearchLedger` from `autolab.ledger` with `initialize()`/`close()`, or as a context manager. `next_id("PROJECT")` and other supported prefixes reserve human-readable IDs atomically. Reserve IDs in the same ledger where records will be stored.

The ledger offers the named `add_*`, `get_*`, and `list_*` methods, plus `get(Model, id)` and `list_records(Model, project_id)` for every canonical model. Missing IDs return `None`. Hypotheses, experiment candidates, and experiment specs append consecutive versions under a stable ID; `get(..., version=1)` retrieves a specific version, an omitted version retrieves the latest, and lists include all versions. Relationships pin exact versions and enforce project boundaries. Reviews accept canonical class names or table names as `target_type`.

All scientific rows reject updates, deletes, replacements, and duplicate IDs. A charter remains immutable; runs, decisions, and events are append-only. Add audit entries explicitly with `add_event`; chronological reads use UTC timestamps and insertion order for ties. Domain fields and nested JSON survive reopening the database. The original smoke utility contracts live in `smoke_schemas.py` for compatibility, and are separate from canonical ledger records. No planner behavior or orchestration was added in this phase.

## Planner control plane

The Planner chooses one scientific action from bounded structured ledger context. Deterministic code checks prerequisites, roles, human approval, readiness, code review/tests, budget, runtime, and the immutable charter. Valid decisions and their audit events are saved atomically before returning a `RoutingDecision`. Evidence, hypothesis, experiment-design, and preparation/readiness routes connect to their Omnigent specialists; later roles remain conceptual.

Use `Orchestrator(ledger, OmnigentPlanner()).decide(project_id)` from an async caller. Context limits are configurable through `ContextBuilder(ContextLimits(...))`. The existing canonical `PlannerAction` and `NextDecision` are reused. The conceptual registry includes review roles and the deterministic `experiment_runner`; it creates no specialist implementations.

Run the offline suite with `python -m pytest -q`. Run the explicit live check separately:

```sh
python -m autolab.planner_integration_smoke
```

The live check requires `OPENAI_API_KEY` privately in `.env`, creates a temporary database, and invokes the existing Planner through Omnigent 0.16.0's local server and `openai-agents` harness with `gpt-6.1-sol` and high reasoning effort. Output must be strict JSON validated as canonical `NextDecision`. Malformed or illegal output permits one repair; transport failures propagate without retry. The Planner-only smoke executes no specialists, and normal pytest makes no API calls. Model, effort, harness, and Omnigent version from the actual invocation configuration are included in existing decision events, without new schemas or tables.

Verification: 179 offline tests passed; ledger smoke returned `AUTOLAB_LEDGER_OK`; live Planner smoke returned `AUTOLAB_PLANNER_OK` with `INITIALIZED → GATHER_EVIDENCE → evidence`, durable decision/event writes, and one model call. Exact token-cost accounting and specialist dispatch remain later-phase work; estimates are never treated as measured spend.

## Literature and evidence

The evidence role runs through the same Omnigent CLI/server transport with `gpt-6.1-sol` and medium reasoning effort. It makes three bounded reasoning calls: structured query generation, batch abstract screening, and batch extraction from Top-K papers. Default limits are three queries, at most 15 results per query/provider, 60 raw candidates, and Top 4 papers. `LiteratureLimits` configures smaller or larger bounds within the Phase 4 limits. Missing abstracts are excluded from extraction, and relevant contradictory/methodological papers receive selection priority.

Providers use official APIs: [OpenAlex works search](https://help.openalex.org/api/searching/) and the [arXiv Atom API](https://info.arxiv.org/help/api/user-manual.html). OpenAlex basic queries work without a key; optionally set `OPENALEX_API_KEY` privately in `.env` for a larger allowance and `AUTOLAB_CONTACT_EMAIL` for contact identification. Authentication uses a bearer header, never a stored URL. arXiv requests are serial, separated by at least three seconds, with repeated-query caching within the provider instance, following its [API terms](https://info.arxiv.org/help/api/tou.html). Calls have timeouts and response-size limits, with no automatic network retries. One provider failure yields warnings and can degrade to the other; all failures surface explicitly. Empty results produce a recorded insufficient-evidence outcome.

Deduplication uses normalized DOI, arXiv/provider identity, or cautious exact normalized title matching. Source identity comes exclusively from provider code. Canonical `SourceRecord.metadata` retains provider provenance and abstract hashes; the Evidence model can return only candidate IDs, claims, copied supporting text, confidence, roles, and tags. Each canonical `EvidenceRecord` must reference its source in the same project and match a contiguous whitespace-normalized abstract passage. Unsupported passages are rejected. Abstract-level provenance does not establish claim correctness or scientific validity; later Scientific Critic review remains necessary. Existing sources/evidence are reused, and source/evidence/completion writes are atomic.

After `route = await orchestrator.decide(project_id)`, dispatch an evidence route with `await orchestrator.execute_evidence(route)`. That returns a structured `EvidenceGatheringResult`. A subsequent explicit `await orchestrator.decide(project_id)` rebuilds context and lets the Planner choose any legal next action. Dispatch rechecks the persisted route, current gates, and completion history. No Phase 5+ specialist is executed.

Explicit live checks, excluded from normal pytest:

```sh
python -m autolab.evidence_retrieval_smoke
python -m autolab.evidence_integration_smoke
python -m autolab.evidence_integration_smoke --with-planner
# Equivalent full handoff command:
python -m autolab.evidence_loop_smoke
```

The retrieval smoke uses no model calls. The evidence smoke uses approximately three; `--with-planner` verifies evidence and both Planner cycles together with approximately five. Each uses an isolated temporary database. The full live handoff returned `AUTOLAB_EVIDENCE_OK` and `AUTOLAB_EVIDENCE_LOOP_OK`: 40 raw papers, 38 screened, 3 selected sources, 6 verified evidence records, and `GATHER_EVIDENCE → evidence → GENERATE_HYPOTHESES → hypothesis`. No hypothesis agent ran. Actual model costs remain unavailable and are never invented. Provider keys and resolved Omnigent credential caches are kept out of scientific records and Git; the transport redacts cached credentials after calls.

## Hypothesis generation and Scientific Critic

The Hypothesis Scientist proposes three competing, falsifiable candidates by default, using the charter, compact evidence, contradictory findings, and concise prior/rejected hypotheses. `HypothesisLimits(candidate_count=...)` supports 1–5 candidates. Canonical `Hypothesis.rationale` explicitly labels **AGENT-GENERATED HYPOTHESIS**, separates **SUPPORTED BY EVIDENCE** from **SCIENTIFIC INFERENCE / PROPOSED EXPLANATION**, and requires **LOW-CONFIDENCE** for uncited proposals. Scores are advisory; novelty refers to the retrieved evidence/current research state, never the global literature. No canonical schema or database table was added.

All directional and rationale evidence references must exist in the same project and supplied context. Exact normalized statement duplicates are rejected across the project history. All supplied contradictory evidence reaches both agents, or context construction fails visibly at the configured bound. Abstracts, raw provider responses, hidden reasoning, and unrelated events are excluded. Isolated no-evidence proposals can be tentative or return insufficient basis; the existing Planner routing prerequisite still requires evidence before `GENERATE_HYPOTHESES`.

One Omnigent Scientific Critic reviews the batch independently as canonical `ReviewRecord`s with PASS, REVISE, REJECT, or BLOCK. At most one batched revision/rebuttal and one final Critic check run, for 2–4 specialist model calls total. Each issue receives ACCEPT, REBUT, or CLARIFY with reasons, persisted in revision events. Invalid output fails without automatic model repair. PASS means suitable to investigate, not scientifically proven. Unresolved final verdicts return to the Planner.

Initial proposals persist before review. Scientific revisions append a consecutive version under the same ID; reviews pin the exact evaluated version. Rejection adds a status-only version and preserves the original review's target version. `ledger.get(Hypothesis, id, version=1)` reconstructs the original. Completed records survive later failures and reopening; scientific batches and their events are atomic.

After a validated hypothesis route, call `await orchestrator.execute_hypotheses(route)` and then `await orchestrator.decide(project_id)`. The rebuilt Planner context includes predictions, scores, evidence IDs, exact Critic verdicts/concerns, and rejected history. The Planner chooses any legal next action. If it chooses `DESIGN_EXPERIMENT → experiment_designer`, exactly one PASS-reviewed candidate ID in `required_context_ids` records the existing `HYPOTHESIS_SELECTED` event atomically with the decision. Selection pins that version without declaring it true. Phase 5 stopped at this handoff; Phase 6 connects it below.

Explicit paid checks, excluded from normal pytest:

```sh
python -m autolab.hypothesis_integration_smoke
python -m autolab.hypothesis_loop_smoke
```

Both use isolated temporary databases and real public scholarly evidence. The first uses approximately 2–4 model calls; the adaptive loop uses approximately 8–10 including Evidence and Planner. Structured scientific output is saved under ignored `results/phase5-hypothesis-*.json` for inspection. Actual model costs remain unavailable and are never invented. Secrets, credential caches, and databases remain ignored; cached credentials are scrubbed by the existing transport.

Phase 5 verification: **307 offline tests passed / 0 failed**. Both live smokes passed. The adaptive run persisted 6 verified EvidenceRecords, 3 distinct hypotheses, and 4 reviews with one revision round; the Planner selected `HYP_0001` version 1 and chose `DESIGN_EXPERIMENT → experiment_designer`. The role was not executed. The successful hypothesis smoke used 4 model calls and the adaptive smoke used 10; one earlier generation call stopped at an overly restrictive background-citation check, which was corrected and regression-tested. All generated hypotheses/reviews were inspected for grounding, distinct predictions, uncertainty, and scientific concerns. Database reopening and credential/ignore checks passed. The Phase 6 continuation is documented below.

## Experiment design and preregistration

The Experimental Scientist runs through Omnigent with OpenAI `gpt-6.1-sol` and high reasoning effort. It receives one canonically selected, exact-version PASS-reviewed hypothesis, compact supporting/contradictory evidence, the hypothesis critique, relevant experiment history, and broad constraints. `DesignLimits` defaults to two candidate experiments and allows three. Candidates should distinguish scientific uncertainties through different interventions, controls, data, measurements, or scope; changing only sample size is insufficient.

Each canonical `ExperimentCandidate.design` proposes variables, conditions, controls, dataset/resource/capability requirements, sampling, one primary metric with rationale, success/falsification/inconclusive criteria, assumptions, confounders, robustness checks and expected result patterns. No results or implementation fields are accepted. Sample adequacy may remain explicitly unresolved; power calculations and precise prices are never invented. Costs/runtime may be `null` for unknown, and non-null estimates remain rough planning assumptions for Phase 7.

The existing Scientific Critic reviews the whole batch in experiment-design mode. One revision/rebuttal round supports ACCEPT, REBUT and CLARIFY, followed by one final Critic assessment. Original/revised candidate versions, exact-version reviews and response events persist. REJECT creates a status-only CANCELLED version while preserving the evaluated review version; final REVISE/BLOCK returns unresolved designs to PI. No model output is silently repaired, and exact normalized objective/approach duplicates are rejected against history.

After `await orchestrator.execute_experiment_design(route)`, call `await orchestrator.decide(project_id)`. PI compares concise designs and critiques and may select one using `SELECT_EXPERIMENT → planner`, identifying exactly one candidate ID in `required_context_ids`. Scores are advisory. Only an exact-version PASS candidate for the selected hypothesis can become a canonical preregistered `ExperimentSpec`. Decision, spec and selection/provenance events persist atomically, including the reason and non-selected IDs. Other candidates remain proposals. An active contract prevents another simultaneous selection.

Compatible schema additions are limited to candidate `design` and `version`, nullable planning cost/runtime on candidates/specs, and the missing `SELECT_EXPERIMENT` action. SQLite schema version 2 automatically migrates the existing candidate table, preserving every prior JSON document, ID and review; no new tables or dependencies are added. Legacy records retain their defaults. Candidates and specs reject silent overwrites. A selected spec reuses its candidate's actual review only when every scientific field matches the deterministic conversion; amendments require a new review. The natural Phase 6 boundary is `AWAITING_HUMAN_APPROVAL`; Phase 7's assessment and explicit approval gate are documented below.

Explicit paid checks, excluded from normal pytest:

```sh
# Prerequisite: real Phase 5 adaptive checkpoint, if not already present.
python -m autolab.hypothesis_loop_smoke
python -m autolab.experiment_design_integration_smoke
# Inspect ignored results/phase6-experiment-design-smoke.json before selection.
# Adaptive check on the original project: any validated scientific action passes.
python -m autolab.experiment_selection_smoke
# Separate empirical-project fixture: reports PASS or LEGAL_DIVERGENCE.
python -m autolab.experiment_selection_smoke --selection-ready
# Offline selection execution, with only the Planner decision mocked:
python -m pytest -q tests/test_phase6_planner_smokes.py -k deterministic_selection_path
```

The design smoke continues the actual Phase 5 PI-selected hypothesis/evidence handoff in a fresh temporary ledger, requiring 2–4 specialist calls. The default Planner smoke resumes those actual generated candidates and the original literature-assessment charter. Any normally validated action passes the adaptive check: decision and event must persist, and an evidence request must not fabricate a selection or ExperimentSpec. Illegal actions and malformed output retain the existing bounded repair/error behavior. Its artifact is `results/phase6-adaptive-planner-smoke.json`.

The separate `--selection-ready` check loads `tests/fixtures/phase6_selection_ready.json` into a new isolated empirical-project ledger. It preserves the real retrieved abstract evidence, selected hypothesis, candidate scientific details and exact-version PASS Critic reviews. The newly authored charter concerns a local empirical investigation rather than retrospective evidence assessment. Abstract-only support remains explicitly limited to motivating competing mechanisms; no paper's budget matching, effect size, adequate sample, prepared resource or experiment result is fabricated. The illustrative planning envelope is not spending approval. Cost, sample adequacy, resources, readiness and approval remain pre-execution gates. The original charter/checkpoint is never amended.

Each Planner check asks the unchanged normal Planner for its next justified action. Selection verifies exact candidate/hypothesis/review provenance, deterministic candidate-to-spec equality, one preregistered contract, preserved alternatives/reviews and the Phase 7 boundary. A different legal action is reported as `LEGAL_DIVERGENCE` by the selection-ready smoke, rather than as model or system failure. Its artifact is `results/phase6-selection-ready-smoke.json`; neither check forces selection, dispatches a specialist, or prepares resources, generates experiment code or executes experiments. Both verify persistence by reopening their temporary databases. The independent offline regression mocks only the Planner decision and exercises selection of **both** candidates through the real validator, ledger and orchestrator, regardless of live LLM choice.

Original Phase 6 verification with `gpt-5.4`: **404 offline tests passed / 0 failed** (307 existing and 97 Phase 6 tests). Both live smokes passed using the real Phase 5 `HYP_0001` version 1 handoff. Two distinct candidates and four experiment reviews persisted through one revision round: `CAND_0001` version 2 received PASS, while the broader `CAND_0002` version 2 remained REVISE. PI selected the smaller valid design and preregistered exactly one `EXP_0001` version 1, preserving the alternative and selection reason. The successful flow used five model calls (Designer 2, Critic 2, Planner 1); one earlier Designer call was rejected for missing sampling details before the prompt schema was tightened. Both candidate designs, critiques, revisions and the selected contract were manually inspected. The smokes continued saved actual scientific checkpoints instead of repeating the full paid evidence/hypothesis loop. Reopening, credential and ignore checks passed; the local Omnigent server was stopped. No Phase 7 component executed.

Phase 6 model-policy follow-up with `gpt-6.1-sol`: **419 offline tests passed / 0 failed**. The policy regression includes all five agents and loads the same supported Omnigent 0.16.0 bundle used by production, preserving each reasoning effort. The Designer's generated output schema now requires the numeric advisory scores and nonempty risks already required by its existing validation gate; canonical historical records and prompts are unchanged. The targeted design smoke passed with two distinct v1 proposals, both PASS-reviewed: an end-to-end matched policy comparison with a clean-retry control, and a conditional checkpoint diagnostic-information ablation. Both were manually inspected; the live batch required no revision, while offline tests verify the single-round revision bound. The targeted selection smoke **failed its selection requirement**: the real high-reasoning Planner legally chose `GATHER_EVIDENCE` because the charter asks to assess prior evidence and the sources are abstract-only. No new ExperimentSpec was created. The historical selection checkpoint remains historical; `results/phase6-model-policy-followup.json` records this follow-up's outcome. No resources, experiment code, or runs were created, and no Phase 7 functionality was implemented.

Testing-contract correction: that earlier outcome is **scientific decision divergence**, not a model, structured-output, orchestration or validation failure. **429 automated tests passed / 0 failed**, including deterministic selection of either candidate with only the Planner decision mocked, persisted legal evidence gathering, illegal-role/unknown-candidate/malformed-output rejection, and detection of fabricated selection. The targeted deterministic regression also passed both cases. The new real adaptive smoke passed; this fresh call selected `CAND_0001` v1. Replaying the previously recorded real `GATHER_EVIDENCE` response separately confirmed valid decision/event persistence, zero ExperimentSpecs, and reopening; that replay was not a new model call. The real selection-ready smoke also passed, selecting `CAND_0001` v1 for its direct end-to-end estimand and retaining `CAND_0002` v1. Each actual selection created exactly one `EXP_0001` v1 in its own temporary ledger and stopped at `AWAITING_HUMAN_APPROVAL`. Both new live calls used the unchanged `gpt-6.1-sol` / high Planner through Omnigent 0.16.0; no fixture correction/retry was needed after a live decision. The model policy, scientific prompts, production control plane and architecture remain unchanged. No Phase 7 code or experiment execution was introduced.

## Cost, feasibility and human approval

Phase 7 assesses the selected, exact-version PASS-reviewed `ExperimentSpec` without redesigning science or acquiring resources. The deterministic capability registry accepts extensible identifiers, dependency lists and AVAILABLE / UNAVAILABLE / REQUIRES_CREDENTIAL / UNKNOWN findings. Local checks inspect configuration only: a credential's presence does not prove network access, model entitlement or independent readiness. Natural-language requirements need explicit capability mappings and resource-access declarations; unknown requirements remain visible.

Costs use only explicitly configured prices and quantity ranges. Missing prices, quantities or total pursuit durations remain UNKNOWN with assumptions and cost drivers, rather than fabricated precision. Estimate-only `CostRecord` entries are never treated as measured spend. Remaining budget subtracts known actual costs; remaining time follows the existing charter clock. Unknown estimates can be approved only with explicit acknowledgement and cost/time caps, after required inputs and blockers are resolved.

The approval packet shows science, selection reason, requirements, feasibility, estimated ranges, current budget/time and risks. Inherited scientific planning notes retain their historical constraints; the current charter limits are displayed separately. `ApprovalService.request_approval(...)` persists the packet; `record_human_decision(project_id, experiment_id, experiment_version, decision, packet_id=..., note=...)` records only an explicit human APPROVE, REJECT or MODIFY. Existing scoped `HUMAN_*` events bind approval to the exact spec fingerprint, version and assessment. A new spec version or completed assessment requires a new approval. REJECT and MODIFY preserve scientific history and return control to the adaptive Planner.

Minimal interaction, using IDs from your existing ledger:

```sh
python -m autolab.approval --db research_state/autolab.db assess --project PROJECT_0001 --experiment EXP_0001 --version 1
python -m autolab.approval --db research_state/autolab.db show --project PROJECT_0001 --experiment EXP_0001 --version 1
python -m autolab.approval --db research_state/autolab.db decide --project PROJECT_0001 --experiment EXP_0001 --version 1 --packet APKT_0001 --decision MODIFY --note 'Resolve missing requirements first'
```

`assess --config public-planning.json` accepts `capabilities` and typed `inputs` (capability mappings, resource access, cost quantities/prices, runtime assumptions and risks); keep credentials out of it. `decide` accepts APPROVE / MODIFY / REJECT; omitting `--decision` requires typed human input, with no default approval. Unknown estimates require `--acknowledge-unknowns`, `--max-cost-usd` and `--max-runtime-minutes`. Production rejects test-human actors; isolated tests opt in explicitly.

Offline smoke commands:

```sh
python -m autolab.feasibility_integration_smoke
python -m autolab.approval_integration_smoke
python -m pytest -q tests/test_feasibility.py
```

The first smoke uses actual local configuration and preserves unknowns. The approval smoke uses **explicit simulated planning declarations and illustrative prices**, plus `test-human` in a temporary DB. Both reuse the saved Phase 6 scientific contract, with a controlled committed-fixture fallback for clean checkouts, and verify reopening. Ignored `results/phase7-*-smoke.json` artifacts preserve the packet and audit state. Optional `python -m autolab.approval_integration_smoke --with-planner` permits one real `gpt-6.1-sol` / high Planner call; any legal decision passes and only a routing boundary is returned.

Verification: **502 automated tests passed / 0 failed** (429 previous and 73 Phase 7), including exact-version/assessment binding, stale approval, explicit rejection/modification, unknown estimates, malformed decisions, restart and failure atomicity. The feasibility smoke reported NEEDS_USER_INPUT honestly; the explicit test-human approval smoke passed and the optional live Planner returned PREPARE_RESOURCES. That actual one-call result is preserved in `results/phase7-post-approval-planner-smoke.json`. Approval grants preparation eligibility only. No Preparation Agent, resources, experiment code or experiments execute in Phase 7; Phase 8 remains unimplemented.

## Project Documentation

- [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) — complete AutoLab product/research plan
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — technical architecture and design rules

Read both before implementation. Their phase table is the requested new planning baseline; it notes the existing Phase 2 work recorded above, which must be preserved and reconciled.


## Phase 8: Experiment Preparation + Readiness Auditor

Preparation creates resources; independent Readiness audits them. Both agents use Omnigent 0.16.0 with `gpt-6.1-sol` / high. `PreparationService` requires the existing exact-spec feasibility/human gate, records a structured acceptance contract before creation, and delegates to constrained local, synthetic JSON/text, download or transform handlers. No arbitrary shell, package installation, remote dataset code, scripts or experiment execution is allowed. Existing input paths require an operator catalog; optional small HTTPS data downloads require an exact operator URL allowlist and pinned SHA-256.

ResourceRecords preserve provenance, generation specification/parameters, seed scope, source/license metadata where available and dependency/parent IDs. Generated files use immutable resource IDs; existing data is imported once into a shared content-addressed cache. Repairs append new canonical resource IDs with logical identity, version and prior-resource links. Versioned manifests live in experiment directories and event payloads, without new tables or duplicate scientific models. The canonical ReadinessReport gains only optional metadata for exact pins and audit findings.

Deterministic validators check integrity, schemas, counts, duplicates, condition coverage, split overlap, direct target shortcuts and provenance; a small registry accepts additional resource/binding validators. The independent Auditor receives bounded stratified samples, suspicious cases, summaries, acceptance criteria and deterministic evidence. Technical correctness cannot override scientific or quality failures. PASS requires all four gates; REPAIR returns specific issues with ACCEPT / REBUT / CLARIFY responses and at most two repair attempts; BLOCK returns control to Planner. Repairs change only accepted issues and preserve acceptance criteria. Changed cost/risk requires refreshed feasibility and explicit human reapproval. Changed artifacts, manifest, resource versions, spec, or a failed subsequent audit invalidate old readiness.

Use `Orchestrator.execute_preparation(route, service, auditor)` to execute a persisted legal PREPARE_RESOURCES route, audit and return control. A current PASS makes implementation eligible only when the human scope explicitly includes IMPLEMENT_EXPERIMENT. Existing preparation-only approval stays preparation-only; no run scope is granted and no Phase 9 role dispatches. The API's optional `approved_actions` is an explicit human choice, not an automatic scope expansion. There is no new full CLI.

Explicit live smokes (paid reasoning calls; isolated databases/artifacts under ignored `results/`):

```sh
python -m autolab.preparation_integration_smoke
python -m autolab.readiness_integration_smoke --with-planner
```

The first command preserves the actual selected empirical spec and demonstrates its honest BLOCK: its existing-data restriction, absent concrete catalog and unresolved B/adequacy/precision settings cannot be fixed by silently generating toy data. A separate, explicitly preregistered protocol fixture exercises preparation and PASS. `--protocol-only` or `--actual-spec-only` limits the first command. Test-human approvals/reapprovals exist only in these isolated fixture databases; they grant no production approval. The protocol fixture has 12 fictional lookup tasks (4 development / 8 held-out), 12 hidden references, 96 matched conditions with real seed-42 shuffling and a frozen configuration. It proves resource mechanics, not policy efficacy, power or population validity. A shuffled data seed does not make LLM proposal generation reproducible.

Verified: **600 offline tests passed / 0 failed** (502 prior tests, 96 Phase 8 tests and two additional model-policy cases). Preparation produced four resources with complete hashes/provenance. The real independent readiness call returned PASS across all four gates, with **52 deterministic checks**, zero repairs and bounded semantic coverage. One real post-readiness Planner call legally chose `PREPARE_RESOURCES → readiness` for additional semantic coverage; only its routing boundary was returned. No implementation, scientific run, metrics or analysis was created. The actual saved EXP_0001 has zero prepared resources and remains BLOCKED. Model billing and unexposed licenses remain explicitly unknown.

## Phase 9: Experiment Implementation + Independent Code Audit

The Implementer plans before generating code through Omnigent `openai-agents`
with `gpt-6.1-sol` / high. The exact approved scientific contract, current
manifest and independent readiness PASS are mandatory. Requirement-to-code
mapping, explicit metric functions, reproducibility, resource hashes and
generated toy tests are recorded in the ImplementationPlan. A constrained
writer preserves immutable implementation revisions inside experiment folders.

Static safety/interface checks precede offline toy tests. Independent framework
metric/invariant adapters are required in addition to generated tests. A
separate Omnigent Code Auditor (`gpt-6.1-sol` / high) assesses scientific
fidelity and returns PASS, REVISE, REJECT or BLOCK. Implementer issue responses
can ACCEPT, REJECT with evidence or request clarification. Review allows at
most two revisions. Code review is pinned to exact source and dependency
hashes; changed code/resources/spec/readiness invalidate eligibility. An auditor
PASS cannot override deterministic failures. The Planner receives compact
status and regains control after audit.

```sh
python -m autolab.implementation_integration_smoke
python -m autolab.code_audit_integration_smoke --planner
python -m autolab.implementation_integration_smoke --verify-existing
python -m pytest -q tests/test_implementation.py tests/test_model_policy.py
```

Smokes use a separate approved/readiness-passed four-row scalar prediction
fixture and ignored databases/artifacts; the saved real EXP_0001 remains
BLOCKED. Neither command invokes a scientific experiment, creates scientific
metrics or dispatches Phase 10. The optional Planner call returns any legal
routing boundary. Dependencies are allowlisted; nothing is automatically
installed. The test worker uses sanitized secrets-free environment, timeouts,
bounded output and a restricted offline Python profile. This is not an OS
sandbox: Seatbelt launch is unavailable in this managed session. Codex is
installed/authenticated but its native editing isolation was not compatible
here, so the supported existing Omnigent/OpenAI coding path is used.
See [Phase 9 validation notes](docs/PHASE9_VALIDATION.md) for exact boundaries.

Verified: **704 offline tests passed / 0 failed**. Live Omnigent generation and
independent audit produced a hash-pinned PASS after two code revisions and
append-only revalidation of corrected static-check false positives. The final
source passed **17 framework checks and 11 generated tests**. Exactly one
post-audit Planner call legally chose `STOP`; future run eligibility was
validated before that call, without dispatch. No scientific runs, metrics or
analysis were created.

## Phase 10: Deterministic Experiment Runtime + Metrics

`ExperimentRuntime` uses the approved scientific contract, current resource
bytes and exact audited source. It invokes no AutoLab LLM. Each execution gets
a unique immutable run identity, recorded seed/configuration and bounded,
sanitized offline process. Raw observations and preregistered Python-computed
metrics are persisted with SHA-256 provenance. A trusted adapter independently
checks coverage, denominators and metric recomputation; unsupported protocols
block rather than guessing. Failed, timed-out or cancelled runs preserve
available evidence without final metrics. Unknown actual cost stays null.

```sh
python -m autolab.experiment_runtime_integration_smoke
python -m autolab.experiment_runtime_integration_smoke --planner
python -m pytest -q tests/test_runtime.py
python -m pytest -q
```

Verified: **755 offline tests passed / 0 failed** (704 prior tests and 51 Phase 10
tests). The linked EXP_PHASE10 fixture retained Phase 9's scientific rules and
received a fresh independent code audit after two bounded provenance-import
corrections. RUN_0001 and RUN_0002 each produced eight observations, identical
scientific outputs and condition MAE values: baseline **0.175**, clipped
**0.075**, with four samples per condition. Independent raw recomputation and
artifact hashes matched. One post-run Planner call legally chose `STOP`.
Analysis was eligible before STOP, but no Phase 11 role executed and no
scientific conclusion was produced. The real EXP_0001 remains blocked.

The test worker is a restricted Python profile, not an OS sandbox. Live smoke
preparation uses an independent Omnigent audit; runtime and metric computation
are fully offline and model-free. See [Phase 10 validation notes](docs/PHASE10_VALIDATION.md)
for boundaries, failure handling and result-integrity gates.


## Phase 11: Scientific Analysis + Post-Result Critique

Deterministic `ResultSummary` checks completed-run/raw/metric integrity and
calculates descriptive comparisons before interpretation. The Omnigent Analyst
uses exact preregistered criteria and traceable evidence; the existing Scientific
Critic independently challenges claims, direction, confounds and scope. Both
use `gpt-6.1-sol` / high. Existing assessments are `SUPPORTED`,
`PARTIALLY_SUPPORTED`, `NOT_SUPPORTED` and `INCONCLUSIVE`; null results are
valid science. No statistics, quantitative confidence or new metrics are invented.

One optional revision records `ACCEPT`, `REBUT` or `CLARIFY` responses and
preserves both canonical versions and exact reviews. Stale/raw-tampered evidence
invalidates analysis and downstream result-based decision eligibility. The
workflow returns Planner control without executing the next scientific action.

```sh
python -m autolab.analysis_integration_smoke
python -m autolab.result_critique_integration_smoke --planner
python -m pytest -q tests/test_analysis.py
python -m pytest -q
```

The smoke uses the legitimate completed Phase 10 runs in a separate pre-STOP
checkpoint branch with an explicit linked analysis charter. It preserves exact
scientific records/artifact pins and leaves the terminal parent and real blocked
project untouched. Inspect the analysis-only artifact before critique.

Verified: **846 offline tests passed / 0 failed**. Live `ANALYSIS_0001` v1 received
`REVISE`; one revision produced v2, independently reviewed `PASS`. Baseline MAE
was 0.175 versus clipped 0.075, with four observations per condition. The final
`SUPPORTED` assessment applies only to this fixed synthetic fixture. One
post-review Planner call legally chose `STOP`; no Phase 12 action was dispatched.
See [Phase 11 validation notes](docs/PHASE11_VALIDATION.md) for evidence, scope,
limitations, migration and failure handling.


## Phase 12: Adaptive Next-Round Scientific Loop

Reviewed results return to Planner for one result-sensitive NextDecision. Existing
Evidence, Hypothesis and Experiment Designer agents handle the selected work.
Follow-ups preserve parent spec/run/analysis/decision lineage, avoid duplicate
protocols unless justified as replication, and require fresh exact-version human
approval. Existing preparation/readiness/implementation/audit/runtime/analysis
services are reused. Event-backed rounds, known aggregate spend, time and step
limits bound autonomy; human approval and pause/STOP halt continuation. Research
history retains favorable, negative, null, contradictory and rejected branches.
STOP is a valid scientific outcome.

```sh
python -m autolab.adaptive_decision_integration_smoke
python -m autolab.adaptive_followup_integration_smoke
python -m autolab.adaptive_loop_integration_smoke
python -m autolab.adaptive_loop_integration_smoke --offline
python -m pytest -q tests/test_adaptive.py
```

Verified: **910 offline tests passed / 0 failed**, including 64 Phase 12 cases.
Live integration legally chose GATHER_EVIDENCE, inspected the existing original
four-pair artifacts through the reused Evidence pipeline, then chose STOP after
coverage and boundary-crossing uncertainty was resolved. No live follow-up was
forced. The offline full path completed a separately approved in-range follow-up
with no measured condition difference and retained both reviewed results. All
smokes use isolated ledgers; real EXP_0001 remains BLOCKED. See
[Phase 12 validation notes](docs/PHASE12_VALIDATION.md) for exact evidence, bounds,
recovery, approval and scope limitations.
