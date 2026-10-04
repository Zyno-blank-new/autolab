# Phase 13: CLI polish and living research report

The baseline passed **910 tests / 0 failed** before implementation. Final
verification passed **1,002 tests / 0 failed**, including **92 Phase 13 cases**.
The separate targeted CLI/report/model-policy run passed **112 tests**. Normal
pytest and all Phase 13 integration smokes make no paid model/network calls.

## Interface and scope

The installed `autolab` entry point, `python -m autolab` and
`python -m autolab.cli` use the same argparse interface. Existing launcher,
approval and smoke modules are preserved. No dependency, scientific agent,
database table or canonical scientific schema was introduced.

Every command requires an explicit `--db`; existing-project commands also
require `--project`. A missing ledger path fails without creating an empty
database. Status/report query the selected project through `load_snapshot`;
there is no filesystem discovery of scientific fixtures or historical smoke
results. An explicitly validated linked charter remains visible through the
existing Phase 12 authorization representation.

Start validates the canonical ResearchCharter and existing round limits.
Structured JSON is accepted directly. Explicit intake requires question,
objective, primary outcome and success criterion. Documented defaults are
zero consequential spending allocation, unconfigured elapsed time limit and
one bounded round. Supplied charter files retain their canonical fields.

Human and JSON status share `reporting.view`. They derive control state using
the existing state machine and expose current science, result metrics, analysis
freshness, latest decision, human gates, capabilities/readiness/scientific
blockers, known actual spend, estimates, unknown actual costs, time and rounds.
Human output is concise; JSON contains the same structured scientific view.
History exposes scientific milestones and excludes arbitrary agent/debug
payloads, prompts, private reasoning and generated code.

Continue calls `Orchestrator.continue_research` with the existing 1–20 step
bound. DecisionValidator and existing specialist services still own all gates
and dispatch. Output identifies previous/resulting state, actual completed
actions, decisions and human boundaries. Tests use injected offline Planner
and services. Paused, terminal and pending-approval projects make zero Planner
calls. Active or interrupted work retains the existing reconciliation boundary.

## Explicit human decisions

Approve/reject/modify call the Phase 7 ApprovalService with the exact current
packet/spec/assessment. The required packet ID prevents ambiguous approval.
Approve displays the existing packet and requires typed `APPROVE APKT_ID`,
or the explicit non-interactive human `--yes` command. Unknown estimates
retain the existing acknowledgement and spending/runtime-cap requirements.
Modification records a request; it never edits the scientific contract.

The production actor is `human`. There is no CLI actor override or LLM approval
tool. The isolated approval smoke explicitly injects `test-human` through the
test-only service opt-in. Ordinary production services reject that actor.
No approval occurs from continuation or report generation.

Approval remains preparation-only by default. An explicit
`--include-implementation` expands eligibility through the existing approved
actions parameter. Phase 7 does not authorize scientific runs; this phase
preserves that service boundary. Exact implementation execution scope and
operator-configured framework/runtime adapters remain prerequisites. The CLI
does not guess adapters or fabricate capability/readiness certification.

Service-level checks reject human decisions on paused, terminal or running
projects. Stale selected specs produce an error naming selected/current versions.
Stale assessments, wrong project/packet and changed specs cannot reuse approval.
These checks apply to both CLI and direct service callers.

Pause/resume append PROJECT_PAUSED/PROJECT_RESUMED with actor and public reason.
Science, charter, approvals, spend and round history remain intact. Human STOP
appends HUMAN_STOPPED, separate from Planner STOP, and derives terminal control
state. Resume cannot override either stop. Relevant human/lifecycle events
participate in the existing adaptive state fingerprint. Pause prevents new
continuation; it does not kill an already running child process.

Exit codes: 0 success (including safe halted continuation), 2 invalid input/state,
1 internal failure. Ordinary errors have actionable messages and no traceback.
Confirmation input is injectable; pytest never blocks on stdin.

## Deterministic ledger-grounded report

