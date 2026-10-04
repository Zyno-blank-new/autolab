"""Atomic project/ledger-scoped reports with an append-only generation receipt."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

from autolab import schemas as s
from autolab.config import PROJECT_ROOT
from autolab.orchestration.snapshot import load_snapshot
from .markdown import render_markdown
from .public import public
from .view import snapshot_fingerprint, view_snapshot


class ReportService:
    def __init__(self, ledger, *, root=None):
        self.ledger = ledger
        self.root = Path(root) if root else PROJECT_ROOT / 'reports'

    def generate(self, project_id, *, now=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', project_id):
            raise ValueError('Report project ID must contain only letters, numbers, underscores or hyphens.')
        now = now or s.utc_now()
        snapshot = load_snapshot(self.ledger, project_id)
        view = view_snapshot(snapshot, now=now)
        ledger_context = str(Path(self.ledger.database.path).resolve())
        ledger_key = hashlib.sha256(ledger_context.encode()).hexdigest()[:12]
        path = self.root / project_id / ledger_key / 'research_report.md'
        content = public(render_markdown(view, generated_at=now.isoformat(), ledger_context=public(ledger_context)))
        path.parent.mkdir(parents=True, exist_ok=True)
        event = s.EventRecord(event_id=self.ledger.next_id('EVENT'), project_id=project_id,
            event_type='REPORT_GENERATED', actor='report', target_type='projects', target_id=project_id,
            summary='Deterministic living research report generated from canonical project state',
            payload={'path': str(path.resolve()), 'generated_at': now.isoformat(),
                'ledger_context': ledger_context, 'snapshot_sha256': snapshot_fingerprint(snapshot),
                'report_sha256': hashlib.sha256(content.encode()).hexdigest()})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.research_report-', delete=False) as output:
                temporary = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            # No partially-written report. Concurrent scientific changes reject
            # publication; report receipts are excluded from the fingerprint.
            with self.ledger.database.transaction():
                if snapshot_fingerprint(load_snapshot(self.ledger, project_id)) != event.payload['snapshot_sha256']:
                    raise ValueError('Ledger changed while rendering; regenerate the report from current state.')
                self.ledger._insert(self.ledger.database.connection, event)
                os.replace(temporary, path)
                temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return public({'path': str(path.resolve()), 'project_id': project_id, 'state': view['state'],
            'rounds': view['round_count'], 'experiments': len(view['experiments']),
            'generation': event.payload, 'event_id': event.event_id})
