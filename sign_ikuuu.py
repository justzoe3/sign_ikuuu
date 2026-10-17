"""Compatibility entry point for the standalone Actions project."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from run_actions import main
if __name__ == "__main__":
    sys.exit(main())
