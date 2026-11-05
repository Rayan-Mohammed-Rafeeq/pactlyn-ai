"""Run the controlled extraction comparison without changing the checked-in dataset."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from run_baseline import run as run_deterministic
from run_ollama import run as run_ollama

REPORTS = Path(__file__).parent / "reports" / "experiments"


async def run() -> dict[str, object]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    configurations = [
        ("A-existing-qwen2.5-7b", "qwen2.5:7b", "existing", "none"),
        ("B-improved-qwen2.5-7b", "qwen2.5:7b", "improved", "none"),
        ("C-improved-qwen2.5-7b-retrieved-context", "qwen2.5:7b", "improved", "existing_contacts"),
        ("alternative-qwen2.5-3b", "qwen2.5:3b", "improved", "none"),
    ]
    experiments: dict[str, object] = {}
    results: dict[str, object] = {
        "dataset": "evaluation/datasets/commitments.json",
        "dataset_size": 150,
        "methodology": "Same checked-in dataset, fixed evaluation_now, schema and scoring implementation for all model runs.",
        "experiments": experiments,
        "D-existing-deterministic-extractor": run_deterministic(),
    }
    original_model = os.environ.get("PACTLYN_OLLAMA_MODEL")
    original_prompt = os.environ.get("PACTLYN_PROMPT_VERSION")
    original_context = os.environ.get("PACTLYN_CONTEXT_MODE")
    try:
        for name, model, prompt, context in configurations:
            os.environ["PACTLYN_OLLAMA_MODEL"] = model
            os.environ["PACTLYN_PROMPT_VERSION"] = prompt
            os.environ["PACTLYN_CONTEXT_MODE"] = context
            outcome = await run_ollama()
            if isinstance(outcome, tuple):
                report, rows = outcome
                (REPORTS / f"{name}-rows.json").write_text(json.dumps(rows, indent=2) + "\n")
            else:
                report = outcome
            (REPORTS / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
            experiments[name] = report
    finally:
        for key, value in (
            ("PACTLYN_OLLAMA_MODEL", original_model),
            ("PACTLYN_PROMPT_VERSION", original_prompt),
            ("PACTLYN_CONTEXT_MODE", original_context),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    (REPORTS / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
