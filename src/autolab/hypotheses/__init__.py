"""Evidence-aware proposals and bounded independent scientific review."""
from .service import HypothesisPipeline
from .models import HypothesisGenerationResult, HypothesisLimits

__all__ = ["HypothesisPipeline", "HypothesisGenerationResult", "HypothesisLimits"]
