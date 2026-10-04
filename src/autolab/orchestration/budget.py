"""Known ledger costs and charter time limits; no predicted or invented spend."""
import math
from datetime import datetime
from .models import BudgetState, ProjectSnapshot, TimeState
from autolab.schemas import utc_now


def calculate_budget(snapshot: ProjectSnapshot) -> BudgetState:
    # Phase 2 defaults actual_usd to zero. Positive actuals are known spend;
    # an estimate-only row is explicitly unknown, not an inferred actual cost.
    unknown = [c.cost_id for c in snapshot.costs if c.actual_usd is None or c.metadata.get("actual_known") is False or
               (c.actual_usd == 0 and c.estimated_usd > 0 and c.metadata.get("actual_known") is not True)]
    actual = math.fsum(c.actual_usd for c in snapshot.costs if c.actual_usd is not None)
    estimated = math.fsum(c.estimated_usd for c in snapshot.costs)
    charter = snapshot.authorized_scope or snapshot.charter
    return BudgetState(initial_budget_usd=charter.budget_usd,
                       estimated_spent_usd=estimated, actual_spent_usd=actual,
                       remaining_budget_usd=max(0, charter.budget_usd-actual),
                       unknown_actual_cost_ids=unknown)


def calculate_time(snapshot: ProjectSnapshot, now: datetime | None = None) -> TimeState:
    now = now or utc_now()
    charter = snapshot.authorized_scope or snapshot.charter
    elapsed = max(0, (now-charter.created_at).total_seconds()/60)
    limit = charter.max_runtime_minutes
    return TimeState(created_at=charter.created_at, elapsed_minutes=elapsed,
                     remaining_minutes=max(0, limit-elapsed) if limit > 0 else None)
