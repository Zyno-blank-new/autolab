"""Structural/provenance checks; scientific merit remains Critic/PI work."""
import json
import re
from pydantic import TypeAdapter
from autolab import schemas as s
from autolab.hypotheses.validation import normalized_statement
from autolab.hypotheses.models import ReviewBatch
from .models import CandidateBatch, CandidateRevision, ExperimentDesignError

# Reuse the canonical spec's field definitions, without a duplicate spec schema
# or creating a preregistered object for unselected proposals.
SPEC_FIELDS = set(s.ExperimentSpec.model_fields) - {
    "experiment_id", "project_id", "hypothesis_id", "hypothesis_version", "title", "objective",
    "created_at", "version", "status", "estimated_cost_usd", "estimated_runtime_minutes", "expected_information_gain"}
EXTRA_DESIGN_FIELDS = {"evidence_ids", "metric_rationale", "sampling_strategy", "robustness_checks",
    "expected_result_patterns", "inconclusive_criteria", "follow_up_strategy", "planning_limitations"}
REQUIRED_DESIGN_FIELDS = {"experiment_type", "independent_variables", "dependent_variables", "controls",
    "dataset_requirements", "required_resources", "required_capabilities", "primary_metric",
    "success_criteria", "falsification_criteria", "potential_confounders", "assumptions",
    "metric_rationale", "sampling_strategy", "expected_result_patterns", "inconclusive_criteria"}
DETAIL_PLACEMENT = {"sampling_strategy": ("dataset_requirements", "sampling_strategy"),
    "metric_rationale": ("dependent_variables", "primary_metric_rationale"),
    "robustness_checks": ("controls", "robustness_checks"),
    "expected_result_patterns": ("success_criteria", "expected_result_patterns"),
    "inconclusive_criteria": ("falsification_criteria", "inconclusive_criteria"),
    "planning_limitations": ("dataset_requirements", "planning_limitations")}


def proposal_output_schema(model):
    """Constrain the canonical candidate's JSON proposal at the agent boundary.

    Scientific fields come directly from ExperimentSpec. This is a prompt schema,
    not another persistent record/model or an unselected preregistration.
    """
    schema = model.model_json_schema()
    properties = {k: v for k, v in s.ExperimentSpec.model_json_schema()['properties'].items() if k in SPEC_FIELDS}
    properties.update({k: {'type': 'string', 'minLength': 1} for k in
        ('metric_rationale', 'sampling_strategy', 'inconclusive_criteria', 'follow_up_strategy')})
    properties.update({k: {'type': 'array', 'items': {'type': 'string', 'minLength': 1}} for k in
        ('evidence_ids', 'robustness_checks', 'planning_limitations')})
    properties['expected_result_patterns'] = {'type': 'object', 'additionalProperties': False,
        'properties': {k: {'type': 'string', 'minLength': 1} for k in ('supported', 'contradicted', 'inconclusive')},
        'required': ['supported', 'contradicted', 'inconclusive']}
    schema['$defs']['ExperimentCandidate']['properties']['design'] = {
        'type': 'object', 'properties': properties, 'required': sorted(REQUIRED_DESIGN_FIELDS), 'additionalProperties': False}
    # The canonical record permits unknown scores for historical compatibility,
    # but validate_candidates already requires numeric advisory scores here.
    # Advertise that exact workflow contract instead of accepting null in the
    # model-facing schema and rejecting it after an otherwise valid response.
    candidate = schema['$defs']['ExperimentCandidate']
    for name in ('expected_information_gain', 'feasibility_score'):
        candidate['properties'][name] = next(option for option in candidate['properties'][name]['anyOf']
                                             if option.get('type') == 'number')
    candidate['properties']['major_risks']['minItems'] = 1
    candidate['required'] = sorted(set(candidate['required']) | {'expected_information_gain', 'feasibility_score', 'major_risks'})
    return schema


def evidence_references(value, context):
    visible = {e["id"] for e in context.evidence}
    mentioned = set(re.findall(r"\bEVID_[A-Za-z0-9_]+\b", json.dumps(value)))
    if not mentioned <= visible:
        raise ExperimentDesignError("Design/review cites missing, foreign, or unsupplied evidence")


