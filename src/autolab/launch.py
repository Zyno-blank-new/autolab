"""Launch the official CLI with the project's environment loaded."""
import os
import sys
from pathlib import Path
from autolab.config import configure

def main() -> None:
    configure()
    cli = Path(sys.executable).parent / "omnigent"
    os.execv(str(cli), [str(cli), *sys.argv[1:]])

if __name__ == "__main__":
    main()
