from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import answer_question
from app.data_loader import load_ticket_csv, sample_dataset_path
from app.theme_discovery import add_theme_column

EVAL_FILE = ROOT / "evals" / "supportsense_eval_questions.csv"
OUTPUT_FILE = ROOT / "outputs" / "eval_results.csv"


def main() -> None:
    df = add_theme_column(load_ticket_csv(sample_dataset_path()))
    rows = []

    with EVAL_FILE.open() as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            response = answer_question(item["question"], df)
            ticket_ids = response.get("ticket_ids", [])
            passed = (
                response.get("method") == item["expected_method"]
                and len(ticket_ids) >= int(item["minimum_ticket_ids"])
            )
            rows.append(
                {
                    "eval_id": item["eval_id"],
                    "question": item["question"],
                    "expected_method": item["expected_method"],
                    "actual_method": response.get("method"),
                    "ticket_ids": ", ".join(ticket_ids),
                    "passed": passed,
                }
            )

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with OUTPUT_FILE.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    passed_count = sum(1 for row in rows if row["passed"])
    print(f"{passed_count}/{len(rows)} evals passed")
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
