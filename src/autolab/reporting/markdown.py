"""Deterministic Markdown, with observations and interpretations kept distinct."""
import html
import json


def text(value):
    if value is None:
        return 'UNKNOWN'
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    value = html.escape(str(value), quote=False)
    return value.replace('\\', '\\\\').replace('`', '\\`').replace('|', '\\|').replace('\n', '<br>')


def render_markdown(view, *, generated_at, ledger_context):
    lines = ['# AutoLab Research Report', '',
        'This report separates canonical observations from recorded scientific interpretation. '
        'Assessments describe their stated scope; they are not statistical proof.', '']
    def section(title):
        lines.extend(['## ' + title, ''])
    def field(label, value):
        lines.append(f'- **{label}:** {text(value)}')
    def items(values, empty='None recorded.'):
        lines.extend(['- ' + text(x) for x in values] or [empty])
        lines.append('')
    def sub(title):
        lines.extend(['### ' + text(title), ''])
    def table(headers, rows):
        lines.append('| ' + ' | '.join(headers) + ' |')
        lines.append('| ' + ' | '.join('---' for _ in headers) + ' |')
        lines.extend('| ' + ' | '.join(text(c) for c in row) + ' |' for row in rows)
        lines.append('')
    c = view['charter']
    section('Project Summary')
    for label, value in [('Project ID', view['project_id']), ('Research question', c['research_question']),
        ('Objective', view['scope']['effective_objective']), ('Status', view['state']),
        ('Stopped', view['stopped']), ('Rounds', f"{view['round_count']} / {view['limits'].get('max_rounds', 'unconfigured')}"),
        ('Generated timestamp (UTC)', generated_at), ('Ledger context', ledger_context),
        ('Ledger snapshot SHA-256', view['ledger_fingerprint'])]:
        field(label, value)
    lines.append('')
    if view['runs']:
        table(['Run / exact experiment', 'Recorded metrics (IDs)', 'Latest recorded assessment (ID/version)'],
            [(f"{r['run_id']} / {r['experiment_id']} v{r['experiment_version']}",
              '; '.join(f"{m['metadata'].get('condition', 'unspecified')} {m['metric_name']} = {m['metric_value']} ({m['metric_id']})" for m in r['metrics']) or 'No metrics recorded',
              next((f"{a['hypothesis_assessment']} ({a['analysis_id']} v{a['version']})" for a in reversed(view['analyses']) if a['run_id'] == r['run_id']), 'No analysis'))
             for r in view['runs']])
    section('Research Charter')
    for label, key in [('Title', 'title'), ('Question', 'research_question'), ('Original objective', 'objective'),
        ('Primary outcome', 'primary_outcome'), ('Success criteria', 'success_criteria'), ('Constraints', 'constraints'),
        ('Budget allocation USD', 'budget_usd'), ('Time limit minutes (0 = unconfigured)', 'max_runtime_minutes'),
        ('Stop conditions', 'stop_conditions')]:
        field(label, c[key])
    if view['authorized_scope']:
        scope = view['authorized_scope']
        field('Explicit human-authorized linked charter', scope['project_id'])
        field('Linked objective', scope['objective'])
        field('Linked constraints', scope['constraints'])
        field('Linked budget / time', f"{scope['budget_usd']} USD / {scope['max_runtime_minutes']} minutes")
        lines.extend(['', 'The original scientific records retain their original project identity; the linked charter is an explicit authorized scope.'])
    lines.append('')
    section('Evidence Review')
    for e in view['evidence']:
        sub(e['evidence_id'] + ' → ' + e['source_id'])
        field('Recorded claim', e['claim'])
        field('Supporting publication text', e['supporting_text'] or 'Not recorded')
        field('Location', e['location'])
        field('Tags', e['tags'])
        support = [f"{h['hypothesis_id']} v{h['version']}" for h in view['hypotheses'] if e['evidence_id'] in h['supporting_evidence_ids']]
        contradiction = [f"{h['hypothesis_id']} v{h['version']}" for h in view['hypotheses'] if e['evidence_id'] in h['contradicting_evidence_ids']]
        field('Supporting relationship', support or 'No relationship recorded')
        field('Contradictory relationship', contradiction or 'No relationship recorded')
        lines.append('')
    if not view['evidence']:
        lines.extend(['No literature evidence recorded. Local measurements are reported under Experiment Results.', ''])
    for inspection in view['local_inspections']:
        field('Local result inspection', inspection['event_id'])
        field('Recorded inspection', {k: v for k, v in inspection['inspection'].items() if k != 'observations'})
        lines.append('')
        if inspection['inspection'].get('observations'):
            table(['Condition', 'Sample', 'Observed outputs', 'Execution status'],
                [(o.get('condition'), o.get('sample_id'), o.get('outputs'), o.get('status'))
                 for o in inspection['inspection']['observations']])
    section('Hypotheses')
    for h in view['hypotheses']:
        sub(f"{h['hypothesis_id']} v{h['version']}")
        for label, value in [('Statement', h['statement']), ('Rationale', h['rationale']),
            ('Falsifiable prediction', h['falsifiable_prediction']), ('Supporting evidence IDs', h['supporting_evidence_ids']),
            ('Contradicting evidence IDs', h['contradicting_evidence_ids']), ('Canonical status', h['status']),
            ('Planner disposition', h['disposition'] or 'No disposition recorded')]:
            field(label, value)
        review = h['review']
        field('Scientific critique', f"{review['review_id']} {review['verdict']}" if review else 'Not reviewed')
        lines.append('')
    if not view['hypotheses']:
        lines.extend(['No hypothesis recorded.', ''])
    section('Experimental Program')
    if view['candidates']:
        table(['Candidate/version', 'Hypothesis/version', 'Approach', 'Estimated USD'],
            [(f"{x['candidate_id']} v{x['version']}", f"{x['hypothesis_id']} v{x['hypothesis_version']}",
              x['approach'], x['estimated_cost_usd']) for x in view['candidates']])
    for e in view['experiments']:
        sub(f"{e['experiment_id']} v{e['version']} — {e['execution']}")
        for label, value in [('Hypothesis', f"{e['hypothesis_id']} v{e['hypothesis_version']}"),
            ('Objective', e['objective']), ('Experiment type', e['experiment_type']),
            ('Conditions / independent variables', e['independent_variables']), ('Controls / baseline', e['controls']),
            ('Dependent variables', e['dependent_variables']), ('Dataset requirements', e['dataset_requirements']),
            ('Primary metric', e['primary_metric']), ('Secondary metrics', e['secondary_metrics']),
            ('Success criterion', e['success_criteria']), ('Falsification criterion', e['falsification_criteria']),
            ('Assumptions', e['assumptions']), ('Potential confounders', e['potential_confounders'])]:
            field(label, value)
        selection = e['selection']
        field('Planner selection / follow-up lineage', selection or 'No selection recorded')
        review = e['review']
        field('Scientific review', f"{review['review_id']} {review['verdict']}" if review else 'Not reviewed')
        if e['execution'] in ('NOT EXECUTED', 'BLOCKED / NOT EXECUTED', 'PENDING / NOT EXECUTED'):
            lines.append('No measured result exists for this experiment version.')
        lines.append('')
    if not view['experiments']:
        lines.extend(['No experiment specified or executed yet.', ''])
    section('Human Decisions')
    if view['human_decisions']:
        table(['Event', 'Timestamp UTC', 'Decision / source', 'Exact scope / note'],
            [(e['event_id'], e['created_at'], e['event_type'] + ' / ' + e['actor'],
                {k: v for k, v in e['scope'].items() if v is not None}) for e in view['human_decisions']])
    else:
        lines.extend(['No explicit human decisions recorded.', ''])
    section('Resource Preparation and Readiness')
    if view['resources']:
        table(['Resource', 'Exact experiment', 'Purpose', 'Reference / SHA-256 / provenance'],
            [(r['resource_id'], f"{r['experiment_id']} v{r['experiment_version']}", r['purpose'],
              {'reference': r['path_or_uri'], 'sha256': r['checksum'], 'source': r['source'], 'provenance': r['provenance']})
             for r in view['resources']])
    else:
        lines.extend(['No resources registered.', ''])
    for r in view['readiness']:
        field('Readiness', f"{r['readiness_id']}: {r['experiment_id']} v{r['experiment_version']} — {r['verdict']}")
        field('Four gates', {k: r[k] for k in ('resource_readiness', 'technical_readiness', 'scientific_readiness', 'quality_readiness')})
        field('Failed checks / warnings', r['failed_checks'] + r['warnings'])
        lines.append('')
    section('Implementation and Code Audit')
    for i in view['implementations']:
        field('Implementation', f"{i['implementation_id']}: {i['experiment_id']} v{i['experiment_version']}")
        field('Implementation hash/version', i['code_version'])
        field('Source reference', i['code_path'])
        field('Registration status (not execution permission)', i['status'])
        field('Deterministic test receipt', i.get('test_status'))
        review = i['review']
        field('Independent code audit', f"{review['review_id']} {review['verdict']}" if review else 'No review recorded')
        field('Audit limitations / issues', review['issues'] + review['recommendations'] if review else 'Unknown')
        lines.append('')
    if not view['implementations']:
        lines.extend(['No implementation recorded.', ''])
    section('Experiment Results')
    lines.extend(['The following are execution records and measurements, separate from scientific assessments.', ''])
    for r in view['runs']:
        sub(f"{r['run_id']} — {r['status']} ({r['experiment_id']} v{r['experiment_version']})")
        field('Implementation', r['implementation_id'])
        field('Started / completed UTC', f"{r['started_at']} / {r['completed_at'] or 'not completed'}")
        field('Seed', r['random_seed'])
        field('Recorded duration seconds', r['duration_seconds'])
        field('Actual cost USD', r['cost_usd'])
        field('Recorded usage', r['usage'])
        field('Recorded environment / execution limitations', r['environment'])
        if r['error_message']:
            field('Execution error', r['error_message'])
        lines.append('')
        if r['metrics']:
            table(['Metric ID', 'Condition', 'Metric / role', 'Value', 'Unit', 'Sample denominator', 'Failure count'],
                [(m['metric_id'], m['metadata'].get('condition'), m['metric_name'] + ' / ' + str(m['metadata'].get('role', 'unspecified')),
                  m['metric_value'], m['unit'], m['metadata'].get('denominator'),
                  m['metadata'].get('failure_count', m['metadata'].get('support', {}).get('failed_samples')))
                 for m in r['metrics']])
        else:
            lines.extend(['No canonical metrics recorded for this run.', ''])
        for name, artifact in sorted(r['artifacts'].items()):
            if name.endswith('.log'):
                continue
            field('Artifact ' + name, artifact)
        lines.append('')
    if not view['runs']:
        lines.extend(['No experiment executed yet. No result fields are inferred.', ''])
    section('Scientific Analysis')
    lines.extend(['Historical versions are retained. A recorded PASS is distinct from current eligibility; '
        'the latter requires fresh artifact and scientific pins.', ''])
    for a in view['analyses']:
        sub(f"{a['analysis_id']} v{a['version']} — {a['hypothesis_assessment']}")
        for label, value in [('Exact result', f"{a['run_id']}; {a['experiment_id']} v{a['experiment_version']}"),
            ('Hypothesis', f"{a['hypothesis_id']} v{a['hypothesis_version']}"), ('Metric IDs', a['metric_ids']),
            ('Criteria evaluation', a['criteria_evaluation']), ('Recorded interpretation', a['interpretation']),
            ('Key findings', a['key_findings']), ('Unexpected findings', a['unexpected_findings']),
            ('Causal scope', a['causal_scope']), ('Generalization scope', a['generalization_scope']),
            ('Confounders', a['confounders']), ('Limitations', a['limitations']),
            ('Remaining uncertainty', a['remaining_uncertainties']), ('Current reviewed eligibility', a['current_reviewed'])]:
            field(label, value)
        review = a['review']
        field('Scientific Critic', f"{review['review_id']} {review['verdict']}" if review else 'Not reviewed')
        field('Critic issues / recommendations', review['issues'] + review['recommendations'] if review else [])
        lines.append('')
    if not view['analyses']:
        lines.extend(['No scientific analysis recorded. Execution alone does not establish hypothesis support.', ''])
    section('Adaptive Decisions')
    for r in view['rounds']:
        sub(r['round_id'])
        field('Start / end UTC', f"{r['started_at']} / {r['ended_at'] or 'in progress'}")
        field('Parent / trigger', {'parent_round': r.get('parent_round'), 'trigger_decision': r.get('trigger_decision'),
            'parent_run_id': r.get('parent_run_id'), 'parent_analysis_id': r.get('parent_analysis_id')})
        field('Recorded result boundary', r['result'])
        boundary = r.get('result') or {}
        result_analysis = next((a for a in view['analyses'] if a['analysis_id'] == boundary.get('parent_analysis_id')
            and a['version'] == boundary.get('parent_analysis_version')), None)
        if result_analysis:
            field('Result learned (recorded assessment)', f"{result_analysis['analysis_id']} v{result_analysis['version']}: {result_analysis['hypothesis_assessment']}")
            field('Unresolved uncertainty / limitations', result_analysis['remaining_uncertainties'] + result_analysis['limitations'])
        field('Experiments / evidence / hypotheses', {k: r[k] for k in ('experiment_ids', 'evidence_ids', 'hypotheses', 'local_evidence_inspections')})
        field('Decisions in round', r['decisions'])
        lines.append('')
    if not view['rounds']:
        lines.extend(['No explicit scientific rounds registered.', ''])
    for d in view['decisions']:
        sub(f"{d['decision_id']} — {d['action']}")
        field('Timestamp UTC', d['created_at'])
        field('Planner rationale / unresolved uncertainty', d['reason'])
        field('Expected information gain (recorded advisory score)', d['expected_information_gain'])
        field('Context IDs', d['required_context_ids'])
        actual = [e for e in view['milestones'] if e.get('decision_id') == d['decision_id'] and
            e['event_type'] in ('ADAPTIVE_CONTROL_RETURNED', 'ADAPTIVE_SPECIALIST_FAILED')]
        if d['action'] == 'SELECT_EXPERIMENT':
            actual += [e for e in view['milestones'] if e.get('decision_id') == d['decision_id'] and e['event_type'] == 'EXPERIMENT_SELECTED']
        field('Actions actually executed', [f"{e['event_id']}: {e['action'] or e['event_type']} ({e['target_id']})" for e in actual] or
            'No specialist completion receipt linked to this decision; selection/stop may occur at the decision boundary.')
        if d['action'] == 'STOP':
            field('Planner stop reason', d['reason'])
        lines.append('')
    section('Research Lineage')
    lines.append('Question (' + text(view['project_id']) + ')')
    lines.append('')
    items([f"{e['evidence_id']} → {e['source_id']}" for e in view['evidence']], 'No literature lineage recorded.')
    for h in view['hypotheses']:
        items([f"Evidence {h['supporting_evidence_ids']} / contradictory {h['contradicting_evidence_ids']} → {h['hypothesis_id']} v{h['version']}"])
    for r in view['research_history']:
        a = r['analysis']
        items([f"{r['hypothesis_id']} → {r['experiment_id']} v{r['version']} → {r['run_id']} → " +
            (f"{a['id']} v{a['version']} ({a['assessment']})" if a else 'no analysis') + '; lineage: ' + str(r['lineage'])])
    items([f"{d['decision_id']} {d['action']}" for d in view['decisions']], 'No Planner decisions recorded.')
    section('Acceleration / Process Telemetry')
    table(['Recorded counter', 'Value'], sorted(view['telemetry']['counts'].items()))
    table(['Recorded durations (seconds)', 'Values'], sorted(view['telemetry']['durations_seconds'].items()))
    lines.extend([text(view['telemetry']['timing_scope']), '',
        'Counters include imported historical records where present. Run attempts are counted separately from scientific conclusions. '
        'No measured human comparison baseline is recorded.', ''])
    b = view['budget']
    field('Known actual spend USD', b['actual_spent_usd'])
    field('Recorded estimates USD (separate from actual)', b['estimated_spent_usd'])
    field('Remaining allocation after known actuals USD', b['remaining_budget_usd'])
    field('Unknown actual cost IDs', b['unknown_actual_cost_ids'])
    lines.append('')
    if view['costs']:
        table(['Cost ID', 'Category / experiment', 'Recorded estimate USD', 'Actual USD'],
            [(c['cost_id'], c['category'] + ' / ' + str(c['experiment_id']), c['estimated_usd'], c['actual_usd'])
             for c in view['costs']])
    section('Limitations and Open Questions')
    items(view['limitations'], 'No scientific limitations recorded yet; an empty project establishes no finding.')
    section('References')
    for source in view['sources']:
        sub(source['source_id'])
        for label, key in [('Title', 'title'), ('Authors', 'authors'), ('Year', 'year'), ('DOI', 'doi'),
            ('URL', 'url'), ('Provider', 'provider'), ('Other stored identifiers', 'identifiers')]:
            field(label, source[key])
        lines.append('')
    if not view['sources']:
        lines.extend(['No SourceRecords; no bibliographic references invented.', ''])
    return '\n'.join(lines).rstrip() + '\n'
