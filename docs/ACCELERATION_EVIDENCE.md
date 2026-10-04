# Acceleration evidence

**Final live audit: INCOMPLETE at readiness. No experiment, measured metric, analysis or post-result decision exists.**

Project: `PROJECT_AUTOLAB_DEMO`. Canonical audit: `results/final-demo/3139fbc73dbf432da21fb22656440f37/audit.json`. No historical scientific records were imported.

## Actual work counts

| Recorded count | Value |
| --- | --- |
| papers_screened | 7 |
| deep_evidence_records | 5 |
| hypotheses_considered | 2 |
| experiment_candidates_considered | 2 |
| experiments_executed | 0 |
| completed_runs | 0 |
| pending_run_records | 0 |
| planner_decisions | 7 |
| human_approvals | 2 |
| revisions | 2 |
| critic_reviews | 6 |
| implementation_revisions | 0 |
| readiness_repairs | 0 |
| model_calls_attempted | 26 |
| model_calls_completed | 25 |
| model_calls_failed | 1 |

Seven paper screening assessments may include repeat publications across batches; two SourceRecords are persisted. Two exact test-human approvals exist, with no RUN approval. `readiness_repairs=0` counts persisted repaired versions; one repair model invocation was attempted and rejected before a new version was persisted. Twenty-six transport attempts include twenty-five completed model responses and one failed daemon invocation; rejected scientific responses count as transport completions, not scientific successes.

## Recorded times

| Stage or interval | Seconds |
| --- | --- |
| preparation | [235.806817] |
| implementation | UNKNOWN / no completed stage |
| analysis | UNKNOWN / no completed stage |
| execution | UNKNOWN / no completed stage |
| result_to_decision | UNKNOWN / no completed stage |
| question_to_first_evidence | 232.032648 |
| evidence_to_hypothesis | 416.925306 |
| hypothesis_to_experiment_spec | 797.97109 |
| approval_waiting | [None, None, 0.004384, 0.004621] |
| spec_to_approval_request | [243.825774, 1195.358401, 1874.885972, 2098.427259] |
| result_to_analysis | UNKNOWN / no completed stage |
| analysis_to_next_planner | UNKNOWN / no completed stage |
| observed_control_and_specialist_active_wall | 630.2751360009715 |
| observed_model_wait_wall | 1090.486904666992 |

Question-to-evidence and stage latencies are wall-clock timestamps and include development, approval and operator delays. Preparation timing records resource creation, not readiness PASS. Failed control invocations lack completion receipts and are excluded from completed-control active time. Model wait overlaps control time; do not add these totals. Near-zero approval waits are automated test-human events, not real human labor measurements. Historical unanswered packets retain UNKNOWN wait endpoints.

## Supported claim and limits

Real Omnigent agents automated retrieval, scientific proposal/review, selection, exact approval, preparation and independent readiness review. The attempt exposed invalid routes, a numeric-equality leakage false positive and unresolved resource-contract requirements. The full reviewed execution loop remains unverified in this project.

No human baseline, human-equivalent time, universal speed multiplier, wet-lab acceleration, provider-token total or actual model-dollar billing was measured. The $20 allocation and zero storage placeholders do not establish zero cost. Unknown billing remains explicitly unknown.
