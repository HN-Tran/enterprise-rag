#!/usr/bin/env python3
"""Run RAG evaluation suite.

Usage:
    python scripts/evaluate.py --test-file tests/eval_cases.json
    python scripts/evaluate.py --test-file tests/eval_cases.json --output results/eval_2024.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from enterprise_rag.evaluation import EvaluationHarness, TestCase


def create_sample_test_file(path: Path) -> None:
    """Create a sample test cases file."""
    import json

    sample = {
        "test_cases": [
            {
                "query": "Was sind die Anforderungen der DSGVO?",
                "relevant_doc_ids": [],  # Fill in with actual doc IDs
                "expected_answer_contains": ["DSGVO", "Datenschutz"],
                "category": "compliance",
            },
            {
                "query": "Wie funktioniert die Authentifizierung?",
                "relevant_doc_ids": [],
                "expected_answer_contains": ["Authentifizierung"],
                "category": "security",
            },
        ],
        "_comment": "Add relevant_doc_ids based on your document corpus",
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, ensure_ascii=False)

    print(f"Created sample test file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG evaluation")
    parser.add_argument(
        "--test-file",
        type=Path,
        help="Path to test cases JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to save results JSON",
    )
    parser.add_argument(
        "--create-sample",
        action="store_true",
        help="Create a sample test cases file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show progress during evaluation",
    )

    args = parser.parse_args()

    if args.create_sample:
        sample_path = args.test_file or Path("tests/eval_cases.json")
        create_sample_test_file(sample_path)
        return

    if not args.test_file:
        parser.error("--test-file is required (or use --create-sample)")

    if not args.test_file.exists():
        print(f"Error: Test file not found: {args.test_file}")
        print("Use --create-sample to create a sample test file")
        sys.exit(1)

    # Run evaluation
    print(f"Loading test cases from: {args.test_file}")
    harness = EvaluationHarness()
    harness.add_test_cases_from_file(args.test_file)
    print(f"Loaded {len(harness.test_cases)} test cases")

    print("\nRunning evaluation...")
    results = harness.run(verbose=args.verbose)

    # Print summary
    print("\n" + results.summary())

    # Save results if output path provided
    if args.output:
        results.save(args.output)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
