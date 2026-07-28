from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from supportsense.evaluation import run_agent_evaluation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SupportSense production gates.")
    parser.add_argument(
        "--output",
        default="outputs/production-eval-results.json",
        help="JSON output path",
    )
    args = parser.parse_args()
    result = run_agent_evaluation()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))
    print(f"Evaluation {'passed' if result['passed'] else 'failed'}: {output}")
    return 0 if result["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
