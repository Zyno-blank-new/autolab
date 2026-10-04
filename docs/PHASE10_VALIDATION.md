# Phase 10 execution and measurement

The ExperimentRuntime is deterministic Python. It calls no AutoLab model, does
not repair code, interpret a hypothesis, create an analysis or dispatch a
follow-up. Only explicit RUN_EXPERIMENT dispatch crosses the execution gate.
Technical COMPLETED means execution and measurement succeeded; a null or
negative condition difference does not make a run FAILED.

The existing `tools/experiment_runner.py` exposes the gated canonical
`run_approved_experiment` entry point and preserves its Phase 1 array-smoke API.

## Admission and adapters

DecisionValidator checks current exact approval, feasibility, spec review,
resources/readiness, implementation source and file set, independent code
review, and deterministic validation receipts. Runtime repeats those checks
under the ledger write lock immediately before its start event. It then reads
bounded JSON resource bytes once, verifies their original-byte SHA-256 and
rejects symlink/changed resource paths. The child receives verified parsed
resources and the freshly hashed source snapshot, without direct input paths.

A trusted RuntimeAdapter must be configured for the exact spec fingerprint.
It supplies context, expected coverage, preregistered metric arguments and an
independent raw-observation oracle. Missing adapters block; the runner does
not guess a metric from its name. Metric functions must be components of the
audited ImplementationPlan. Primary and all secondary metrics must be
preregistered. The paired-scalar adapter belongs only to this controlled
fixture; it is not a universal AutoLab MAE policy.

## Restricted offline execution

Phase 10 reuses Phase 9's restricted loader, import proxies, builtins, audit
hook and CPU/file-size limits. A separate trusted entry point invokes setup,
run and collect_results; Phase 9 still never calls run. The process starts
with Python `-I -S`, an explicit nonsecret environment and a fresh per-run
working directory. Network and direct filesystem/system capabilities are
denied. Output and logs are bounded; timeout/cancellation kills the process
group. The timeout covers execution and metric computation together. No
whole-experiment retry occurs automatically. New dependencies are not installed.

This profile is defense in depth for statically admitted small Python programs,
not an OS sandbox or a guarantee for arbitrary malicious Python. Native
Seatbelt remains unavailable in this managed session. The MVP supports offline
JSON-resource protocols only; live subject inference and credential/network
capabilities require a separately approved future runtime scope.

## Runs, observations and metrics

Each attempt reserves a distinct RUN ID and exclusively creates
`experiments/<experiment>/runs/<run>/`. It preserves config, stdout/stderr,
metric process logs, raw_outputs.jsonl and metrics.json, with SHA-256 and byte
size references. The config pins scientific dependencies, audited source,
seed, adapter, limits and policy. Python version, framework identity, timing,
exit statuses and observed usage are retained. Phase 9 validation receipts
also now retain child Python and framework-source versions in their existing
output field; historical receipts/reviews are not rewritten.

Every raw observation is wrapped with run/spec identity, implementation hash
and full resource pins. Implementation-generated comparisons/conclusions are
excluded from the persisted scientific envelope. Metric arguments are derived
from validated raw observations; audited deterministic functions execute in a
separate restricted process. An independent trusted oracle must agree before
final MetricRecords are persisted. Their metadata preserves condition, role,
denominator, supporting counts/sums, method/component and raw-artifact hash.

The scalar contract requires ordered paired coverage of every frozen sample,
identity/clipping without target leakage, and one counted rule attempt per
sample-condition. Missing or failed samples remain raw evidence and prevent
a successful-only MAE denominator. The runtime does not create partial final
metrics or invented observations. Other failure policies need an explicit
reviewed adapter matching that spec.

## Append-only lifecycle and integrity

The existing run table remains immutable. Active identity and config live in
EXPERIMENT_RUN_STARTED events; one final ExperimentRun is inserted atomically
with its metrics, cost record and terminal events. FAILED, TIMED_OUT and
CANCELLED attempts preserve available raw evidence/logs and return Planner
control. An unfinalized start remains visibly active after a host interruption;
it cannot silently trigger a repeat dispatch. Whole-process recovery requires
explicit operator reconciliation rather than an automatic rerun.

