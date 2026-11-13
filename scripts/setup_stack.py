"""Generate .env.compose.local without modifying the application's existing .env."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.deployment.config import configure_stack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".env.compose.local")
    args = parser.parse_args()
    try:
        path = configure_stack(args.model_dir, args.model_sha256, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Setup failed: {exc}\n")
    print(f"Verified the GGUF and created {path.name} with private permissions. No services started.")


if __name__ == "__main__":
    main()
