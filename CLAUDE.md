# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Refund triage for an online retailer: **rules decide the money, an LLM only reads the free-text notes, people handle
everything else**. Two outcomes only, `approve` or `route` (to the `reviewer` or `fraud` queue). The system never
rejects. README.md explains the product; `docs/eda/findings.md` holds the evidence for the policy's thresholds.

## Commands

```bash
source .venv/bin/activate                 # venv already exists; pip install -r requirements.txt && pip install -e . if not
pytest                                    # full suite (~180 tests, ~12s), no API key needed
pytest tests/test_engine.py               # one file
pytest tests/test_engine.py -k unknown    # one test by name
refund-agent decide data/pending.csv      # decide a CSV -> outputs/system_decisions.jsonl (+ requests_snapshot.jsonl)
refund-agent decide x.csv --no-llm --policy 1 --out /tmp/d.jsonl
refund-agent backtest                     # replay latest policy on data/history.csv; exit 1 on FAIL
refund-agent backtest --no-write          # same, without rewriting "The line" section of docs/eda/findings.md
streamlit run app/Home.py                 # demo app (Home, Reviewer Queue, Manager Policy)
python scripts/eda.py                     # regenerates docs/eda/findings.md + figures from data/
python scripts/eval_extractor.py          # needs a key, ~$0.05; rewrites docs/eda/extractor_eval.md and data/llm_cache_seed.jsonl
```

`refund-agent` is the console script for `src.cli:main` (`python -m src.cli` also works). There is no linter or
formatter configured. The Streamlit page tests use `streamlit.testing.v1.AppTest` and are the slowest part of the suite.

Everything runs without `ANTHROPIC_API_KEY`: the LLM degrades to "unknown" answers. Default model is
`claude-haiku-5-5`; `REFUND_AGENT_MODEL` / `REFUND_AGENT_TRANSLATOR_MODEL` override, and the app sidebar persists
choices to `outputs/app_settings.json` (env var > file > default, see `src/app_settings.py`).

## Architecture

Flow for one CSV: `src/data/normalize.py` (types, reason aliases, PII redaction, duplicate-id detection) ->
`src/policy/engine.py` (first matching rule wins) -> `src/queue.py::run_system` writes decisions + a request snapshot
to `outputs/`. The app and CLI share this exact path; nothing in the app is mocked.

**Policy** (`policies/vN.json`, schema in `src/schemas/policy.py`): a list of `facts` (yes/no questions the LLM
answers about the notes) and an ordered list of `rules`, each `IF conditions THEN approve | route`. Conditions may
reference request columns (`REQUEST_FIELDS`) or fact ids; the `Policy` validator rejects anything else. The
`Policy.describe_rule` text is what reviewers and the manager see, so keep `description` on every rule.

**Engine invariants** (`src/policy/engine.py`): rules are walked top to bottom; column conditions are checked first and
facts are requested from the `FactProvider` only when a rule's column conditions already hold and it references a
fact (this is what keeps LLM calls rare). `evaluate_condition` returns `True / False / None`; **unknown never
satisfies a condition, so unknown can never approve**. No rule matching means `route` to reviewer (`default_route`).

**Policy versions are immutable**: `store.save_policy` refuses to overwrite `vN.json`; every change goes through
`src/policy/operations.py::apply_operation`, which returns a new `Policy` with `version + 1`. New `route` rules
default to the top, new `approve` rules to the bottom (`resolve_position`). Rollback republishes an older version as a
new number.

**LLM layer** (`src/llm/`): `client.py` is the only module that imports `anthropic`; it uses structured output
(`messages.parse` with a pydantic `output_format`) and tracks tokens/cost/latency in `stats`. Prompts live as
`src/llm/prompts/*.md` templates filled by `render_prompt`. Two callers:
- `extractor.py::FactExtractor` satisfies the engine's `FactProvider` signature. Any failure (no key, timeout, bad
  output) becomes `unknown` and is **not cached** so the next run retries. Answers are cached in
  `outputs/llm_cache.jsonl`, keyed on (request id, both notes, question id, question text, model); the committed
  `data/llm_cache_seed.jsonl` holds answers for every history note so `backtest` reproduces offline.
- `translator.py::translate_instruction` turns a manager's English into one `RuleOperation`
  (`add_rule | replace_rule | disable_rule | add_fact | cannot_express`). It post-validates the model's output against the
  closed field/fact vocabulary and downgrades anything unevaluable to `cannot_express`. The model proposes; publishing
  happens only in the app after a dry run.

**Pydantic models**: domain in `src/schemas/`, LLM return shapes in `src/llm/schemas/`. Add new ones there.

**Backtest** (`src/policy/backtest.py`): ground truth is derived from `history.csv` (`outcome_note` text for
chargebacks / appeals / fraud confirmation, plus the reviewer's final `decision`). A "bad" auto-approval is
"detectable" when a note or fraud flag existed; any detectable bad approval makes the verdict `FAIL`. `diff_policies`
powers the Manager page dry run and sets `blocks_publish`. `cap_table` re-runs the backtest with the `over_cap` rule's
value swapped (that rule id is hard-coded there).

**State** is two append-only JSONL files in `outputs/` (`system_decisions.jsonl`, `reviewer_decisions.jsonl`) plus
`requests_snapshot.jsonl`; the reviewer queue is derived on every read (routed minus already-reviewed). `outputs/` is
gitignored and is also where logs (`outputs/logs/app.log`) and the LLM cache go.

**Streamlit pages** (`app/`) do `sys.path.insert` to import `src` and `app._shared`; `_shared.py` builds the fact
provider, sidebar, and formatting helpers. Widget keys in the Manager page carry a generation suffix (`key@N`) that
changes on discard/publish/rollback so checkboxes reset; tests find them by splitting on `@`.

## Testing conventions

- `tests/conftest.py` sets `ANTHROPIC_API_KEY=""` before importing `src`, so tests never hit the API. Session
  fixtures `history_df` / `pending_df` are the normalized real data files.
- Use the `tmp_outputs` fixture for anything that writes: it monkeypatches every path in `src.settings` (outputs, cache,
  decisions, `POLICY_DIR`) and `app_settings.SETTINGS_PATH` to a temp dir. Tests that need a policy copy v1 into the
  temp policy dir via `save_policy(load_policy(1, policy_dir=ROOT / "policies"))`.
- `tests/fixtures/fact_labels.csv` are hand labels for the extractor eval (generated by `scripts/label_facts.py`), not
  a test input.

## Data

`data/history.csv` (248 decided requests, 3 months) and `data/pending.csv` are deliberately messy; the data dictionary
(`data/data_dictionary.csv`) says what columns should hold and `normalize.py` makes it so. Request ids `RF-1xxx` are
web form, `RF-2xxx` support desk. `data/policy_notes.csv` is the manager's six numbered notes; `src/policy_notes.py`
maps stated reasons to them for the reviewer page.