ReportService and Markdown rendering call no LLM. The canonical project snapshot
supplies the charter, actual source/evidence relationships, all hypothesis and
experiment versions, candidates/selection lineage, human scopes, resource
provenance, readiness, implementation hashes/test receipts/audits, runs, metrics,
analyses/reviews, adaptive choices, limitations and factual telemetry.

Metric values are rendered directly, without new report metrics or model
arithmetic. Each run keeps its own experiment/version and MetricRecord IDs,
condition, role, denominator, failure counts and provenance. Analysis versions
retain exact assessment, interpretation, criteria, causal/generalization scope,
limitations and Critic verdict. Historical PASS and current reviewed eligibility
are labeled separately. An execution COMPLETED label is not a support claim.
The report preserves supportive, negative, null, inconclusive, rejected and
blocked branches. Unexecuted work receives no inferred results.

Literature references come exclusively from SourceRecords, including available
authors/year/DOI/URL/provider/arXiv or provider identifiers. Evidence claims link
to their actual evidence/source IDs; supporting and contradictory relationships
remain explicit. The two-round execution fixture has no literature records and
honestly reports none. Separate tests and the blocked-project-copy report verify
actual literature citations rather than manufacturing references for that fixture.

Phase 12 research_history, round_history and telemetry are reused. Stage duration
pairing now matches experiment/run scope rather than forming all possible event
pairs. Approval waiting ends at the first approval for the exact packet, and
result-to-decision measures the first following PI decision. Pending run records
are distinct from actually executed attempts and completed runs. Duration receipts
retain the paired event IDs. Missing timings stay UNKNOWN. Counters are actual
ledger counts, including imported history where present; run attempts are distinct
from scientific conclusions. There is no measured human baseline or automatic
acceleration multiplier.

Default output is:

`reports/<project_id>/<ledger-path-digest>/research_report.md`

The extra ledger digest prevents same-namespace smoke databases from overwriting
one another's reports. Scientific snapshot hashing excludes REPORT_GENERATED
events so regeneration does not change its own scientific fingerprint. Ordering
follows stable canonical chronology. Repeated generation is byte-identical with
a fixed generation timestamp and semantically identical otherwise.

Files are written to a same-directory temporary file, flushed, then atomically
replaced under a fresh scientific snapshot check. A meaningful REPORT_GENERATED
receipt contains path/project/UTC timestamp, ledger context, snapshot SHA-256 and
report SHA-256. Injected replacement failure preserves the previous file,
rolls back the receipt and removes the temporary file. Concurrent scientific
changes reject publication. The filesystem and SQLite are separate resources;
a host crash at their final commit boundary may require receipt reconciliation,
but cannot leave a partially written Markdown file.

Output redacts configured credentials, recognizable key patterns and credential
assignments, including legacy scientific strings. Exported fields omit arbitrary
agent metadata, source code and raw debug payloads. Tests check configured .env
credentials without printing their values. Final credential scan found zero
configured-key matches in source, agents, docs, tests or generated reports.

## Integration and manual review

```sh
autolab --help
autolab status --help
autolab continue --help
autolab approve --help
autolab report --help
python -m autolab.cli_integration_smoke
python -m autolab.cli_approval_integration_smoke
python -m autolab.report_integration_smoke
python -m pytest -q tests/test_cli.py tests/test_reporting.py tests/test_model_policy.py
python -m pytest -q
```

CLI smoke: **AUTOLAB_CLI_OK**. A fresh isolated charter starts, status works,
pause stops continuation without a Planner call, and resume retains state.

Approval smoke: **AUTOLAB_CLI_APPROVAL_OK**. The exact committed Phase 6
scientific fixture is deliberately selected in a new ledger, receives explicit
test planning estimates and a current packet, then an explicit test-human CLI
approval. Reopening verifies packet/spec/assessment scope. No resource,
implementation, execution authorization or scientific run is created.

