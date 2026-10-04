# Phase 12: adaptive next-round scientific loop

The Planner chooses one NextDecision from actual reviewed results. Deterministic
software checks eligibility and dispatches existing specialists. There is no new
reasoning agent, fixed follow-up sequence, database table or workflow engine.
The baseline was 846 tests passed / 0 failed before implementation. Final verification:
**910 tests passed / 0 failed**, including all 846 prior cases and 64 Phase 12
cases. The separate 20-case model-policy regression passed.

## Context and decision integrity

PlannerContext includes charter success/stop conditions, known remaining budget,
elapsed/remaining time, current exact hypothesis and falsifiable prediction,
selected contract/reason, run-scoped measurements, deterministic descriptive
comparisons, reviewed assessment/criteria, limitations, confounders and Critic
verdict. Canonical research history retains positive, null, negative and
contradictory outcomes, previous choices and BLOCK/REVISE/rejected branches.
Context remains capped at 24,000 JSON characters. Duplicate prose is compressed;
identities, measurements, unfavorable verdicts and constraints remain visible.
Historical analyses are labeled historical; stale analysis is absent from the
current reviewed-result packet and cannot authorize acceptance or follow-up.

ADAPTIVE_DECISION_CREATED stores concise rationale, source run/spec/analysis and
hypothesis versions, round, budget/time and scientific snapshot fingerprints.
Dispatch rechecks the exact persisted, latest decision under the SQLite write
lock. Scientific versions, new evidence, reviews, metrics, actual costs, human
responses, selection, lifecycle and linked charter changes revoke the receipt.
Original-byte result gates are repeated by the existing services. Audit progress
events alone do not spuriously revoke a specialist's own work.

Acceptance means sufficient support for the charter decision, never proof.
HYPOTHESIS_ACCEPTED_FOR_CHARTER and HYPOTHESIS_REJECTED overlay the disposition
with exact version, reason and reviewed basis. They preserve canonical hypotheses,
reviews/results and uncertainty. A rejected branch cannot be designed again
without a new reviewed refinement/replacement. STOP persists RESEARCH_STOPPED
with an explicit reason; malformed model output never becomes a fallback STOP.

## Existing agents and lineage

GATHER_EVIDENCE reuses EvidencePipeline/OmnigentEvidenceAgent. Adaptive query
planning sees the reviewed result, evidence gap, previous source/evidence IDs and
contradictions. Known publications remain immutable and are excluded from new
deep extraction. The same Evidence Agent can instead choose bounded inspection
of existing result artifacts: no scholarly search or new experiment is performed.
Deterministic inspection reads verified original raw/resource bytes, preserves
all observations up to 24, checks matching sample IDs/order and records
LOCAL_RESULT_EVIDENCE_INSPECTED. No paper citation, new measurement or changed
ScientificAnalysis is fabricated. The compact inspected pairs return to PI.
Larger artifacts require targeted evidence scope rather than an unbounded dump.

REFINE_HYPOTHESIS reuses HypothesisPipeline, Hypothesis Agent and independent
Scientific Critic. It creates the next stable hypothesis version with a changed
falsifiable prediction, parent result and PI trigger. Historical results are
parent evidence, not support automatically transferred to the refined claim.
A fresh PASS hypothesis review is required before design. GENERATE_HYPOTHESES
can propose replacements from real reviewed measurements, retaining rejection
history and distinguishing uncited scientific inference from literature evidence.

RUN_FOLLOWUP and post-result DESIGN_EXPERIMENT use ExperimentDesignPipeline:
two candidates by default, up to three through existing limits, independent
Critic and bounded revision. The Designer receives previous spec/result,
limitations, unresolved confounders, Critic findings, Planner reason, prior
candidate/experiment history and constraints. Planner selection creates a new
immutable spec with parent experiment/run/analysis, requesting decision, reason,
round and selection decision in existing selection/spec events.

A deterministic structured comparison detects equivalent completed scientific
protocols despite changed title/purpose labels. Justified replication declares
`dataset_requirements.purpose=replication` and a meaningful replication_reason.
It remains a new contract requiring fresh approval. This MVP comparison is not
semantic equivalence for every free-text protocol; independent Critic still
assesses scientific distinctness and whether replication adds information.

Fresh feasibility, ApprovalPacket and exact-version human approval are required.
Prior approval never authorizes a new spec. Preparation, independent Readiness,
Implementation/independent Code Audit, deterministic Runtime, Analysis and
Scientific Critic are the existing production services, with unchanged scientific
integrity gates. Exact runtime adapters still need operator configuration;
unsupported new science blocks rather than inventing an execution adapter.

## Bounds and recovery

continue_research accepts 1–20 steps and asks PI at scientific boundaries. Each
specialist's internal plan/audit/revision remains inside its existing workflow.
Human approval, pause, terminal STOP, active runtime and blocks halt continuation.
A completed specialist returns control; no third experimental round is forced.
Once-only ADAPTIVE_DISPATCHED and failure events prevent automatic repeats after
interruption. Partial records remain recoverable through explicit reconciliation,
not a blind retry. A pending undispatched current decision may resume after restart.

Research rounds use RESEARCH_ROUND_STARTED/COMPLETED/NEXT_DECISION events, parent
round and trigger IDs, timestamps, performed work, resulting reviewed analysis
and ending PI decision. Round 1 can register imported existing work explicitly;
its actual first run timestamp is retained. Design/selection alone does not end
a follow-up round: its new reviewed result ends it. Evidence/refinement rounds
end at the completed specialist boundary. Canonical/event links reconstruct
lineage without a graph database.

