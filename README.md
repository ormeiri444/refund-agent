# Refund Agent

An online retailer gets a few hundred refund requests a week; a forgotten auto-approve rule takes some, a person
reads the rest. This project is a refund triage system where **rules decide the money, a model only reads the
notes, and people handle everything else**, plus the two mechanisms around it: the reviewer's queue and the
manager's policy editor.

- Presentation (slides): [docs/presentation.pptx](docs/presentation.pptx)
- Screen recording (9 min): [docs/demo.mp4](docs/demo.mp4)
- Evidence for the line: [docs/eda/findings.md](docs/eda/findings.md) (EDA + backtest, generated from the data)
- Model evaluation: [docs/eda/extractor_eval.md](docs/eda/extractor_eval.md)

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env            # optional: put your Anthropic API key in it (see "Plugging in an API key")

refund-agent decide data/pending.csv      # decide every request in a CSV with pending.csv's columns
refund-agent backtest                     # replay the policy on history.csv: PASS/FAIL, cap table, "The line"
streamlit run app/Home.py                 # the demo: Reviewer Queue and Manager Policy
pytest                                    # 180+ tests, no key needed
```

`decide` prints a summary (approved / routed, by rule) and writes one JSON line per request to
`outputs/system_decisions.jsonl` with the outcome, the rule that fired, the facts it used, and the policy version.
Works on any file with the same columns (`refund-agent decide my_file.csv`).

### Plugging in an API key

Either of these works; the environment variable wins if both are set:

```bash
cp .env.example .env            # then edit .env so it reads  ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_API_KEY=sk-ant-...   # or set it in the shell before running
```

`.env` is read from the project root by `python-dotenv` when `src` is imported, so the CLI, the Streamlit app and the
scripts all pick it up; it is gitignored. To confirm it took: `refund-agent decide data/pending.csv` prints
"LLM unavailable (no ANTHROPIC_API_KEY)" when it did not, and the app sidebar says the same.

### With and without a key

Everything runs without a key. The LLM does exactly one thing at decision time: answer the policy's yes/no questions
about the free-text notes ("does the note say a photo shows the damage?"). Without a key those answers are
"unknown", and a request whose approval depends on them goes to a person. The model's answers for the historical
notes are committed in `data/llm_cache_seed.jsonl`, so `refund-agent backtest` reproduces the presentation's numbers
offline. With `ANTHROPIC_API_KEY` in `.env`, new notes are read live. Default model `claude-haiku-5-5` for both
reading notes and translating rules (switchable in the app sidebar, or `REFUND_AGENT_MODEL` /
`REFUND_AGENT_TRANSLATOR_MODEL`); about $0.0002 per note-reading call, and most requests need no call.

## Architecture

```
                    policies/vN.json  (fact questions + ordered rules; versions never overwritten)
                              |
 CSV  -->  normalize  -->  engine  -->  approve | route (reviewer / fraud)  -->  outputs/system_decisions.jsonl
          (types, aliases,   |  first matching rule wins; unknown never approves
           PII redaction)    |  asks for a fact only when a rule needs it
                             v
                        extractor  (LLM reads the notes: true / false / unknown + quote; cached; offline = unknown)
                             |
                          client   (one Anthropic client: structured output, tokens, cost, latency)

 backtest   replays a policy on history.csv -> metrics, PASS/FAIL, cap table; diff of two policies for the dry run
 translator LLM: manager's English -> one structured change (add / replace / disable rule, add fact, or cannot_express)
 app/       Streamlit: Home (run, counters, reset) · Reviewer Queue · Manager Policy
```

Code lives under `src/` (`data/`, `policy/`, `llm/`, `schemas/`, `queue.py`, `cli.py`); every pydantic model is in
`src/schemas/` (domain) or `src/llm/schemas/` (what an LLM call must return).

## How a decision is made

The policy is a JSON file: a list of **fact questions** (yes/no questions about the notes) and an ordered list of
**rules**, each `IF <conditions> THEN approve | route`. The engine walks the rules top to bottom; the first rule
whose conditions all hold decides. If none holds, the request goes to a person. Unknown values (a blank fraud flag,
a fact the model could not answer) never satisfy a condition, so they never approve. Two outcomes only: **approve**
or **route to a person**. The system never rejects.

## How we know the line is right

`refund-agent backtest` replays the policy on the 3 months of decided requests. A **bad** auto-approval is one where
the case later charged back, carried a fraud flag the fraud team did not confirm, or a reviewer rejected or partially
refunded it (after appeals). Bad cases a note or flag could have caught make the verdict **FAIL** (exit 1); cases
nothing could have caught are listed as accepted risk. The same check runs on the manager's dry run and blocks
publishing (unless she ticks "publish anyway"). Headline, policy v1 with note facts: 120 of 248 past requests
auto-approved (48%, $5,015), 156 reviewer minutes saved, 0 detectable bad approvals, 1 accepted-risk case ($49).

## How well the model reads notes

`python scripts/eval_extractor.py` scores the extractor on 205 hand-labelled notes (`tests/fixtures/fact_labels.csv`):
precision of "yes" is 1.00 on all five facts (a wrong yes is what could approve money), recall 0.76 to 1.00, about
$0.0002 per call. Needs a key; costs about $0.05. Results and every mismatch: `docs/eda/extractor_eval.md`.

## The demo app

`streamlit run app/Home.py`:

- **Home**: run the system on `data/pending.csv`, see the counters, reset the demo.
- **Reviewer Queue**: the requests the rules did not take, oldest first, with a fraud-queue filter. For each: why it is
  here (the rule in plain words), what the model read in the notes with the exact words it relied on, the customer's
  history, and the manager's policy note that applies. Actions: approve in full, approve partial, reject, send to
  the fraud queue; each is appended to `outputs/reviewer_decisions.jsonl` with the reviewer's name and the policy
  version. A collapsed table lists what the system approved on its own, for spot-checks.
- **Manager Policy**: type an instruction in English ("From now on, anything over $300 comes to us"); the model
  returns one structured change or says exactly why it can't ("no fact question covers 'angry'"). Check it in the
  form, stage it in a proposal (several changes can be batched; the panel shows the net difference from the live
  policy), run a **dry run**: live vs proposal on the 248 past requests and the pending file, what flips, the
  dollars, and the red / yellow / green lists. A new fact question is read on all past notes once, with a progress
  bar and the cost. Publish writes `policies/v{N+1}.json`; rollback republishes an older version.
- **Sidebar**: which model reads notes and which translates rules, with prices.

Nothing in the app is a mock: the pages call the same engine, extractor and decision logs as the CLI. There is no
payments integration ("approve" writes a decision record) and the fraud queue is a label, not a workflow.

## How I used AI coding tools

Built with Claude Code: a design conversation first, then a written plan with tests for each step, then one branch
per step with a review pass between them (the spec and plan are local notes, not shipped). One thing it produced
that I threw away: the first note question was "photo attached" (does the note say a photo was sent?). Replaying
it on history showed approvals where the photo proved the item was fine, so the question became "does the photo
show damage to the item itself" (`damage_photo_confirmed` in `policies/v1.json`), with the support shorthand
spelled out in the question.
