"""Run the source checkout without installing packages or contacting the network."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from cfd_review.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