Dependencies are checked again before publication and under the final ledger
lock. Changed dependencies revoke completed-result eligibility. Historical
source/result artifacts are not overwritten. Actual local dollar cost is
UNKNOWN/null because no trustworthy billable measurement exists; Phase 7
estimates are never converted into actuals. Nullable known-cost fields preserve
legacy defaults while allowing new truthful unknown records.

ANALYZE_RESULT requires a current COMPLETED run, matching config/source/spec
pins, intact artifacts, exact run-scoped canonical metrics and a trusted
completion receipt. Labels alone do not grant analysis eligibility. Failed,
incomplete, tampered, wrong-run or missing-primary results are rejected. The
existing ANALYSIS control state is the results-available Phase 11 boundary;
no analysis dispatch is implemented here. Planner context contains compact
measurements, usage, references and errors, without raw dumps or interpretation.

## Isolated smoke

```sh
python -m autolab.experiment_runtime_integration_smoke
python -m autolab.experiment_runtime_integration_smoke --planner
python -m pytest -q tests/test_runtime.py
python -m pytest -q
```

The live smoke creates a new linked PROJECT_PHASE10_ISOLATED charter and
EXP_PHASE10 with the same frozen four-row scientific protocol as Phase 9.
It rebinds only provenance/identity strings in the saved generated source,
then performs fresh static checks, toy tests and an independent Omnigent code
audit. The old PASS never authorizes altered code. An explicit isolated
test-human event grants exact implementation execution scope. The production
approval interface is not silently expanded. Real EXP_0001 is read only.

The smoke executes twice, independently recomputes the persisted condition
metrics, compares scientific observations/metrics, verifies distinct IDs and
hashes, and optionally makes at most one real post-run Omnigent Planner call.
Any legal decision is accepted as a route only. Preparation audit calls are
separate from the model-free runtime. Normal pytest makes no model or network
calls. Controlled failure, timeout, cancellation, partial observations, skipped
samples, artifact tampering, wrong-run metrics, secondary preregistration and
null scientific differences are exercised with offline child-process/ledger
fixtures.

## Verified execution

All 755 offline tests pass, including the previous 704 tests and 51 Phase 10
tests. The live linked fixture retains two BLOCK and two REVISE reviews from
identity/revision import errors; its two immutable corrections stay within the
new fixture's two-round bound. No failed check or verdict was overwritten.
HREV_0005 independently approved IMPL_0003, source hash
`a496a5d1b02a0d74437d782fb9cf8da7b91c90972fbb709aa4bf8986c2f068aa`,
after 18 framework checks and 11 generated tests passed.

RUN_0001 and RUN_0002 both COMPLETED with eight raw observations and eight
counted rule calls each. Their baseline MAE was 0.175 and clipped MAE was
0.07500000000000001, each with denominator four. Independent recomputation
from persisted observations agreed. Scientific observations and metric values
were identical across the distinct runs. The measured durations were
approximately 0.104 and 0.098 seconds; known actual dollar cost remained null.

The first raw artifact SHA-256 is
`5e509edb68fb7765a80d2e9e4edf459ae79c277c9d75f03473d4a3404878a74c`;
the second is
`b53585d238225110528290cb8af03e38c0e664df364d45a5807ee9da1545f563`.
Their envelopes have distinct run IDs; scientific observations match after
removing identity wrappers. Manual inspection confirmed ordered conditions,
raw prediction/reference values, full denominators, matching hashes and no
scientific interpretation. One real post-run Planner call legally chose STOP.
ANALYZE_RESULT was eligible before STOP, but no Phase 11 role executed. The
saved real EXP_0001 snapshot retained SHA-256
`cee272e362ed83c97b13839112c80d50cd8b83996dc28c85ee62377ff119598e`
and zero implementations, runs or metrics.
