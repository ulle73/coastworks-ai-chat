"""Keep the evaluation corpus reproducible and its reference labels resolvable."""

import hashlib
import json
from pathlib import Path


def test_eval_corpus_integrity_and_reference_coverage():
    pages = json.loads(Path("evals/corpus.json").read_text(encoding="utf-8"))
    cases = json.loads(Path("evals/questions.json").read_text(encoding="utf-8"))
    urls = {p["url"] for p in pages}
    assert len({c["id"] for c in cases}) == len(cases) >= 40
    assert {
        "exact",
        "paraphrase",
        "synonym",
        "followup",
        "specific",
        "distractor",
        "absent",
        "conflict",
        "injection",
    } <= {c["category"] for c in cases}
    for page in pages:
        assert hashlib.sha256(page["content"].encode()).hexdigest() == page["sha256"]
        assert page["captured_at"] == "2026-09-24"
    for case in cases:
        assert case["gold"] and case["question"]
        for group in case["expected_source_groups"]:
            assert group
            assert all(url in urls or url.startswith("https://fixtures.example/") for url in group)
