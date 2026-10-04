> **INCOMPLETE READINESS CHECKPOINT.** No implementation or experiment has executed. Readiness is REPAIR and the attempted repair was rejected; prospective numbers remain deductions, not measurements. The numeric-equality validator defect was fixed after this preserved review; the remaining readiness requirements have no new PASS. Original canonical report SHA-256: `3ebc57d75e82f7e43b168af88d1ca9964b6f5c88d518834def728890c78018ac`.

# AutoLab Research Report

This report separates canonical observations from recorded scientific interpretation. Assessments describe their stated scope; they are not statistical proof.

## Project Summary

- **Project ID:** PROJECT_AUTOLAB_DEMO
- **Research question:** When does range clipping help or harm the reliability of scalar AI predictions compared with leaving predictions unchanged?
- **Objective:** Decide whether clipping to [0,1] is defensible in one frozen synthetic cohort, with target-domain validity explicitly examined. Demonstrate the reviewed computational scientific loop, not population efficacy or tool-agent behavior.
- **Status:** RESOURCE_PREPARATION
- **Stopped:** False
- **Rounds:** 4 / 6
- **Generated timestamp (UTC):** 2026-10-04T11:01:02.998444+00:00
- **Ledger context:** results/final-demo/3139fbc73dbf432da21fb22656440f37/demo.db
- **Ledger snapshot SHA-256:** 268947ca9f1d3064ff785c2e3c2287d43421d2891015ad23c29b105a405a510c

## Research Charter

- **Title:** AutoLab: an output guardrail under test
- **Question:** When does range clipping help or harm the reliability of scalar AI predictions compared with leaving predictions unchanged?
- **Original objective:** Decide whether clipping to [0,1] is defensible in one frozen synthetic cohort, with target-domain validity explicitly examined. Demonstrate the reviewed computational scientific loop, not population efficacy or tool-agent behavior.
- **Primary outcome:** Condition-wise mean_absolute_error over all four matched samples
- **Success criteria:** {"decision": "A reviewed, reproducible condition comparison and a result-sensitive next decision; a negative or inconclusive scientific outcome is valid."}
- **Constraints:** {"demo_scope": "One approved CPU experiment; at most one post-result specialist action. No inference, training, wet lab, external subject model, or general efficacy claim.", "max_experiments": 1, "max_rounds": 6, "operator_supported_protocol": {"candidate_choices": "Two distinct candidate cohorts: bounded targets or range_shift targets. The Planner selects. Copy chosen rows into dataset_requirements.frozen_rows before approval. Do not select rows after results.", "cohorts": {"bounded": [{"prediction": -0.2, "sample_id": "bounded-0", "target": 0.1}, {"prediction": 0.3, "sample_id": "bounded-1", "target": 0.4}, {"prediction": 1.2, "sample_id": "bounded-2", "target": 0.9}, {"prediction": 0.7, "sample_id": "bounded-3", "target": 0.7}], "range_shift": [{"prediction": -0.2, "sample_id": "shift-0", "target": -0.3}, {"prediction": 0.3, "sample_id": "shift-1", "target": 0.4}, {"prediction": 1.2, "sample_id": "shift-2", "target": 1.3}, {"prediction": 0.7, "sample_id": "shift-3", "target": 0.7}]}, "criteria_format": {"falsification_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "maximum_improvement": 0}, "success_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "minimum_improvement": 0}}, "independent_variables": {"condition": ["baseline", "clipped"], "max_calls_per_sample": 1, "seed": 19}, "interpretation": "These are synthetic scalar outputs, not measured AI-model answers. Literature is background/method evidence, not evidence for these future fixture outcomes. Range_shift violates the proposed clipping range on purpose; do not assume targets are bounded for that candidate.", "primary_metric": "mean_absolute_error", "resource": "Exactly one frozen JSON list of four rows with sample_id, prediction, target; required_capabilities=[filesystem_access].", "rules": "baseline identity; clipped min(1,max(0,prediction)); predict receives prediction and condition only; target is scorer-only; all four rows in both conditions in the same order; no missing-row exclusions.", "secondary_metrics": []}, "stop_conditions": ["One completed and reviewed comparison followed by a justified decision", "Missing scientific prerequisite or unsupported contract", "Explicit human rejection, budget/time exhaustion, or call cap"]}
- **Budget allocation USD:** 20.0
- **Time limit minutes (0 = unconfigured):** 60.0
- **Stop conditions:** []
- **Explicit human-authorized linked charter:** PROJECT_AUTOLAB_DEMO_COMPLETION_01
- **Linked objective:** Decide whether clipping to [0,1] is defensible in one frozen synthetic cohort, with target-domain validity explicitly examined. Demonstrate the reviewed computational scientific loop, not population efficacy or tool-agent behavior.
- **Linked constraints:** {"completion_authorization": "User explicitly approved full isolated test and linked 30-minute window; existing 40 total transport-attempt cap and $20 allocation, unknown billing acknowledged; original science unchanged", "demo_scope": "One approved CPU experiment; at most one post-result specialist action. No inference, training, wet lab, external subject model, or general efficacy claim.", "max_experiments": 1, "max_rounds": 6, "operator_supported_protocol": {"candidate_choices": "Two distinct candidate cohorts: bounded targets or range_shift targets. The Planner selects. Copy chosen rows into dataset_requirements.frozen_rows before approval. Do not select rows after results.", "cohorts": {"bounded": [{"prediction": -0.2, "sample_id": "bounded-0", "target": 0.1}, {"prediction": 0.3, "sample_id": "bounded-1", "target": 0.4}, {"prediction": 1.2, "sample_id": "bounded-2", "target": 0.9}, {"prediction": 0.7, "sample_id": "bounded-3", "target": 0.7}], "range_shift": [{"prediction": -0.2, "sample_id": "shift-0", "target": -0.3}, {"prediction": 0.3, "sample_id": "shift-1", "target": 0.4}, {"prediction": 1.2, "sample_id": "shift-2", "target": 1.3}, {"prediction": 0.7, "sample_id": "shift-3", "target": 0.7}]}, "criteria_format": {"falsification_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "maximum_improvement": 0}, "success_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "minimum_improvement": 0}}, "independent_variables": {"condition": ["baseline", "clipped"], "max_calls_per_sample": 1, "seed": 19}, "interpretation": "These are synthetic scalar outputs, not measured AI-model answers. Literature is background/method evidence, not evidence for these future fixture outcomes. Range_shift violates the proposed clipping range on purpose; do not assume targets are bounded for that candidate.", "primary_metric": "mean_absolute_error", "resource": "Exactly one frozen JSON list of four rows with sample_id, prediction, target; required_capabilities=[filesystem_access].", "rules": "baseline identity; clipped min(1,max(0,prediction)); predict receives prediction and condition only; target is scorer-only; all four rows in both conditions in the same order; no missing-row exclusions.", "secondary_metrics": []}, "parent_project": "PROJECT_AUTOLAB_DEMO", "stop_conditions": ["One completed and reviewed comparison followed by a justified decision", "Missing scientific prerequisite or unsupported contract", "Explicit human rejection, budget/time exhaustion, or call cap"]}
- **Linked budget / time:** 20.0 USD / 30.0 minutes

