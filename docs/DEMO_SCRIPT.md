# AutoLab: two-minute checkpoint demo

**The requested full end-to-end demo is INCOMPLETE.** This script presents the actual earlier checkpoint honestly. It demonstrates evidence, scientific proposals, approval, preparation and a failed readiness branch; it does not demonstrate execution, analysis or a result-sensitive next decision. Do not present it as a completed scientific loop.

Run from the repository root with `.venv` activated. The main path below needs no API call. Generated databases are ignored by Git; on another machine, the portable [DEMO_REPORT.md](DEMO_REPORT.md) shows this same incomplete earlier checkpoint. No completed observation receipt or `completed.json` exists.

## 0:00–0:20 — question

```sh
source .venv/bin/activate
CHECKPOINT_DB=results/final-demo/3139fbc73dbf432da21fb22656440f37/demo.db
autolab status --db "$CHECKPOINT_DB" --project PROJECT_AUTOLAB_DEMO
```

Say: “AutoLab is an Omnigent-powered adaptive computational AI lab. It coordinates literature, hypotheses, experiments, code, evaluation and deciding what to try next. This earlier run asks when clipping scalar predictions helps or harms. Its four predictions are deliberately synthetic, not answers from an evaluated AI model.”

## 0:20–0:55 — actual scientific work

Open [DEMO_REPORT.md](DEMO_REPORT.md), **Evidence Review**, **Hypotheses** and **Experimental Program**.

Say: “Real Omnigent agents retrieved publication abstracts with provenance, proposed two falsifiable hypotheses and compared two designs. Critics required a revision. The Planner selected the range-shift harm test; the bounded alternative remains blocked for not testing that selected hypothesis. Anticipated numerical values are prospective deductions, not measured results. Background papers do not establish clipping efficacy.”

## 0:55–1:30 — human boundary and independent failure

Show **Human Decisions** and **Resource Preparation and Readiness**.

Say: “The isolated audit explicitly recorded test-human approval of the exact packet. Preparation discovered additional risks, which went into a refreshed packet. Independent readiness returned REPAIR. A proposed repair changed the immutable resource set and was rejected. No implementation or experiment executed, and approval did not override the failure. The prediction/target equality false positive was fixed in code; the earlier review and remaining findings stay visible.”

## 1:30–1:50 — deterministic audit trail

```sh
python -m autolab.final_demo_audit --db "$CHECKPOINT_DB" --allow-partial
autolab report --db "$CHECKPOINT_DB" --project PROJECT_AUTOLAB_DEMO
```

Say: “These commands execute live locally. They validate provenance and regenerate a report from the ledger. The audit reports INCOMPLETE and zero recomputed metrics. Preparation and readiness ran through real Omnigent; execution, metrics and report rendering are deterministic components, but the experiment has not reached execution.”

Show [ACCELERATION_EVIDENCE.md](ACCELERATION_EVIDENCE.md): measured work and timing, missing stages explicit, no human baseline or speed multiplier.

## 1:50–2:00 — honest ending

Say: “AutoLab preserves scientific artifacts and refuses unsupported execution. This checkpoint demonstrates that boundary. The full demo still needs valid readiness, audited implementation, execution, reviewed analysis and the Planner’s result-sensitive decision.”

## Optional fresh live path and reset

```sh
python -m autolab.prepare_demo
LIVE_DB=$(python -c 'import json; print(json.load(open("results/final-demo/latest.json"))["db"])')
autolab continue --db "$LIVE_DB" --project PROJECT_AUTOLAB_DEMO --max-steps 1
```

Say: “This new Planner decision and any selected legal specialist work are executing now.” This makes real model calls, may take several minutes and can legally stop or fail. Each preparation creates a fresh charter-only namespace without deleting history. Do not resume terminal STOP or blindly repeat interrupted dispatches.

The explicit extended integration command is:

```sh
python -m autolab.final_e2e_integration_smoke --db "$LIVE_DB" --test-human
python -m autolab.final_demo_audit --db "$LIVE_DB" --export-docs
```

`--test-human` explicitly authorizes only an isolated automated test. It does not grant production authority or force scientific decisions/verdicts. Forty transport attempts, one experiment, a $20 allocation and charter time bounds apply; provider billing is UNKNOWN. The export command refuses incomplete integration. A successful future export produces `completed.json`, `DEMO_REPORT.md` and `DEMO_RECEIPT.json`; only then may a completed run be presented as such. Production approvals require explicit human action; exact audited implementation RUN scope remains a separate boundary.

## If live connectivity fails

State the failure and switch to the offline checkpoint commands above. If the ledger is unavailable, open the portable Markdown checkpoint. Do not substitute historical Phase 10/12 fixture results or prospective arithmetic for this project’s measurements. A completed end-to-end fallback is currently unavailable.