def validate_design(design):
    if set(design) - SPEC_FIELDS - EXTRA_DESIGN_FIELDS:
        raise ExperimentDesignError("Unknown design fields; results and implementation are forbidden")
    if not REQUIRED_DESIGN_FIELDS <= set(design):
        raise ExperimentDesignError("Scientific design lacks preregistration fields")
    for name in SPEC_FIELDS & set(design):
        field = s.ExperimentSpec.model_fields[name]
        TypeAdapter(field.rebuild_annotation()).validate_python(design[name])
    for name in REQUIRED_DESIGN_FIELDS:
        value = design[name]
        if value is None or value == {} or value == [] or (isinstance(value, str) and not value.strip()):
            raise ExperimentDesignError(f"Scientific design requires meaningful {name}")
    for name in ("metric_rationale", "sampling_strategy", "inconclusive_criteria"):
        if not isinstance(design[name], str) or not design[name].strip():
            raise ExperimentDesignError(f"Design {name} must be a concise explanation")
    patterns = design["expected_result_patterns"]
    if not isinstance(patterns, dict) or set(patterns) != {"supported", "contradicted", "inconclusive"} or any(
        not isinstance(value, str) or not value.strip() for value in patterns.values()):
        raise ExperimentDesignError("Design must distinguish supported, contradicted, and inconclusive patterns")
    for name in ("required_resources", "required_capabilities", "potential_confounders", "assumptions", "secondary_metrics"):
        if name in design and any(not isinstance(x, str) or not x.strip() for x in design[name]):
            raise ExperimentDesignError("Design lists require nonempty descriptions")
    ids = design.get("evidence_ids", [])
    if not isinstance(ids, list) or any(not isinstance(x, str) or not re.fullmatch(r"EVID_[A-Za-z0-9_]+", x) for x in ids):
        raise ExperimentDesignError("Design evidence references must be EvidenceRecord IDs")
    forbidden = {"results", "observed_results", "measured_results", "run_id", "metric_value", "code", "code_path", "implementation"}
    def walk(value):
        if isinstance(value, dict):
            if set(value) & forbidden:
                raise ExperimentDesignError("Observed results or implementation cannot enter a scientific design")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(design)
    for source, (container, key) in DETAIL_PLACEMENT.items():
        if source in design and key in design[container] and design[container][key] != design[source]:
            raise ExperimentDesignError("Conflicting preregistration detail cannot be silently replaced")


def validate_candidates(batch, context, assignments, existing=(), *, revised=False):
    batch = (CandidateRevision if revised else CandidateBatch).model_validate(batch.model_dump())
    expected = {a["candidate_id"]: a["version"] for a in assignments}
    ids = [c.candidate_id for c in batch.candidates]
    if len(ids) != len(expected) or set(ids) != set(expected):
        raise ExperimentDesignError("Return every assigned candidate exactly once")
    seen = {}
    for old in existing:
        seen.setdefault(normalized_statement(old.objective + " " + old.approach), old.candidate_id)
    for candidate in batch.candidates:
        if (candidate.project_id != context.charter.project_id or candidate.hypothesis_id != context.hypothesis.hypothesis_id
            or candidate.hypothesis_version != context.hypothesis.version or candidate.version != expected[candidate.candidate_id]
            or candidate.status != s.ExperimentStatus.PROPOSED):
            raise ExperimentDesignError("Candidate must use assigned project, selected hypothesis/version, proposal identity/status")
        if len(candidate.model_dump_json()) > 18000:
            raise ExperimentDesignError("Candidate exceeds compact scientific proposal bound")
        if candidate.expected_information_gain is None or candidate.feasibility_score is None or not candidate.major_risks:
            raise ExperimentDesignError("Candidate needs advisory information gain, feasibility, and explicit major risks")
        validate_design(candidate.design)
        evidence_references(candidate.model_dump(mode="json"), context)
        key = normalized_statement(candidate.objective + " " + candidate.approach)
        if not key or (key in seen and seen[key] != candidate.candidate_id):
            raise ExperimentDesignError("Exact normalized candidate already considered")
        seen[key] = candidate.candidate_id
    return batch