The original scientific records retain their original project identity; the linked charter is an explicit authorized scope.

## Evidence Review

### EVID_0001 → SRC_0001

- **Recorded claim:** The abstract identifies distribution shifts, feedback loops, and adversarial actors as challenges to forecast validity; this provides background context, not evidence about scalar clipping or its effect on mean absolute error.
- **Supporting publication text:** Real-world data streams can change unpredictably due to distribution shifts, feedback loops and adversarial actors, which challenges the validity of forecasts.
- **Location:** abstract
- **Tags:** ["BACKGROUND", "ABSTRACT_ONLY", "distribution_shift", "forecast_validity", "abstract_only"]
- **Supporting relationship:** No relationship recorded
- **Contradictory relationship:** No relationship recorded

### EVID_0002 → SRC_0001

- **Recorded claim:** The abstract reports a Blackwell-approachability forecasting framework that guarantees calibrated uncertainties for outcomes in a compact space, including bounded regression. This reported guarantee concerns uncertainty calibration, not the efficacy of clipping scalar predictions to [0,1].
- **Supporting publication text:** Leveraging the concept of Blackwell approachability from game theory, we introduce a forecasting framework that guarantees calibrated uncertainties for outcomes in any compact space (e.g., classification or bounded regression).
- **Location:** abstract
- **Tags:** ["BACKGROUND", "ABSTRACT_ONLY", "uncertainty_calibration", "bounded_regression", "compact_outcome_space", "abstract_only"]
- **Supporting relationship:** No relationship recorded
- **Contradictory relationship:** No relationship recorded

### EVID_0003 → SRC_0002

- **Recorded claim:** The abstract describes an image-restoration method that iteratively projects images onto convex constraint sets and uses particle swarm optimization to tune a relaxation parameter. This is methodological background for constraint-based prediction adjustment, not direct evidence about scalar clipping to [0,1].
- **Supporting publication text:** For this task, a number of convex sets are used as constraints and images are projected to these sets iteratively to reach restored image. Since relaxation parameter in POCS has a significant effect on restoration results, PSO is developed to find the best value for this parameter to be used in restoration process.
- **Location:** abstract
- **Tags:** ["METHOD", "ABSTRACT_ONLY", "convex_constraints", "iterative_projection", "parameter_optimization", "abstract_only", "indirect_evidence"]
- **Supporting relationship:** No relationship recorded
- **Contradictory relationship:** No relationship recorded

### EVID_0004 → SRC_0001

- **Recorded claim:** The abstract identifies distribution shifts, feedback loops, and adversarial actors as challenges to forecast validity. This provides background on changing data domains, not evidence that clipping helps or harms mean absolute error.
- **Supporting publication text:** Real-world data streams can change unpredictably due to distribution shifts, feedback loops and adversarial actors, which challenges the validity of forecasts.
- **Location:** abstract
- **Tags:** ["BACKGROUND", "ABSTRACT_ONLY", "distribution_shift", "forecast_validity", "abstract_only", "indirect_evidence"]
- **Supporting relationship:** No relationship recorded
- **Contradictory relationship:** No relationship recorded

### EVID_0005 → SRC_0001

- **Recorded claim:** The abstract reports a forecasting framework with calibrated-uncertainty guarantees for outcomes in any compact space, including bounded regression. This reported domain condition does not establish that the charter's targets belong to [0,1] or validate scalar clipping under mean absolute error.
- **Supporting publication text:** Leveraging the concept of Blackwell approachability from game theory, we introduce a forecasting framework that guarantees calibrated uncertainties for outcomes in any compact space (e.g., classification or bounded regression).
- **Location:** abstract
- **Tags:** ["BACKGROUND", "ABSTRACT_ONLY", "calibration", "compact_outcome_space", "bounded_regression", "domain_assumptions", "abstract_only", "indirect_evidence"]
- **Supporting relationship:** No relationship recorded
- **Contradictory relationship:** No relationship recorded

## Hypotheses

### HYP_0001 v1

- **Statement:** Conditional on selection of the supplied bounded cohort, clipping predictions to [0,1] will reduce mean_absolute_error over all four matched samples because the two out-of-range predictions are moved toward targets inside the clipping interval.
- **Rationale:** AGENT-GENERATED HYPOTHESIS<br>SUPPORTED BY EVIDENCE: No supplied EvidenceRecord directly supports or contradicts the predicted clipping effect. EVID_0005 supplies background about outcome-domain assumptions, and EVID_0003 supplies constraint-projection methodological background; neither validates this scalar adjustment under absolute error. Both directional evidence lists therefore remain empty.<br>SCIENTIFIC INFERENCE / PROPOSED EXPLANATION: LOW-CONFIDENCE inference regarding empirical efficacy, with numerical expectations deduced from supplied synthetic rows rather than measured outcomes. In the bounded fixture, the proposed explanation is removal of excess prediction distance beyond valid target bounds: clipping is expected to reduce absolute error by 0.2 on each of the two out-of-range prediction rows and leave the other two unchanged. This is conditional on the Planner choosing that cohort, not a recommendation to select it. A null effect would be plausible for a different bounded fixture with no out-of-range predictions, so target boundedness alone does not imply strict improvement in every cohort. The proposal concerns only this synthetic comparison, not calibration, population reliability, or actual AI-model efficacy.
- **Falsifiable prediction:** If the bounded cohort is selected, the fixed all-four-row comparison will yield baseline mean_absolute_error of 0.175 and clipped mean_absolute_error of 0.075, a predicted reduction of 0.100. These are prospective fixture deductions, not measurements. The directional hypothesis is falsified if clipped mean_absolute_error is greater than or equal to baseline; values incompatible with the predicted pair would also refute its exact numerical prediction.
- **Supporting evidence IDs:** []
- **Contradicting evidence IDs:** []
- **Canonical status:** PROPOSED
- **Planner disposition:** No disposition recorded
- **Scientific critique:** HREV_0001 PASS

