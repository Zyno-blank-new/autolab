"""Only explicit quantities and prices contribute costs; no pricing lookup."""
import math
from .models import (BudgetStatus as B, CostCategory, CostEstimate, CostInput,
                     EstimateRange, TimeStatus as T)


def estimate_cost(inputs, *, spec_estimate=None):
    categories = []
    for item in inputs:
        item = CostInput.model_validate(item.model_dump() if isinstance(item, CostInput) else item)
        unknown = []
        if item.unit_price_usd is None:
            unknown.append(f"{item.category}: unit price unknown")
        if item.units.maximum is None:
            unknown.append(f"{item.category}: total quantity upper bound unknown")
        values = {field: (getattr(item.units, field) * item.unit_price_usd
                         if getattr(item.units, field) is not None and item.unit_price_usd is not None else None)
                  for field in ("minimum", "expected", "maximum")}
        categories.append(CostCategory(category=item.category, estimate_usd=EstimateRange(**values),
            assumptions=item.assumptions + [f"Uses explicitly configured price per {item.unit}; not a current-price lookup."],
            unknown_drivers=unknown, confidence=item.confidence))
    if not categories:
        categories = [CostCategory(category="experiment pursuit", estimate_usd=EstimateRange(expected=spec_estimate),
            assumptions=["ExperimentSpec's advisory estimate only; no supporting prices/quantities configured."],
            unknown_drivers=["Preparation, implementation, execution and future agent-call costs are not fully priced."])]
    totals = {}
    for field in ("minimum", "expected", "maximum"):
        values = [getattr(c.estimate_usd, field) for c in categories]
        totals[field] = math.fsum(values) if all(v is not None for v in values) else None
    confidence = [c.confidence for c in categories]
    return CostEstimate(estimate_usd=EstimateRange(**totals), categories=categories,
        assumptions=[a for c in categories for a in c.assumptions],
        unknown_cost_drivers=[d for c in categories for d in c.unknown_drivers],
        confidence=min(confidence) if all(c is not None for c in confidence) else None)


def budget_status(estimate, remaining):
    if estimate.minimum is not None and estimate.minimum > remaining:
        return B.OVER_BUDGET
    if estimate.maximum is None:
        return B.UNKNOWN
    return B.WITHIN_BUDGET if estimate.maximum <= remaining else B.POSSIBLY_WITHIN_BUDGET


def time_status(estimate, remaining):
    if remaining is not None and estimate.minimum is not None and estimate.minimum > remaining:
        return T.OVER_TIME
    if estimate.maximum is None:
        return T.UNKNOWN
    return T.WITHIN_TIME if remaining is None or estimate.maximum <= remaining else T.AT_RISK
