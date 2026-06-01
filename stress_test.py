# stress_test.py
# Simple entry point – run from the project root:  python stress_test.py [--plot]

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api import stress_test

if __name__ == "__main__":
    plot = "--plot" in sys.argv
    stress_test(plot=plot)