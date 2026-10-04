# AutoLab

**One-liner:** An Omnigent-powered adaptive computational AI research lab that turns a question into auditable evidence, executable experiments, measured results and the next scientific decision, with human approval.

## Problem and solution

Research repeatedly crosses literature, hypotheses, experimental design, implementation, evaluation and next-step decisions. AutoLab coordinates this computational loop and stores its scientific memory in a SQLite Research Ledger. Each result can change the Planner's next action. Unsupported work can remain blocked; a scientific STOP is a valid outcome.

## Why Omnigent

Omnigent 0.16.0 invokes the PI / Planner and specialist Evidence, Hypothesis, Scientific Critic, Experiment Designer, Preparation, Readiness, Implementer, Code Auditor and Analyst roles through its actual local server and `openai-agents` harness. AutoLab surrounds those structured agent handoffs with deterministic validation and persistent memory. The experiment runner, metric computation and report renderer are deterministic Python components.

## How it works and what is adaptive

Question → evidence with provenance → falsifiable hypotheses and critique → candidate experiments and critique → Planner selection → feasibility and exact approval → preparation and independent readiness → implementation, tests and independent code audit → restricted deterministic execution → raw observations and metrics → analysis and independent critique → Planner reassessment.

The Planner can gather more evidence, revise hypotheses, select an informative test, request input or stop. It receives actual reviewed measurements, limitations and remaining resources. Follow-ups need new scientific contracts and fresh approval; no prompt forces another experiment for presentation purposes.

## Scientific rigor

Preregistered metrics and criteria, immutable scientific versions, exact-spec and implementation-scoped approvals, independent reviews, bounded repair/revision loops, artifact hashes, full denominators and independent metric recomputation. Semantic review is model-based and does not replace deterministic checks. Negative, inconclusive and blocked branches remain visible.

## Demo result and acceleration evidence

The current final-demo checkpoint has reviewed hypotheses/designs, exact test-human approval, prepared resources and a REPAIR readiness report. The attempted repair was rejected for changing the immutable required resource set. There is no implementation, experiment execution or measured result. The completed canonical demo report and observation export will be produced only after the gated integration passes. Submission readiness remains incomplete; consult [FINAL_AUDIT.md](FINAL_AUDIT.md). This is a deliberately tiny synthetic scalar-output guardrail study, not an evaluation of live tool-using agents or a publishable discovery.

[ACCELERATION_EVIDENCE.md](ACCELERATION_EVIDENCE.md) reports observed timestamps, bounded processing intervals, work counts and explicit test-human approval events. No human-equivalent baseline, wet-lab acceleration or universal speed multiplier was measured. The supportable claim is automation of the demonstrated reviewed computational loop while retaining human approval boundaries.

## Limitations

Current execution requires operator-adapted offline protocols and suitable resources. External providers affect live stages. Restricted workers are not a perfect OS sandbox. Four constructed rows cannot establish population efficacy, significance or deployment frequencies. Dollar billing is unknown. The historical empirical EXP_0001 remained BLOCKED because prerequisites were unresolved; the final demo never changes it. Wet-lab execution is unsupported.

## Run instructions

From the repository root:

```sh
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[test]'
cp .env.example .env
# Set OPENAI_API_KEY privately before real reasoning calls.
python -m autolab.prepare_demo
```

Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the exact extended integration commands and the two-minute offline judging path. The current Markdown export shows an explicitly incomplete earlier checkpoint; no completed observation JSON export exists. A new live integration requires provider access and can produce a different legal decision or fail. Tests: `python -m pytest -q` (offline). Final validation evidence: [FINAL_AUDIT.md](FINAL_AUDIT.md).

## Thirty-second pitch

“AutoLab is an Omnigent-powered adaptive computational AI research lab. A scientist supplies a question; specialist agents gather evidence, propose and critique hypotheses, design experiments, prepare resources, generate and audit code, and interpret real computed measurements. The reviewed result returns to a Planner that chooses what to do next—even stop. A persistent ledger records the evidence, versions, approvals and hashes. Humans retain consequential approval, while deterministic Python executes and verifies the experiment.”

## Approximately 100-word description

AutoLab runs an adaptive computational research loop through Omnigent. Its Planner coordinates specialists for evidence, hypotheses, scientific critique, experimental design, preparation, readiness, implementation, code audit and analysis. SQLite preserves scientific artifacts and decisions. Exact-version human approval and independent checks gate consequential execution. A restricted Python runner captures raw observations and computes preregistered metrics, which are independently recomputed before interpretation. Reviewed results inform the next legal Planner action, including STOP. The demonstration tests clipping on a frozen synthetic scalar-prediction cohort. It illustrates auditable scientific automation without claiming population efficacy, universal scientific execution or an unmeasured acceleration multiplier.

## Challenge alignment

| Dimension | Concrete evidence |
| --- | --- |
| Omnigent orchestration — 30% | Actual role invocations, Planner-selected routes, structured specialist handoffs and reviewed result returned to PI |
| Breakthrough potential — 25% | Automation across a computational loop, persistent scientific memory and adaptive experimental decisions |
| Discovery acceleration / learning — 20% | Timestamp/count receipts, deterministic execution and result-sensitive next choice; no invented baseline |
| Scientific rigor — 15% | Publication provenance, falsifiability, preregistration, independent review, raw measurements and calibrated limitations |
| Creativity / responsibility — 10% | Exact approval, bounded autonomy, blocked invalid alternatives and honestly blocked historical execution |

These are evidence mappings, not predicted scores.
