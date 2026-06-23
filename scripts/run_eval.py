from __future__ import annotations

import argparse
from pathlib import Path

from app.main import build_container


def print_report(summary: dict[str, object], reports: list[dict[str, object]]) -> None:
    print("=== Eval Summary ===")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("\n=== Turn Results ===")
    for report in reports:
        status = "PASS" if report["passed"] else "FAIL"
        print(f"[{status}] {report['case_id']}#{report['turn_index']} | {report['question']}")
        print(
            f"  grounded={report['grounded']} citation_match={report['citation_match']} "
            f"section_match={report['section_match']} keyword_match={report['keyword_match']} "
            f"insufficient_match={report['insufficient_match']} grounded_match={report['grounded_match']}"
        )
        print(f"  top_citation={report['top_citation_file']} | {report['top_citation_section']}")
        print(f"  answer={str(report['answer'])[:220]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run QA acceptance eval against the current local knowledge base.")
    parser.add_argument(
        "--dataset",
        default="data/evals/knowledge_base_eval_cases.json",
        help="Path to evaluation dataset JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/evals/results",
        help="Directory to store timestamped evaluation reports.",
    )
    args = parser.parse_args()

    container = build_container()
    payload = container.evaluation_service.run(dataset_path=Path(args.dataset), output_dir=Path(args.output_dir))
    print_report(payload["summary"], payload["reports"])
    print(f"\nSaved report to: {payload['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
