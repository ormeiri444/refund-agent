"""Score the LLM fact extractor against the hand labels, report cost, and write the cache seed.

Run (needs ANTHROPIC_API_KEY): python scripts/eval_extractor.py
Writes docs/eda/extractor_eval.md and data/llm_cache_seed.jsonl.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src import settings
from src.llm.client import LLMClient
from src.llm.extractor import FactExtractor
from src.logging_setup import setup_logging
from src.policy.store import load_policy

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eda import md_table  # noqa: E402  (shared markdown table helper)

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "tests" / "fixtures" / "fact_labels.csv"
OUT_MD = ROOT / "docs" / "eda" / "extractor_eval.md"
FACTS = ["damage_photo_confirmed", "carrier_proof_of_delivery", "carrier_investigation_open", "card_confirmed_stolen", "our_error_confirmed"]
TO_LABEL = {True: "T", False: "F", None: "U"}


def score(labels: pd.DataFrame, preds: pd.DataFrame) -> list[dict]:
    rows = []
    for f in FACTS:
        y, p = labels[f], preds[f]
        decided = y.isin(["T", "F"])
        tp = int(((p == "T") & (y == "T")).sum())
        fp_decided = int(((p == "T") & (y == "F")).sum())
        fp_strict = int(((p == "T") & (y != "T")).sum())
        yes_on_ambiguous = int(((p == "T") & (y == "U")).sum())
        n_true = int((y == "T").sum())
        rows.append({
            "fact": f,
            "labelled_yes": n_true, "labelled_no": int((y == "F").sum()),
            "model_yes": int((p == "T").sum()),
            "precision_yes": tp / max(tp + fp_decided, 1),
            "precision_yes_strict": tp / max(tp + fp_strict, 1),
            "recall_yes": tp / max(n_true, 1),
            "yes_on_unlabelled": yes_on_ambiguous,
            "accuracy_3class": float((y[decided] == p[decided]).mean()) if decided.any() else float("nan"),
        })
    return rows


def main() -> None:
    setup_logging()
    client = LLMClient()
    if not client.available:
        raise SystemExit("ANTHROPIC_API_KEY is not set; cannot run the evaluation")
    labels = pd.read_csv(LABELS, dtype=str).fillna("")
    policy = load_policy(1)
    eval_cache = settings.OUTPUTS_DIR / "eval_cache.jsonl"   # always fresh, so the cost below is what a real run costs
    eval_cache.unlink(missing_ok=True)
    extractor = FactExtractor(client, cache_path=eval_cache, use_seed=False)

    def run(row: dict) -> dict:
        facts = extractor(row, policy.facts)
        return {"request_id": row["request_id"], **{f: TO_LABEL[facts[f].value] for f in FACTS},
                **{f"{f}__quote": facts[f].quote for f in FACTS}}

    with ThreadPoolExecutor(max_workers=8) as pool:
        preds = pd.DataFrame(list(pool.map(run, labels.to_dict(orient="records"))))
    preds = preds.set_index("request_id").loc[labels.request_id].reset_index()

    rows = score(labels, preds)
    calls, cost = client.stats["calls"], client.stats["cost_usd"]
    per_call = cost / max(calls, 1)
    mismatches = []
    for f in FACTS:
        bad = labels[(labels[f] != "U") & (labels[f] != preds[f])]
        for r in bad.itertuples():
            mismatches.append({"fact": f, "request_id": r.request_id, "label": getattr(r, f),
                               "model": preds.loc[r.Index, f], "quote": preds.loc[r.Index, f + "__quote"],
                               "customer_note": r.customer_note, "support_note": r.support_note})

    # The seed: every cache entry produced for history notes, so the backtest reproduces without a key.
    shutil.copyfile(eval_cache, settings.CACHE_SEED_PATH)
    n_seed = sum(1 for _ in settings.CACHE_SEED_PATH.open())

    table = pd.DataFrame(rows)
    md = [
        "# Fact extractor evaluation",
        "",
        f"Model `{client.model}`, effort low, structured output via `messages.parse()`. Scored on `tests/fixtures/fact_labels.csv`: "
        f"{len(labels)} history requests with a note, hand-labelled T/F/U for each of the {len(FACTS)} fact questions in policy v1.",
        "",
        "**precision_yes**: of the model's yes answers on rows a human labelled yes or no, the share that were yes. This is the number that "
        "matters: a wrong yes can approve money. **precision_yes_strict** also counts a yes on a row the human left unlabelled as wrong. "
        "**recall_yes**: of the human yes rows, the share the model found. A miss only sends the case to a person.",
        "",
        md_table(table, "{:.2f}"),
        "",
        "## Cost",
        "",
        f"- calls: {calls} (one per request with a note, all {len(FACTS)} questions in one call)",
        f"- total spend for the {len(labels)} noted requests: ${cost:.4f}",
        f"- per call: ${per_call:.5f} (mean {client.stats['input_tokens'] // max(calls, 1)} input tokens, "
        f"{client.stats['output_tokens'] // max(calls, 1)} output tokens, {client.stats['latency_ms'] // max(calls, 1)} ms)",
        f"- cache seed written to `data/llm_cache_seed.jsonl` ({n_seed} answers) so `refund-agent backtest` reproduces offline",
        "",
        "## Yes answers on rows the human left unlabelled (ambiguous notes)",
        "",
    ]
    amb = []
    for f in FACTS:
        for r in labels[(labels[f] == "U") & (preds[f] == "T")].itertuples():
            amb.append({"fact": f, "request_id": r.request_id, "quote": preds.loc[r.Index, f + "__quote"],
                        "customer_note": r.customer_note, "support_note": r.support_note})
    md.append(md_table(pd.DataFrame(amb)) if amb else "none")
    md += ["", "## Mismatches against the labels", ""]
    if mismatches:
        md.append(md_table(pd.DataFrame(mismatches)))
    else:
        md.append("none")
    OUT_MD.write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