### HYP_0002 v1

- **Statement:** Conditional on selection of the supplied range_shift cohort, clipping predictions to [0,1] will increase mean_absolute_error over all four matched samples because the clipping interval excludes two targets and moves their already nearby predictions farther from them.
- **Rationale:** AGENT-GENERATED HYPOTHESIS<br>SUPPORTED BY EVIDENCE: No supplied EvidenceRecord directly supports or contradicts the predicted harm from clipping. EVID_0001 provides distribution-shift background, while EVID_0005 emphasizes that compact-domain calibration claims do not establish membership in [0,1]. These are background considerations, not directional evidence for this fixture outcome; both directional evidence lists remain empty.<br>SCIENTIFIC INFERENCE / PROPOSED EXPLANATION: LOW-CONFIDENCE inference regarding empirical efficacy, with numerical expectations deduced from supplied synthetic rows rather than measured outcomes. The competing explanation is incorrect enforcement of a target-domain constraint rather than removal of invalid prediction excursions. For the two range_shift rows with out-of-range targets, clipping is expected to increase absolute error by 0.2 each while leaving the other two rows unchanged. This prediction is conditional on the Planner choosing that cohort and does not request another experiment. Out-of-range targets alone do not imply harm for every possible prediction; the predicted direction depends on the supplied prediction-target geometry. Neither the anticipated harm nor the bounded-cohort proposal establishes a general rule across populations.
- **Falsifiable prediction:** If the range_shift cohort is selected, the fixed all-four-row comparison will yield baseline mean_absolute_error of 0.075 and clipped mean_absolute_error of 0.175, a predicted increase of 0.100. These are prospective fixture deductions, not measurements. The directional hypothesis is falsified if clipped mean_absolute_error is less than or equal to baseline; values incompatible with the predicted pair would also refute its exact numerical prediction.
- **Supporting evidence IDs:** []
- **Contradicting evidence IDs:** []
- **Canonical status:** PROPOSED
- **Planner disposition:** No disposition recorded
- **Scientific critique:** HREV_0002 PASS

## Experimental Program

| Candidate/version | Hypothesis/version | Approach | Estimated USD |
| --- | --- | --- | --- |
| CAND_0001 v1 | HYP_0002 v1 | Propose one deterministic, paired CPU comparison of identity predictions versus clipping to [0,1]. Hold rows, ordering, scoring and computational allowance fixed. Evaluate the preregistered condition-wise mean_absolute_error and inspect row-level arithmetic solely for protocol integrity and the proposed geometric explanation. The expected values are prospective deductions, not experimental results. Only the Planner-selected candidate may run. | UNKNOWN |
| CAND_0002 v1 | HYP_0002 v1 | Propose the same approved identity-versus-clipping intervention on the distinct bounded-target cohort. The predictions are identical to those in range_shift, but the two out-of-range targets are replaced by supplied in-range targets. This changes prediction-target geometry rather than sample size. Only this cohort would run if selected; no observed cross-cohort contrast is claimed. | UNKNOWN |
| CAND_0001 v2 | HYP_0002 v1 | Propose one deterministic, matched CPU comparison of baseline identity versus clipping to [0,1]. Preserve the frozen rows, ordering, scorer-only targets and equal computational allowances. Define hypothesis support through increased clipped mean_absolute_error, not the charter's separate clipping-benefit comparison. Retain row-level records to audit the aggregate and the proposed prediction-target geometry. The numerical expectations are prospective fixture deductions, not measured results. Only one Planner-selected and approved candidate may run. | UNKNOWN |
| CAND_0002 v2 | HYP_0002 v1 | Retain the distinct supplied bounded cohort and its complete matched identity-versus-clipping design. Repair the decision contract by making exact-hypothesis evaluation inapplicable and approval blocked in this workflow. Do not treat bounded benefit as support or falsification of HYP_0002, do not compare an observed bounded outcome with unexecuted range_shift deductions as an observed interaction, and do not relabel the range_shift experiment as a second design. PROPOSED status preserves the assigned candidate record; it does not establish scientific eligibility. | UNKNOWN |

### EXP_0001 v1 — BLOCKED / NOT EXECUTED

