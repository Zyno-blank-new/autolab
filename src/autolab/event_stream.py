"""Small public renderer of persisted project events, never prompts or reasoning."""
from pathlib import Path
from autolab.reporting.public import public


class EventStream:
    def __init__(self,project,path):
        self.project=project;self.path=Path(path);self.seen=set()
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if ' event=' in line: self.seen.add(line.rsplit(' event=',1)[1])

    def refresh(self,ledger):
        lines=[]
        for e in ledger.list_events(self.project):
            if e.event_id in self.seen: continue
            # No free-form payload/summary is rendered: it could contain source
            # text, prompts or a provider's untrusted response.
            action=e.payload.get('action') if e.event_type=='PLANNER_DECISION' else None
            stamp=e.created_at.astimezone().strftime('%H:%M:%S')
            line=public(f'[{stamp}] [{e.actor}] → {action or e.event_type} target={e.target_id or self.project} event={e.event_id}')
            lines.append(line);self.seen.add(e.event_id)
        if lines:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a') as f: f.write('\n'.join(lines)+'\n')
            for line in lines: print(line,flush=True)
        return lines