Charter constraints max_rounds/max_experiments are positive integers. Additional
work is blocked at the hard limit; ROUND_LIMIT_REACHED can retain an unexecuted
proposal for audit. Completion/interpretation of already admitted work remains
possible. Known actual spend aggregates across rounds; estimates never become
actuals, and unknown costs remain unknown. Phase 7 estimate/cap gates enforce
remaining money and time. Recorded timestamps/counters support question→evidence,
evidence→hypothesis, hypothesis→spec, approval waiting, preparation,
implementation, execution, analysis and result→next decision. Missing timings
stay unknown. No human baseline or acceleration factor is invented.

Explicit linked charter authorization is represented by a separately persisted
immutable ResearchCharter plus LINKED_RESEARCH_SCOPE_AUTHORIZED human event.
load_snapshot validates both canonical charter fingerprints and parent identity.
The linked objective, fresh time allocation and budget/limits are visible to PI;
all prior known spend still counts. The original scientific charter is preserved.
This cannot resume a terminal STOP, and Planner cannot create the authorization.

## Integration evidence

```sh
python -m autolab.adaptive_decision_integration_smoke
python -m autolab.adaptive_followup_integration_smoke
python -m autolab.adaptive_loop_integration_smoke
python -m autolab.adaptive_loop_integration_smoke --offline
python -m pytest -q tests/test_adaptive.py
python -m pytest -q tests/test_model_policy.py
python -m pytest -q
```

Live smokes import the actual Phase 11 reviewed checkpoint verbatim into separate
pre-STOP ledgers, verify it against the terminal parent opened read-only and
preserve the parent's STOP in provenance. The explicit Phase 12 request authorizes
PROJECT_PHASE12_SCOPE, max_rounds=2/max_experiments=2. The source namespace and
original raw/code/resource fingerprints remain unchanged. The original saved
real EXP_0001 stays BLOCKED with snapshot SHA-256
`cee272e362ed83c97b13839112c80d50cd8b83996dc28c85ee62377ff119598e`.

Live decision smoke: one gpt-6.1-sol/high Omnigent PI call chose GATHER_EVIDENCE,
citing RUN_0002, ANALYSIS_0001 v2/PASS, baseline MAE 0.175 versus clipped
0.07500000000000001, n=4 per condition, and incomplete representative coverage.
It requested existing artifact inspection before any new experiment. The
follow-up smoke independently chose the same legal divergence and executed the
bounded selected Evidence path with gpt-6.1-sol/medium.

The live full loop likewise chose artifact inspection. All eight original
observations and the frozen four-row resource were read with original hashes.
Both conditions have identical toy-0..toy-3 IDs/order, with no missing/failed
rows. Predictions -0.2 and 1.2 become 0 and 1; predictions 0.3 and 0.7 are
unchanged. Raw SHA-256 remains
`b53585d238225110528290cb8af03e38c0e664df364d45a5807ee9da1545f563`;
resource SHA-256 remains
`70103c3a07dee0a1821f3339ae8dc3cd5baeed3b0abbcf6906bd4c19800b4a51`.
No new live experiment, analysis version, human approval or metric was created.

PI then chose STOP (DEC_0005), explicitly citing new full coverage/order and
boundary-crossing evidence, the two-round limit, synthetic generalization limits,
unavailable independent source-code reproduction and unknown actual costs.
Manual review found the action reduced a real uncertainty, avoided unnecessary
execution and changed the final decision based on new evidence. LEGAL_DIVERGENCE
is the honest live outcome; no stochastic action/verdict was forced.

The deterministic full vertical slice uses real production services/restricted
child execution with explicitly offline scripted agents and test-human approval.
Round 1 baseline/clipped MAE is .175/.075 (SUPPORTED). Two distinct follow-up
cohort candidates are reviewed; PI selects a frozen in-range negative control.
Fresh packet approval and exact implementation run scope are recorded. Round 2
has a separate spec/run/analysis with baseline/clipped MAE
0.15000000000000005/0.15000000000000005 (NOT_SUPPORTED for that preregistered
condition-difference test), followed by STOP. Both outcomes and all original
records remain intact; round 3 is rejected. There are two packet approvals plus
two exact implementation execution-scope events, four human approval events.
No paid model/network call occurs in normal pytest or this offline slice.

Artifacts are ignored JSON/SQLite under results/phase12-*; the persistent offline
full-path artifact is phase12-deterministic-loop-smoke.json. Model configuration
and original scientific integrity gates are production code; scripted choices
and independent fixture audit doubles are explicitly test-only.

## Development failures retained

One sandboxed live attempt failed local daemon startup before a model completed.
Automatic approval review initially rejected escalation; inspecting the exact
nonsecret synthetic payload and citing the user's explicit Omnigent instructions
established authorization for the accepted retry. One real development PI output
referenced the actually supplied linked charter, which exposed a missing context
ID allowlist entry; it was rejected before canonical decision persistence. The
allowlist now includes that validated linked charter only, not foreign scientific
records. This was not an automatic model retry.

The full live branch completed Evidence inspection but exceeded the context bound
before its second PI call. Duplicate recommendations/prose were compressed, and
an explicit resume-after-inspection smoke continued that same branch at PI. It
neither repeated the completed Evidence dispatch nor relaxed the 24,000-character
limit. Four successful live PI calls and one rejected development PI output
occurred across the separate smokes; two live Evidence query-planning calls
selected local inspection. Invocation metadata retains Omnigent 0.16.0,
openai-agents, model/effort and role. Production gpt-5.4 references remain zero.

Phase 13 CLI/report/frontend functionality is not implemented. ARCHITECTURE.md
is unchanged. Only the Phase 12 MASTER_PLAN status was changed to COMPLETE after all final
checks passed. Phase 13 and Phase 14 remain NOT STARTED.