- **Hypothesis:** HYP_0002 v1
- **Objective:** Evaluate the exact conditional harm prediction in HYP_0002 version 1 using all four supplied range_shift rows. Distinguish support for that hypothesis from benefit of clipping as an intervention.
- **Experiment type:** Deterministic matched finite-cohort intervention comparison
- **Conditions / independent variables:** {"baseline_rule": "Return prediction unchanged.", "clipped_rule": "Return min(1,max(0,prediction)).", "cohort": "range_shift", "condition": ["baseline", "clipped"], "max_calls_per_sample": 1, "seed": 19}
- **Controls / baseline:** {"comparator": "Baseline identity transformation on the identical supplied predictions.", "execution_control": "No tuning, stateful adaptation, stochastic perturbation or adaptive row selection. Seed 19 remains fixed; randomization is unnecessary for these deterministic transformations.", "fair_budget": "One transformation call per sample per condition; no inference, training or external model.", "matching": "Use all four rows in both conditions in the supplied order, without missing-row exclusions.", "negative_controls": "Predictions 0.3 and 0.7 must remain unchanged under clipping.", "robustness_checks": ["Audit returned predictions against identity and min(1,max(0,prediction)) without adding another condition.", "Verify that predictions 0.3 and 0.7 are unchanged and that each boundary-excursion row has the prospectively deduced 0.2 increase in absolute error.", "Reconcile retained row-level errors with each four-row mean and the preregistered numerical tolerance.", "Verify complete matching and scorer-only target access.", "Audit the decision mapping: positive Delta supports directional harm, and zero or negative Delta contradicts it only after integrity is established."], "target_isolation": "The prediction function receives prediction and condition only. Target is accessible only to the scorer."}
- **Dependent variables:** {"definition": "For each condition, sum abs(returned_prediction - target) over the four frozen rows and divide by four. Targets are scorer-only.", "hypothesis_contrast": "Delta = clipped mean_absolute_error minus baseline mean_absolute_error. Positive Delta denotes clipping harm.", "integrity_diagnostics": "Retain sample IDs, condition labels, returned predictions and row-level absolute errors for auditing. These are audit quantities, not additional outcome metrics.", "primary": "Condition-wise mean_absolute_error over exactly four matched samples.", "primary_metric_rationale": "This is both the charter's primary outcome and the exact hypothesis's outcome. Equal weighting over all four matched rows prevents selective reporting of the two affected rows. Delta is a contrast of the same primary metric, not a second metric."}
- **Dataset requirements:** {"adequacy": "Complete scoring of these four rows exhausts the specified finite evaluand. No population power calculation is warranted; missing or altered rows invalidate the comparison.", "cohort": "range_shift", "data_integrity": "Require the four unique expected sample IDs, finite numeric values and exact correspondence to the frozen list.", "evaluation_separation": "No fitting or outcome-dependent design selection occurs. An additional held-out split is unnecessary, but targets must remain isolated from prediction logic.", "format": "Exactly one frozen JSON list of four rows containing sample_id, prediction and target.", "frozen_rows": [{"prediction": -0.2, "sample_id": "shift-0", "target": -0.3}, {"prediction": 0.3, "sample_id": "shift-1", "target": 0.4}, {"prediction": 1.2, "sample_id": "shift-2", "target": 1.3}, {"prediction": 0.7, "sample_id": "shift-3", "target": 0.7}], "planning_limitations": ["Phase 7 must verify existing filesystem access, CPU transformation/scoring support, target isolation and complete audit-record support without acquiring new resources.", "Phase 7 must confirm Planner selection and the immutable four-row contract before approval.", "Phase 7 must verify that downstream evaluation can represent direction=higher and the strict success threshold. If it cannot, this is an unsupported contract: stop rather than revert to benefit criteria or change the hypothesis.", "Cost and runtime are unknown. Phase 7 must establish fit within the supplied remaining budget and time.", "Information-gain and feasibility scores are advisory judgments, not measurements or readiness certifications.", "No reviewed result or previous experiment exists. This revision is neither replication nor a post-result mechanism experiment."], "purpose": "Direct conditional hypothesis test, not replication.", "sampling_strategy": "Census of the supplied four-row range_shift cohort. No resampling, added seeds, generated rows or sample-count expansion. Completeness establishes adequacy for this finite fixture, not population precision.", "selection_and_freeze": "The Planner must select the cohort before approval. If this candidate is selected, preserve this exact list; do not substitute bounded rows, change targets or select rows after results.", "synthetic_data_limits": "No generation or acquisition is needed. Deliberately constructed target geometry, limited diversity and unrealistic deployment frequencies preclude population claims. Known targets must not be encoded into prediction logic."}
- **Primary metric:** mean_absolute_error
- **Secondary metrics:** []
- **Success criterion:** {"charter_comparison_scope": "Retain the supplied generic benefit comparison as a separate intervention assessment. It is not an input to the hypothesis-support classification; equality is not evidence of strict benefit.", "charter_intervention_benefit_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "minimum_improvement": 0}, "comparison": {"control": "baseline", "direction": "higher", "intervention": "clipped", "minimum_improvement": 0, "threshold_operator": "&gt;"}, "comparison_semantics": "For hypothesis evaluation, improvement means movement in the hypothesized direction: increased error. This comparison requires clipped mean_absolute_error minus baseline mean_absolute_error strictly greater than zero. Equality is not success. Increased error is intervention harm, not predictive improvement.", "eligibility": "Apply only after range_shift is selected and the complete frozen-row, target-isolation, matching, transformation and scoring integrity gates pass.", "exact_prediction": {"absolute_numerical_tolerance": 1e-12, "baseline_mean_absolute_error": 0.075, "clipped_mean_absolute_error": 0.175, "clipped_minus_baseline": 0.1, "interpretation": "Prospective arithmetic deductions. The tolerance addresses floating-point representation, not sampling uncertainty, and does not replace the strict directional threshold."}, "expected_result_patterns": {"contradicted": "An audited Delta less than or equal to zero contradicts the directional hypothesis. An audited mismatch with the predicted means or contrast contradicts the numerical component. Because the arithmetic is predetermined, unexpected values first require protocol-integrity review.", "inconclusive": "An unmet cohort antecedent, unsupported execution, incomplete rows, leakage or unresolved scoring prevents hypothesis interpretation. Even an exact numerical match remains inconclusive about population-level clipping harm.", "supported": "Valid means of 0.075 baseline and 0.175 clipped, within the preregistered tolerance, support the exact fixture prediction. Positive Delta alone supports its direction but not an incompatible numerical component. Support indicates clipping harm in this frozen cohort."}, "hypothesis_support": "A valid positive Delta supports the directional claim. Support for the exact numerical prediction additionally requires both means and their contrast to match the preregistered values within the stated tolerance.", "scientific_completion": "Require complete matched scoring, reviewed integrity and a scope-limited next decision. Software completing a run is insufficient."}
- **Falsification criterion:** {"charter_comparison_scope": "Failure of clipping to benefit this fixture is separate from falsification of HYP_0002. The predicted harm supports the hypothesis while failing the benefit assessment.", "charter_intervention_benefit_failure_comparison": {"control": "baseline", "direction": "lower", "intervention": "clipped", "maximum_improvement": 0}, "comparison": {"control": "baseline", "direction": "higher", "intervention": "clipped", "maximum_improvement": 0, "threshold_operator": "&lt;="}, "comparison_semantics": "A protocol-valid Delta less than or equal to zero falsifies the strict directional harm prediction. Equality belongs to directional falsification, not hypothesis success.", "exact_numerical_prediction": "A protocol-valid mismatch exceeding 1e-12 for either predicted condition mean or the predicted contrast contradicts the exact numerical component, even if Delta remains positive.", "inconclusive_criteria": "The exact hypothesis is untested if range_shift is not selected. Treat execution as inconclusive if any frozen row is missing, changed, duplicated or excluded; targets reach prediction logic; conditions receive different predictions or allowances; transformations or scoring cannot be audited; or numerical integrity prevents determining the contrast. Four complete valid rows suffice for the finite-fixture claim. No result resolves population efficacy.", "integrity_gate": "Investigate unexpected values first for transformation, matching, target-isolation and scoring defects. An unresolved protocol defect is inconclusive, not falsification."}
- **Assumptions:** ["The exact hypothesis remains HYP_0002 version 1.", "The range_shift rows define the entire evaluand, and two targets intentionally fall outside [0,1].", "Predicted harm depends on the supplied prediction-target geometry; out-of-range targets alone do not imply harm for arbitrary predictions.", "EVID_0001 and EVID_0005 provide background only, not directional evidence for the fixture outcome.", "The candidates are alternatives, and the charter permits only one approved experiment.", "The structured hypothesis criteria and separate charter benefit criteria must remain distinct throughout evaluation."]
- **Potential confounders:** ["Condition-dependent ordering, state or computational allowances.", "Swapped condition labels, scoring original rather than transformed predictions, or using a denominator other than four.", "Selecting rows or redefining the clipping interval after results.", "Treating intentional out-of-range targets as data errors or assuming every compact target domain is [0,1].", "Using the charter's benefit comparison to classify support for the harm hypothesis.", "Presenting constructed scalar outputs as measured AI-model answers."]
- **Planner selection / follow-up lineage:** {"decision_id": "DEC_0007", "followup_reason": null, "parent_analysis_id": null, "parent_analysis_version": null, "parent_experiment_id": null, "parent_experiment_version": null, "parent_run_id": null, "reason": "Select CAND_0001 version 2, PASS-reviewed by ERREV_0005 and aligned with HYP_0002 version 1. Its predicted MAE increase from 0.075 to 0.175 is a prospective fixture deduction, not a measurement. This four-row matched comparison is the smallest permitted test of reproducible protocol fidelity when the clipping interval excludes targets; confirmed harm would support HYP_0002 while making clipping indefensible for this frozen cohort. CAND_0002 version 2 remains BLOCK-reviewed: bounded targets cannot test the selected range_shift hypothesis, and the one-experiment cap prevents later repair. Preserve that alternative and its blocker. Freeze the supplied range_shift rows unchanged before approval, with scorer-only targets and complete matched aggregation. Selection authorizes no execution: readiness must verify the strict higher-error hypothesis comparison separately from clipping benefit, existing capabilities, audit support, and cost/runtime fit within the remaining limits; fresh exact-version human approval is required. Stop if prerequisites fail. Any numerical disagreement requires auditing before scientific interpretation; no population or AI-model efficacy inference is warranted.", "round_id": null, "selection_decision_id": null}
- **Scientific review:** ERREV_0005 PASS
No measured result exists for this experiment version.

## Human Decisions

| Event | Timestamp UTC | Decision / source | Exact scope / note |
| --- | --- | --- | --- |
| EVENT_0107 | 2026-10-04T10:42:25.622656Z | HUMAN_APPROVED / test-human | {"approved_actions": ["PREPARE_RESOURCES", "IMPLEMENT_EXPERIMENT"], "assessment_id": "FEAS_0003", "experiment_id": "EXP_0001", "experiment_version": 1, "max_cost_usd": 20.0, "max_runtime_minutes": 20.0, "note": "Explicit --test-human automated isolated final audit; unknown billing acknowledged; exact packet scope only", "packet_id": "APKT_0003"} |
| EVENT_0124 | 2026-10-04T10:46:09.164180Z | HUMAN_APPROVED / test-human | {"approved_actions": ["PREPARE_RESOURCES", "IMPLEMENT_EXPERIMENT"], "assessment_id": "FEAS_0004", "experiment_id": "EXP_0001", "experiment_version": 1, "max_cost_usd": 20.0, "max_runtime_minutes": 20.0, "note": "Explicit --test-human automated isolated final audit; unknown billing acknowledged; exact packet scope only", "packet_id": "APKT_0004"} |

## Resource Preparation and Readiness

| Resource | Exact experiment | Purpose | Reference / SHA-256 / provenance |
| --- | --- | --- | --- |
| RES_0001 | EXP_0001 v1 | Reuse the exact approved range_shift cohort without generation, sampling, alteration or outcome-dependent selection. The audit-location component is covered by REQ_CPU_AUDIT_ENVIRONMENT. | {"provenance": {"acquisition_mode": "EXISTING", "creation_tool": "local", "parent_ids": [], "source_uri": "results/final-demo/3139fbc73dbf432da21fb22656440f37/operator-inputs/frozen_rows.json"}, "reference": "results/final-demo/3139fbc73dbf432da21fb22656440f37/data/shared/7aed123a893ad2c94ea488f7f9e5f306e0752ea61fb6138458bf584f5e62df15.json", "sha256": "7aed123a893ad2c94ea488f7f9e5f306e0752ea61fb6138458bf584f5e62df15", "source": "Operator resource_catalog; frozen_rows declared in EXP_0001 version 1."} |
| RES_0002 | EXP_0001 v1 | Reuse catalog evidence for the existing offline CPU pathway and service-assigned audit storage. Establish acceptance gates for downstream implementation without executing the experiment, creating final code or treating environment metadata as readiness certification. | {"provenance": {"acquisition_mode": "EXISTING", "creation_tool": "local", "parent_ids": ["RES_0001"], "source_uri": "results/final-demo/3139fbc73dbf432da21fb22656440f37/operator-inputs/cpu_environment.json"}, "reference": "results/final-demo/3139fbc73dbf432da21fb22656440f37/data/shared/d562cb3a1f1faeef5b953c497fb1dbb982777c061be71e8682448c4bae5be078.json", "sha256": "d562cb3a1f1faeef5b953c497fb1dbb982777c061be71e8682448c4bae5be078", "source": "Operator resource_catalog; cpu_environment.json and FEAS_0003 version 1 resource-access assessment."} |

- **Readiness:** READY_0001: EXP_0001 v1 — REPAIR
- **Four gates:** {"quality_readiness": false, "resource_readiness": false, "scientific_readiness": false, "technical_readiness": false}
- **Failed checks / warnings:** ["RES_0001 version 1: deterministic target_leakage check failed and remains unresolved.", "RES_0001 version 1: independent verification of all four rows, exact fields, finite nonboolean numbers, values and supplied order is not demonstrated by the bounded summaries.", "RES_0001 version 1 and RES_0002 version 1: prediction-facing target isolation, including exclusion of whole-row and source-file access, is unestablished.", "RES_0002 version 1: audit_output_location is descriptive text rather than a resolved, accessible, immutable experiment-bound storage location with complete-record support.", "RES_0002 version 1: actual downstream worker binding and scientifically faithful transformation, scoring, matching and evaluation contracts are not established.", "RES_0002 version 1: current approval binding and enforceability of remaining cost and runtime limits are unestablished.", "RES_0001: target_leakage — Forbidden input fields []; 1 rows directly encode target label", "Deterministic file, hash, parsing, schema and duplicate checks passed; these do not establish scientific readiness or execution isolation.", "The constructed four-row census can support only the approved finite-fixture claim, not population efficacy, statistical power, realistic deployment frequency or measured model performance.", "The restricted offline worker is explicitly not an OS sandbox; its profile label does not demonstrate the prediction/scorer visibility boundary.", "Actual billing, elapsed preparation time, remaining authorization and license metadata are unknown.", "No experiment implementation, transformation, scoring or outcome evaluation was performed in this audit.", "This is a prospective preparation plan, not a completed validation, independent readiness decision or resource approval. No resources have been created or independently inspected by this response.", "Catalog and feasibility statements report availability. File hashes, actual worker binding, target isolation, complete audit storage and downstream strict-direction evaluation still require independent acceptance before implementation release.", "The concrete audit output path is service-assigned and is not supplied in the catalog. No audit result exists in this plan; the manifest description must be resolved and access established by the service.", "Actual billing and preparation runtime remain unknown, not zero. APKT_0003 acknowledges unknown billing and authorizes caps of 20 USD and 20 minutes; current remaining limits must govern subsequent work.", "The restricted offline worker is explicitly not an OS sandbox. Logical separation must not be mistaken for demonstrated target isolation.", "The deliberately constructed four-row fixture is adequate only for its finite evaluand. Mechanical validity does not establish population validity, realistic deployment frequencies or clipping efficacy.", "Only approved existing catalog resources are used. No downloads, generation, external model calls, package installation or new hardware are requested; no preparation credential is required.", "Any failed acceptance gate must stop implementation release and be reported to Planner. Criteria may not be relaxed, rows substituted or the harm comparison replaced with the charter benefit comparison."]

## Implementation and Code Audit

No implementation recorded.

## Experiment Results

The following are execution records and measurements, separate from scientific assessments.

No experiment executed yet. No result fields are inferred.

## Scientific Analysis

Historical versions are retained. A recorded PASS is distinct from current eligibility; the latter requires fresh artifact and scientific pins.

No scientific analysis recorded. Execution alone does not establish hypothesis support.

## Adaptive Decisions

### ROUND_0001

- **Start / end UTC:** 2026-10-04T09:50:11.004595+00:00 / 2026-10-04T09:50:55.837753+00:00
- **Parent / trigger:** {"parent_analysis_id": null, "parent_round": null, "parent_run_id": null, "trigger_decision": "DEC_0002"}
- **Recorded result boundary:** {"decision_id": "DEC_0002", "round_id": "ROUND_0001", "work_decision": "DEC_0002"}
- **Experiments / evidence / hypotheses:** {"evidence_ids": ["EVID_0001", "EVID_0002"], "experiment_ids": [], "hypotheses": [], "local_evidence_inspections": []}
- **Decisions in round:** ["DEC_0003"]

### ROUND_0002

- **Start / end UTC:** 2026-10-04T09:51:20.024828+00:00 / 2026-10-04T09:52:14.997839+00:00
- **Parent / trigger:** {"parent_analysis_id": null, "parent_round": "ROUND_0001", "parent_run_id": null, "trigger_decision": "DEC_0003"}
- **Recorded result boundary:** {"decision_id": "DEC_0003", "round_id": "ROUND_0002", "work_decision": "DEC_0003"}
- **Experiments / evidence / hypotheses:** {"evidence_ids": ["EVID_0003", "EVID_0004", "EVID_0005"], "experiment_ids": [], "hypotheses": [], "local_evidence_inspections": []}
- **Decisions in round:** ["DEC_0005"]

### ROUND_0003

- **Start / end UTC:** 2026-10-04T09:57:19.492669+00:00 / 2026-10-04T09:58:38.045388+00:00
- **Parent / trigger:** {"parent_analysis_id": null, "parent_round": "ROUND_0002", "parent_run_id": null, "trigger_decision": "DEC_0005"}
- **Recorded result boundary:** {"decision_id": "DEC_0005", "round_id": "ROUND_0003", "work_decision": "DEC_0005"}
- **Experiments / evidence / hypotheses:** {"evidence_ids": [], "experiment_ids": [], "hypotheses": ["HYP_0001", "HYP_0002"], "local_evidence_inspections": []}
- **Decisions in round:** ["DEC_0006"]

### ROUND_0004

- **Start / end UTC:** 2026-10-04T09:58:56.313924+00:00 / in progress
- **Parent / trigger:** {"parent_analysis_id": null, "parent_round": "ROUND_0003", "parent_run_id": null, "trigger_decision": "DEC_0006"}
- **Recorded result boundary:** UNKNOWN
- **Experiments / evidence / hypotheses:** {"evidence_ids": [], "experiment_ids": ["EXP_0001"], "hypotheses": [], "local_evidence_inspections": []}
- **Decisions in round:** ["DEC_0007", "DEC_0008", "DEC_0010"]

### DEC_0002 — GATHER_EVIDENCE

- **Timestamp UTC:** 2026-10-04T09:50:11.002739Z
- **Planner rationale / unresolved uncertainty:** No supporting evidence or reviewed hypothesis exists. Request one focused methods check, with a verifiable source, on when clipping to [0,1] cannot increase absolute error and how out-of-range targets invalidate that guarantee. This resolves the target-domain prerequisite that could change whether clipping is defensible and informs selection of the single frozen cohort. Avoid a broad literature survey; do not treat background evidence as measured fixture outcomes or evidence of AI-model efficacy.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** []
- **Actions actually executed:** ["EVENT_0014: GATHER_EVIDENCE (DEC_0002)"]

### DEC_0003 — GATHER_EVIDENCE

- **Timestamp UTC:** 2026-10-04T09:51:20.023556Z
- **Planner rationale / unresolved uncertainty:** EVID_0001 and EVID_0002 provide only forecasting and calibration background; the requested clipping/absolute-error prerequisite remains unanswered. Request one narrow methods verification of interval projection under absolute loss, documenting the bounded-target assumption and whether the guarantee fails for out-of-range targets. This follow-up addresses the prior retrieval's specific gap rather than repeating its forecasting evidence. Resolving that gap could distinguish conditionally defensible clipping from an unsupported general claim and inform the single frozen-cohort selection. Do not execute an experiment or calculate fixture outcomes.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["DEC_0002", "EVID_0001", "EVID_0002"]
- **Actions actually executed:** ["EVENT_0032: GATHER_EVIDENCE (DEC_0003)"]

### DEC_0005 — GENERATE_HYPOTHESES

- **Timestamp UTC:** 2026-10-04T09:57:19.490727Z
- **Planner rationale / unresolved uncertainty:** Two evidence rounds produced only indirect, abstract-level background; none establishes scalar-clipping efficacy under absolute error or validates the target range. Repeating that retrieval is unlikely to resolve the gap. Request two falsifiable, domain-conditional hypotheses using the supplied bounded and range_shift cohorts and the fixed all-four-row MAE comparison. Label anticipated effects as inference, not publication evidence or measured results, and make the target-domain assumptions explicit for subsequent Critic review. This identifies a discriminating test of whether clipping is defensible only when its range matches the targets, without executing an experiment or claiming general AI efficacy.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["PROJECT_AUTOLAB_DEMO", "DEC_0003", "EVID_0003", "EVID_0005"]
- **Actions actually executed:** ["EVENT_0051: GENERATE_HYPOTHESES (DEC_0005)"]

### DEC_0006 — DESIGN_EXPERIMENT

- **Timestamp UTC:** 2026-10-04T09:58:56.311952Z
- **Planner rationale / unresolved uncertainty:** Select HYP_0002 version 1, which has an exact-version PASS review. HYP_0001 predicts bounded-cohort MAE falling from 0.175 to 0.075; HYP_0002 predicts range_shift MAE rising from 0.075 to 0.175. These are prospective fixture deductions, not measurements, and retrieved literature provides only indirect background. The range_shift comparison more directly examines the charter's unresolved target-domain limitation: whether clipping remains defensible when its interval excludes targets. Request the smallest supported design: freeze the four supplied range_shift rows before approval, compare identity versus clipping on all four matched samples, and use only mean_absolute_error. Distinguish support for the harm hypothesis from intervention benefit. Execution would verify reproducibility and implementation, not discover general efficacy; a reviewed increase would support rejecting clipping for this frozen cohort, while numerical disagreement would require protocol checking. Retain HYP_0001 as an untested alternative. This action authorizes design only; execution requires fresh exact-version human approval and must respect the one-experiment limit.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["HYP_0002"]
- **Actions actually executed:** ["EVENT_0065: ADAPTIVE_SPECIALIST_FAILED (DEC_0006)", "EVENT_0079: ADAPTIVE_CONTROL_RETURNED (DEC_0006)"]

### DEC_0007 — SELECT_EXPERIMENT

- **Timestamp UTC:** 2026-10-04T10:11:10.730586Z
- **Planner rationale / unresolved uncertainty:** Select CAND_0001 version 2, PASS-reviewed by ERREV_0005 and aligned with HYP_0002 version 1. Its predicted MAE increase from 0.075 to 0.175 is a prospective fixture deduction, not a measurement. This four-row matched comparison is the smallest permitted test of reproducible protocol fidelity when the clipping interval excludes targets; confirmed harm would support HYP_0002 while making clipping indefensible for this frozen cohort. CAND_0002 version 2 remains BLOCK-reviewed: bounded targets cannot test the selected range_shift hypothesis, and the one-experiment cap prevents later repair. Preserve that alternative and its blocker. Freeze the supplied range_shift rows unchanged before approval, with scorer-only targets and complete matched aggregation. Selection authorizes no execution: readiness must verify the strict higher-error hypothesis comparison separately from clipping benefit, existing capabilities, audit support, and cost/runtime fit within the remaining limits; fresh exact-version human approval is required. Stop if prerequisites fail. Any numerical disagreement requires auditing before scientific interpretation; no population or AI-model efficacy inference is warranted.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["CAND_0001"]
- **Actions actually executed:** ["EVENT_0085: EXPERIMENT_SELECTED (EXP_0001)"]

### DEC_0008 — PREPARE_RESOURCES

- **Timestamp UTC:** 2026-10-04T10:43:40.118135Z
- **Planner rationale / unresolved uncertainty:** Prepare only the approved frozen four-row range_shift resource for EXP_0001 v1. CAND_0001 v2 has an exact-version PASS; the bounded alternative remains BLOCKED. EVENT_0107 authorizes preparation under FEAS_0003, with unknown billing acknowledged. Preserve the approved rows, ordering, scorer-only targets, and separation of hypothesis-harm criteria from charter-benefit criteria. This smallest necessary step resolves resource reproducibility and protocol compatibility, not clipping efficacy: no measured outcomes exist yet. Failure would block the charter comparison rather than justify a substitute cohort. Preserve PROJECT_AUTOLAB_DEMO as the source and PROJECT_AUTOLAB_DEMO_COMPLETION_01 as the linked authorization; respect the approved $20 and 20-minute limits within its remaining window. Do not implement or execute.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["PROJECT_AUTOLAB_DEMO", "PROJECT_AUTOLAB_DEMO_COMPLETION_01", "EXP_0001", "CAND_0001", "ERREV_0005", "HYP_0002", "FEAS_0003", "EVENT_0107"]
- **Actions actually executed:** ["EVENT_0115: PREPARE_RESOURCES (DEC_0008)"]

### DEC_0010 — PREPARE_RESOURCES

- **Timestamp UTC:** 2026-10-04T10:47:35.898469Z
- **Planner rationale / unresolved uncertainty:** Resume PPLAN_0001 for approved EXP_0001 v1: a preparation plan exists, but no registered resource manifest is supplied. Materialize and register only the four frozen range_shift rows, preserving their values and order. This is unfinished preparation, not a repeat experiment. CAND_0001 v2 passed review; the bounded alternative remains blocked. The smallest useful next step resolves whether the preregistered inputs can be faithfully prepared for independent readiness review; any mismatch must block progression rather than prompt cohort substitution. EVENT_0124 provides current exact-version approval, and the linked completion authorization preserves the original science. No measured outcome exists yet, and unknown billing remains acknowledged.
- **Expected information gain (recorded advisory score):** UNKNOWN
- **Context IDs:** ["EXP_0001", "PPLAN_0001", "CAND_0001", "ERREV_0005", "FEAS_0004", "EVENT_0124", "PROJECT_AUTOLAB_DEMO_COMPLETION_01"]
- **Actions actually executed:** ["EVENT_0138: ADAPTIVE_SPECIALIST_FAILED (DEC_0010)"]

## Research Lineage

Question (PROJECT_AUTOLAB_DEMO)

- EVID_0001 → SRC_0001
- EVID_0002 → SRC_0001
- EVID_0003 → SRC_0002
- EVID_0004 → SRC_0001
- EVID_0005 → SRC_0001

- Evidence [] / contradictory [] → HYP_0001 v1

- Evidence [] / contradictory [] → HYP_0002 v1

- DEC_0002 GATHER_EVIDENCE
- DEC_0003 GATHER_EVIDENCE
- DEC_0005 GENERATE_HYPOTHESES
- DEC_0006 DESIGN_EXPERIMENT
- DEC_0007 SELECT_EXPERIMENT
- DEC_0008 PREPARE_RESOURCES
- DEC_0010 PREPARE_RESOURCES

## Acceleration / Process Telemetry

| Recorded counter | Value |
| --- | --- |
| completed_runs | 0 |
| deep_evidence_records | 5 |
| experiment_candidates_considered | 2 |
| experiments_executed | 0 |
| human_approvals | 2 |
| hypotheses_considered | 2 |
| papers_screened | 7 |
| pending_run_records | 0 |
| planner_decisions | 7 |
| revisions | 2 |

| Recorded durations (seconds) | Values |
| --- | --- |
| analysis | [] |
| approval_waiting | [null, null, 0.004384, 0.004621] |
| evidence_to_hypothesis | 416.925306 |
| execution | [] |
| hypothesis_to_experiment_spec | 797.97109 |
| implementation | [] |
| preparation | [235.806817] |
| question_to_first_evidence | 232.032648 |
| result_to_decision | [] |

Recorded timestamps only; stage pairs match their scientific scope; approval wait ends at the first approval of the exact packet; result-to-decision ends at the first following PI decision; missing stays unknown; no human baseline or acceleration claim

Counters include imported historical records where present. Run attempts are counted separately from scientific conclusions. No measured human comparison baseline is recorded.

- **Known actual spend USD:** 0.0
- **Recorded estimates USD (separate from actual):** 0.0
- **Remaining allocation after known actuals USD:** 20.0
- **Unknown actual cost IDs:** ["COST_0001", "COST_0002", "COST_0003", "COST_0004", "COST_0005"]

| Cost ID | Category / experiment | Recorded estimate USD | Actual USD |
| --- | --- | --- | --- |
| COST_0001 | Remaining Omnigent reasoning calls; billing unavailable / EXP_0001 | 0.0 | 0.0 |
| COST_0002 | Remaining Omnigent reasoning calls; billing unavailable / EXP_0001 | 0.0 | 0.0 |
| COST_0003 | Remaining Omnigent reasoning calls; billing unavailable / EXP_0001 | 0.0 | 0.0 |
| COST_0004 | Remaining Omnigent reasoning calls; billing unavailable / EXP_0001 | 0.0 | 0.0 |
| COST_0005 | resource preparation estimate / EXP_0001 | 0.0 | 0.0 |

## Limitations and Open Questions

- Condition-dependent ordering, state or computational allowances.
- Swapped condition labels, scoring original rather than transformed predictions, or using a denominator other than four.
- Selecting rows or redefining the clipping interval after results.
- Treating intentional out-of-range targets as data errors or assuming every compact target domain is [0,1].
- Using the charter's benefit comparison to classify support for the harm hypothesis.
- Presenting constructed scalar outputs as measured AI-model answers.
- READY_0001: REPAIR
- RES_0001 version 1: deterministic target_leakage check failed and remains unresolved.
- RES_0001 version 1: independent verification of all four rows, exact fields, finite nonboolean numbers, values and supplied order is not demonstrated by the bounded summaries.
- RES_0001 version 1 and RES_0002 version 1: prediction-facing target isolation, including exclusion of whole-row and source-file access, is unestablished.
- RES_0002 version 1: audit_output_location is descriptive text rather than a resolved, accessible, immutable experiment-bound storage location with complete-record support.
- RES_0002 version 1: actual downstream worker binding and scientifically faithful transformation, scoring, matching and evaluation contracts are not established.
- RES_0002 version 1: current approval binding and enforceability of remaining cost and runtime limits are unestablished.
- RES_0001: target_leakage — Forbidden input fields []; 1 rows directly encode target label
- EVENT_0113 (historical blocker): Preparation stopped before any resource action
- Actual cost UNKNOWN: COST_0001, COST_0002, COST_0003, COST_0004, COST_0005

## References

### SRC_0001

- **Title:** Calibrated Probabilistic Forecasts for Arbitrary Sequences
- **Authors:** ["Charles T. Marx", "Volodymyr Kuleshov", "Stefano Ermon"]
- **Year:** 2024
- **DOI:** 10.48550/arxiv.2409.19157
- **URL:** https://pubmed.ncbi.nlm.nih.gov/41815873
- **Provider:** openalex
- **Other stored identifiers:** {"arxiv_id": "2409.19157", "pdf_url": "https://arxiv.org/pdf/2409.19157v2", "provider_id": "https://openalex.org/W7135156094"}

### SRC_0002

- **Title:** Image Restoration by Projection onto Convex Sets with Particle Swarm Parameter Optimization
- **Authors:** ["Abdolreza Rashno", "Sadegh Fadaei"]
- **Year:** 2023
- **DOI:** 10.5829/ije.2023.36.02b.18
- **URL:** http://dx.doi.org/10.5829/ije.2023.36.02b.18
- **Provider:** openalex
- **Other stored identifiers:** {"pdf_url": "https://www.ije.ir/article_163040_f046387e3792dae94db6634d839214e4.pdf", "provider_id": "https://openalex.org/W4313730998"}