def validate_reviews(batch, candidates, context, assignments):
    batch = ReviewBatch.model_validate(batch.model_dump())
    targets = {c.candidate_id: c.version for c in candidates}
    # A design-alignment critique may cite the actual candidate/hypothesis it
    # reviews. These are scientific artifact references, not new publications.
    visible = {e['id'] for e in context.evidence} | set(targets) | {context.hypothesis.hypothesis_id}
    expected = {a["target_id"]: a["review_id"] for a in assignments}
    if len(batch.reviews) != len(targets) or {r.target_id for r in batch.reviews} != set(targets):
        raise ExperimentDesignError("Critic must independently review each assigned candidate once")
    for review in batch.reviews:
        if (review.project_id != context.charter.project_id or review.review_id != expected[review.target_id]
            or review.target_type != "experiment_candidates" or review.target_version != targets[review.target_id]
            or review.review_type != "experiment" or review.reviewer_role != "critic"):
            raise ExperimentDesignError("Review must identify the exact assigned candidate version/project")
        if len(review.model_dump_json()) > 8000 or len(review.issues) > 8 or len(review.questions) > 5 or len(review.recommendations) > 5:
            raise ExperimentDesignError("Review exceeds compact bounds")
        if review.verdict != s.ReviewVerdict.PASS and not review.issues:
            raise ExperimentDesignError("Non-PASS review requires specific scientific issues")
        for issue in review.issues:
            if any(not isinstance(issue.get(k), str) or not issue[k].strip() for k in ("problem", "why_it_matters", "resolution")):
                raise ExperimentDesignError("Critic issues must explain problem, significance, and resolution")
            ids = issue.get("evidence_ids", [])
            if not isinstance(ids, list) or any(i not in visible for i in ids):
                raise ExperimentDesignError("Critic issue references unavailable evidence")
        evidence_references(review.model_dump(mode="json"), context)
    return batch


def validate_responses(batch, reviews, context, ledger):
    from autolab.hypotheses.validation import validate_evidence_ids
    expected = {(r.review_id, i) for r in reviews for i in range(len(r.issues))}
    actual = [(r.review_id, r.issue_index) for r in batch.responses]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ExperimentDesignError('Respond exactly once to every material design critique')
    visible = {e['id'] for e in context.evidence} | {c.candidate_id for c in batch.candidates} | {context.hypothesis.hypothesis_id}
    for response in batch.responses:
        if not set(response.evidence_ids) <= visible:
            raise ExperimentDesignError('Design response references unavailable scientific evidence')
        validate_evidence_ids([i for i in response.evidence_ids if i.startswith('EVID_')], context, ledger)
        if any(i not in response.evidence_ids for i in re.findall(r'\bEVID_[A-Za-z0-9_]+\b', response.reason)):
            raise ExperimentDesignError('Design response cites evidence outside its reference list')


def spec_from_candidate(candidate, experiment_id):
    validate_design(candidate.design)
    # Preserve proposal-only scientific details inside the existing canonical
    # JSON fields, so a downstream consumer of Spec alone sees the full contract.
    import copy
    fields = {k: copy.deepcopy(v) for k, v in candidate.design.items() if k in SPEC_FIELDS}
    for source, (container, key) in DETAIL_PLACEMENT.items():
        if source in candidate.design:
            fields[container][key] = copy.deepcopy(candidate.design[source])
    return s.ExperimentSpec(experiment_id=experiment_id, project_id=candidate.project_id,
        hypothesis_id=candidate.hypothesis_id, hypothesis_version=candidate.hypothesis_version,
        title=candidate.title, objective=candidate.objective,
        **fields,
        estimated_cost_usd=candidate.estimated_cost_usd, estimated_runtime_minutes=candidate.estimated_runtime_minutes,
        expected_information_gain=candidate.expected_information_gain)
