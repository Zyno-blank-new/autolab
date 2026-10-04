"""Load a local key without displaying it; isolate Omnigent's runtime files."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REASONING_MODEL = "gpt-6.1-sol"

def configure() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    state = str(PROJECT_ROOT / ".omnigent")
    os.environ.setdefault("OMNIGENT_CONFIG_HOME", state)
    os.environ.setdefault("OMNIGENT_DATA_DIR", state)
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
    # Ad-hoc CLI calls also use an explicit model, rather than a catalog
    # default that can drift. Agent YAML and explicit CLI overrides win.
    os.environ.setdefault("OMNIGENT_MODEL", DEFAULT_REASONING_MODEL)


def ledger_path() -> Path:
    """Return the default local ledger path or an explicit environment override."""
    configured = os.environ.get("AUTOLAB_LEDGER_PATH")
    return Path(configured).expanduser() if configured else PROJECT_ROOT / "research_state" / "autolab.db"
