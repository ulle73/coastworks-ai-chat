"""Re-score BOTH variants under the same reviewed rubric, without regenerating answers."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from app.runtime import run
from evals.scoring import score_pairs


async def main(path):
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(Path("evals/questions.json").read_text(encoding="utf-8"))}
    await score_pairs(data["records"], list(cases.values()))
    for record in data["records"]:
        if not record["correct"] or not record["grounded"]:
            print(
                record["id"],
                record["mode"],
                record["correct"],
                record["grounded"],
                record["reason"],
                flush=True,
            )
    for mode in ["before", "after"]:
        subset = [r for r in data["records"] if r["mode"] == mode]
        summary = data["summary"][mode]
        summary["correctness"] = sum(r["correct"] for r in subset) / len(subset)
        summary["groundedness"] = sum(r["grounded"] for r in subset) / len(subset)
        costs = []
        for r in subset:
            usage = r.get("tokens", {})
            costs.append(
                sum(
                    (u["input_tokens"] * 0.30 + u["output_tokens"] * 2.50) / 1_000_000 for u in usage.values()
                )
            )
        summary["estimated_llm_usd_mean"] = statistics.mean(costs)
        summary["input_tokens_mean"] = statistics.mean(
            sum(u["input_tokens"] for u in r.get("tokens", {}).values()) for r in subset
        )
        summary["output_tokens_mean"] = statistics.mean(
            sum(u["output_tokens"] for u in r.get("tokens", {}).values()) for r in subset
        )
    data["questions_sha256"] = hashlib.sha256(Path("evals/questions.json").read_bytes()).hexdigest()
    data["scoring"] = "blind-paired-v1"
    data["rubric_review"] = (
        "Ambiguous follow-up accepts explicitly scoped answer; payment-method question does not require unsolicited VAT/shipping details. Both variants rejudged identically."
    )
    source.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data["summary"], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("path")
    run(main(p.parse_args().path))
