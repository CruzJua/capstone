"""Print GGUF metadata and chat template without running inference."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.inference.gguf_metadata import summarize_gguf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gguf", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize_gguf(args.gguf), indent=4))


if __name__ == "__main__":
    main()
