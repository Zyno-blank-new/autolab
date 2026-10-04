"""Same paid evidence integration smoke with actual PI decisions on both sides."""
import asyncio
from autolab.evidence_integration_smoke import smoke

if __name__ == "__main__":
    asyncio.run(smoke(with_planner=True))