Report smoke: **AUTOLAB_REPORT_OK**. It explicitly regenerates the existing
Phase 12 offline full scientific slice, imports its canonical snapshot verbatim
into a separate ledger, adds an unrelated sentinel project and generates the
project-scoped report. Existing production services/restricted child execution
produce measurements; agents/critics and approvals are explicitly offline/test
doubles. The real blocked project is never imported into this report.

Reviewed representative report:

`reports/PROJECT_PHASE10_ISOLATED/0fc700cb8c91/research_report.md`

- Round 1: EXP_PHASE10 v1 / RUN_0001 / METRIC_0001 baseline MAE 0.175 and
  METRIC_0002 clipped MAE 0.07500000000000001; ANALYSIS_0001 v1 SUPPORTED,
  HREV_0002 PASS, within the fixed synthetic cohort only.
- Round 2: separate EXP_0001 v1 / RUN_0002 / METRIC_0003 and METRIC_0004 both
  MAE 0.15000000000000005; ANALYSIS_0002 v1 NOT_SUPPORTED for its preregistered
  condition-difference test, HREV_0005 PASS. This isolated EXP_0001 belongs to
  PROJECT_PHASE10_ISOLATED; it is not the saved blocked project's EXP_0001.
- DEC_0001 requests the distinct frozen in-range negative control, DEC_0002
  selects it, fresh scopes authorize preparation/implementation and exact runs,
  and DEC_0007 STOP retains scientific limitations. Parent run/analysis and
  requesting/selection decision IDs are visible.
- Actual counts: 0 screened papers, 0 literature evidence records, 1 hypothesis,
  2 candidates, 2 completed runs, 7 Planner decisions, 4 explicit test-human
  approval events and 0 revisions. Known runtime dollar costs remain UNKNOWN.

Manual Markdown review checked the question/objective, distinct experimental
cohorts, why follow-up was selected, fresh approvals, actual run identities,
every metric table row, scoped analysis/critique, result-sensitive next choice,
lineage, limitations and provenance. Observation versus interpretation is clear;
both outcomes remain visible and no broader efficacy/proof/acceleration claim
is introduced. The fixture's scientific prose is retained verbatim.

An additional isolated copy of the actual saved blocked project produced:

`reports/PROJECT_SELECTION_READY/f1b11826c4b6/research_report.md`

Its 3 SourceRecords and 6 EvidenceRecords matched stored metadata/IDs. Its
EXP_0001 is explicitly BLOCKED / NOT EXECUTED, with no Phase 10/12 run or metric
leakage. The original saved snapshot/database were opened read-only for checks.

## Integrity and boundaries

The original saved real project snapshot SHA-256 is unchanged:

`cee272e362ed83c97b13839112c80d50cd8b83996dc28c85ee62377ff119598e`

All original canonical SQLite records also match their before-work fingerprint.
The real project's implementations, runs, metrics and analyses remain **zero**;
EXP_0001 remains BLOCKED. ARCHITECTURE.md SHA-256 is unchanged:

`612f4687c3bbd0c5a295d588ae02c72a214e226699d25cef9c647b7a12b145b3`

Production model policy remains gpt-6.1-sol/high, Evidence medium. The 20-case
model-policy check passes; production gpt-5.4 references are zero. CLI/report
are deterministic and introduce no model role. All Phase 13 smokes use ignored
results/SQLite artifacts and reports. Git status reflects the existing untracked
repository baseline; no commit, push or submission package was created.

Development tests exposed two resolved issues: lifecycle checking was initially
attached to packet creation alone rather than human-decision recording, and a
test fixture's default start timestamp followed its supplied completion time.
Both were corrected and regression-tested. Manual review also prompted accurate
resource-provenance keys, scope-matched durations, test counts and explicit
selection/completion references. No failed verdict or scientific record was edited.

Only the Phase 13 MASTER_PLAN row is marked COMPLETE after successful validation.
Phase 14 remains NOT STARTED. No final presentation, video, benchmark comparison,
marketing screenshots, frontend, deployment or submission packaging was built.
