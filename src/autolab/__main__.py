"""Preserve python -m autolab as the same thin CLI entry point."""
from .cli import main

raise SystemExit(main())
