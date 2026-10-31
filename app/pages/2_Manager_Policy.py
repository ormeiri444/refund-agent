"""Manager Policy: change the rules in English, see what it would do, publish, roll back."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app._shared import get_fact_provider, live_policy, money, sidebar_status  # noqa: E402
from src import settings  # noqa: E402
from src.app_settings import load_app_settings  # noqa: E402
from src.data.normalize import load_requests  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.llm.schemas.operation import RuleOperation  # noqa: E402
from src.llm.translator import translate_instruction  # noqa: E402
from src.policy.backtest import diff_policies, run_backtest  # noqa: E402
from src.policy.operations import apply_operation, proposal_notes, resolve_position  # noqa: E402
from src.policy.store import list_versions, load_policy, save_policy  # noqa: E402
from src.queue import run_system  # noqa: E402
from src.schemas import REQUEST_FIELDS, Condition, FactQuestion, Policy, Rule  # noqa: E402

st.set_page_config(page_title="Manager Policy", page_icon="📜", layout="wide")
sidebar_status()
st.title("Manager Policy")

OPS = ["==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_true", "is_false", "is_unknown"]
EXAMPLES = {
    "Stolen-card cases go straight through": "From now on, stolen-card cases go straight through.",
    "Anything over $300 comes to us": "From now on, anything over $300 comes to us.",
    "Angry customers get a human": "Angry customers get a human.",
}

live = live_policy()
if live is None:
    st.error("No policy on disk.")
    st.stop()


@st.cache_data(show_spinner=False)
def history_df() -> pd.DataFrame:
    return load_requests(settings.DATA_DIR / "history.csv")


@st.cache_data(show_spinner=False)
def pending_df() -> pd.DataFrame:
    return load_requests(settings.DATA_DIR / "pending.csv")


# ------------------------------------------------------------------ proposal state
ss = st.session_state


def reset_proposal() -> None:
    """Forget the proposal and every checkbox value, so nothing resurrects on the next run."""
    ss["proposal"], ss["proposal_notes"], ss["dry_run"], ss["verdict"], ss["translated"], ss["translated_from"] = None, [], None, None, None, None
    ss["checkbox_gen"] = ss.get("checkbox_gen", 0) + 1   # new widget keys: the browser forgets the old tick state
    ss["proposal_base"] = live.version


if ss.get("proposal_base") != live.version:
    reset_proposal()
gen = ss.setdefault("checkbox_gen", 0)
for key in [k for k in ss if str(k).startswith("enabled_") and not str(k).endswith(f"@{gen}")]:
    del ss[key]                                   # tick state from a discarded or published proposal


def proposal() -> Policy:
    return ss["proposal"] or live


def stage(op: RuleOperation, note: str) -> None:
    """Apply one change to the proposal (creating it from the live policy on first use)."""
    base = ss["proposal"] or live
    new = apply_operation(base, op, changelog="")
    new.version = live.version + 1
    ss["proposal"], ss["dry_run"], ss["verdict"] = new, None, None
    ss["proposal_notes"].append(note)


def parse_value(op: str, raw: str):
    if op in ("is_true", "is_false", "is_unknown"):
        return None
    if op in ("in", "not_in"):
        return [v.strip() for v in raw.split(",") if v.strip()]
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw.strip()


# ------------------------------------------------------------------ 1. live policy
st.subheader(f"Policy in force: v{live.version}")
st.caption(live.changelog)
with st.expander("Fact questions the model answers from the notes", expanded=False):
    for q in proposal().facts:
        st.markdown(f"- **{q.id}**: {q.question}")
st.markdown("**Rules, top to bottom** (first match decides; untick to disable in the proposal):")
for i, rule in enumerate(proposal().rules, start=1):
    col_a, col_b = st.columns([1, 11])
    want = col_a.checkbox("on", value=rule.enabled, key=f"enabled_{rule.id}@{gen}", label_visibility="collapsed")
    col_b.markdown(f"{i}. **{rule.name}** `{rule.id}` — {proposal().describe_rule(rule)}" + ("" if rule.enabled else " _(disabled)_"))
    if want != rule.enabled:
        if want:
            stage(RuleOperation(op="replace_rule", target_rule_id=rule.id, rule=rule.model_copy(update={"enabled": True}), explanation=""),
                  f"re-enabled rule {rule.id}")
        else:
            stage(RuleOperation(op="disable_rule", target_rule_id=rule.id, explanation=""), f"disabled rule {rule.id}")
        st.rerun()

# ------------------------------------------------------------------ 2. describe a change
st.subheader("Describe a change")
ex_cols = st.columns(len(EXAMPLES))
for col, (label, text) in zip(ex_cols, EXAMPLES.items()):
    if col.button(label, key=f"example_{label[:12]}"):
        ss["instruction"] = text
translator_client = LLMClient(model=load_app_settings().translator_model)
instruction = st.text_area("In plain English", key="instruction", placeholder="From now on, anything over $300 comes to us.")
if not translator_client.available:
    st.caption("No API key: the translator is off. Write the rule with the form below instead.")
if st.button("Translate into a rule", key="btn_translate", disabled=not instruction):
    with st.spinner("Asking the model..."):
        ss["translated"] = translate_instruction(instruction, proposal(), translator_client)
    ss["translated_from"] = instruction
translated: RuleOperation | None = ss.get("translated")
if translated is not None:
    if translated.op == "cannot_express":
        st.warning(f"Can't do that as asked: {translated.explanation}")
    elif translated.op == "add_fact" and translated.fact:
        st.info(f"The model suggests a new fact question: **{translated.fact.id}**: {translated.fact.question}. {translated.explanation}")
        if st.button("Add this question to the proposal", key="btn_accept_fact"):
            stage(translated, f"added question {translated.fact.id}: {translated.fact.question}")
            ss["translated"] = None
            st.rerun()
    elif translated.op == "disable_rule":
        st.info(f"Proposed: disable rule `{translated.target_rule_id}`. {translated.explanation}")
        if st.button("Add to proposal", key="btn_accept_disable"):
            stage(translated, f"instruction: {ss.get('translated_from', '')}")
            ss["translated"] = None
            st.rerun()
    elif translated.rule is not None:
        st.success(f"Proposed: {proposal().describe_rule(translated.rule)}. {translated.explanation}")
        st.caption("Check it in the form below (you can edit anything), then add it to the proposal.")

# ------------------------------------------------------------------ 3. the rule form
st.markdown("**Rule form**")
pre = translated.rule if translated is not None and translated.rule is not None else None
field_choices = sorted(REQUEST_FIELDS - {"request_id"}) + proposal().fact_ids()
if pre is not None and ss.get("form_loaded_from") is not translated:
    ss["form_rule_id"], ss["form_rule_name"], ss["form_rule_description"] = pre.id, pre.name, pre.description
    ss["form_then"], ss["form_queue"], ss["n_conds"] = pre.then, pre.queue, max(1, len(pre.when))
    for i, c in enumerate(pre.when):
        ss[f"cond_field_{i}"] = c.field if c.field in field_choices else field_choices[0]
        ss[f"cond_op_{i}"] = c.op
        ss[f"cond_value_{i}"] = "" if c.value is None else (", ".join(map(str, c.value)) if isinstance(c.value, list) else str(c.value))
    ss["form_position"] = translated.position or resolve_position(pre, None)
    ss["_last_then"] = pre.then
    ss["form_loaded_from"] = translated

f1, f2, f3 = st.columns(3)
rule_id = f1.text_input("Rule id (snake_case)", key="form_rule_id")
rule_name = f2.text_input("Name", key="form_rule_name")
rule_desc = f3.text_input("Description shown to reviewers", key="form_rule_description")
t1, t2, t3 = st.columns(3)
then = t1.selectbox("Then", ["approve", "route"], key="form_then")
queue = t2.selectbox("Queue (for route)", ["reviewer", "fraud"], key="form_queue")
if ss.get("_last_then") != then:                      # position default follows the outcome: route -> top, approve -> bottom
    ss["form_position"] = "top" if then == "route" else "bottom"
    ss["_last_then"] = then
position = t3.selectbox("Position", ["top", "bottom"], key="form_position",
                        help="Route rules go on top so they outrank approvals; approve rules go to the bottom, below every guard.")
n_conds = ss.setdefault("n_conds", 1)
conds: list[Condition] = []
for i in range(n_conds):
    c1, c2, c3 = st.columns([3, 2, 3])
    fld = c1.selectbox(f"Condition {i + 1}: field", field_choices, key=f"cond_field_{i}")
    op = c2.selectbox("operator", OPS, key=f"cond_op_{i}")
    raw = c3.text_input("value (comma-separated for in / not_in)", key=f"cond_value_{i}")
    conds.append(Condition(field=fld, op=op, value=parse_value(op, raw)))
cc1, cc2 = st.columns([1, 5])
if cc1.button("+ condition", key="btn_add_cond"):
    ss["n_conds"] = n_conds + 1
    st.rerun()
replacing = translated is not None and translated.op == "replace_rule" and translated.target_rule_id
if replacing:
    st.caption(f"This will replace the existing rule `{translated.target_rule_id}` in place.")
if cc2.button("Save this rule to the proposal" if replacing else "Add this rule to the proposal", key="btn_add_to_proposal", type="primary"):
    try:
        rule = Rule(id=rule_id.strip(), name=rule_name.strip() or rule_id.strip(), description=rule_desc.strip(), when=conds, then=then, queue=queue)
        if replacing:
            rule.id = translated.target_rule_id
            op = RuleOperation(op="replace_rule", target_rule_id=translated.target_rule_id, rule=rule, explanation="")
        else:
            op = RuleOperation(op="add_rule", rule=rule, position=position, explanation="")
        stage(op, f"instruction: {ss['translated_from']}" if ss.get("translated_from") else f"added rule {rule.id}")
        ss["translated"], ss["translated_from"] = None, None
        st.rerun()
    except Exception as exc:  # pydantic or ValueError: show the reason, nothing is staged
        st.error(f"Not added: {exc}")

# ------------------------------------------------------------------ 4. add a fact question
st.markdown("**Add a fact question** (a yes/no question the model answers from the notes; rules can then use it)")
q1, q2, q3 = st.columns([2, 5, 2])
fact_id = q1.text_input("id (snake_case)", key="fact_id")
fact_q = q2.text_input("question", key="fact_question", placeholder="Does the note mention a police report?")
if q3.button("Add question", key="btn_add_fact"):
    try:
        stage(RuleOperation(op="add_fact", fact=FactQuestion(id=fact_id.strip(), question=fact_q.strip()), explanation=""),
              f"added question {fact_id.strip()}: {fact_q.strip()}")
        st.rerun()
    except Exception as exc:
        st.error(f"Not added: {exc}")

# ------------------------------------------------------------------ 5. the proposal
net_notes = proposal_notes(live, proposal()) if ss["proposal"] else []
if ss["proposal"] and not net_notes:
    st.subheader("Proposal: no difference from the policy in force")
    st.caption("Every change was undone (for example a rule unticked and ticked again).")
else:
    st.subheader(f"Proposal: v{live.version + 1}" if ss["proposal"] else "Proposal: none yet")
for note in net_notes:
    st.markdown(f"- {note}")
if ss["proposal"]:
    if st.button("Discard proposal", key="btn_discard"):
        reset_proposal()
        st.rerun()

# ------------------------------------------------------------------ 6. dry run
st.subheader("Dry run: what would change")
st.caption("Compares the policy in force with the proposal on the 248 past requests and on the pending file. No money moves.")


def read_new_facts(policy: Policy, new_ids: list[str], df: pd.DataFrame):
    """A new question has no cached answers: read the past notes once, with progress and cost."""
    provider, label = get_fact_provider()
    questions = [q for q in policy.facts if q.id in new_ids]
    rows = df[df.has_note].to_dict(orient="records")
    answers: dict[str, dict] = {}
    if not hasattr(provider, "client") or not provider.client.available:
        st.warning("No API key: the new question cannot be read on past notes, so it is 'unknown' everywhere in this dry run.")
        return answers, 0.0
    bar = st.progress(0.0, text=f"Reading {len(rows)} past notes for: {', '.join(new_ids)}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(provider, r, questions): r["request_id"] for r in rows}
        for n, fut in enumerate(as_completed(futures), start=1):
            answers[futures[fut]] = {k: v for k, v in fut.result().items()}
            bar.progress(n / len(rows))
    bar.empty()
    cost = getattr(provider, "stats", {}).get("cost_usd", 0.0)
    st.caption(f"Read {len(rows)} notes for {len(questions)} new question(s); cost ${cost:.4f}.")
    return answers, cost


if st.button("Dry run", key="btn_dry_run", disabled=not net_notes):
    prop = proposal()
    new_ids = [q for q in prop.fact_ids() if q not in live.fact_ids()]
    new_fact_answers = {}
    if new_ids:
        new_fact_answers, _ = read_new_facts(prop, new_ids, history_df())
    provider, _ = get_fact_provider()
    with st.spinner("Replaying both policies..."):
        d_hist = diff_policies(history_df(), live, prop, provider)
        d_pend = diff_policies(pending_df(), live, prop, provider)
        verdict = run_backtest(history_df(), prop, provider)
    ss["dry_run"] = {"history": d_hist, "pending": d_pend, "new_fact_answers": new_fact_answers, "new_ids": new_ids}
    ss["verdict"] = verdict

if ss.get("dry_run"):
    dr, verdict = ss["dry_run"], ss["verdict"]
    for title, d in (("Past 3 months (248 requests)", dr["history"]), ("Pending file", dr["pending"])):
        st.markdown(f"**{title}**: {d.n_flipped} request(s) would flip.")
        m1, m2, m3 = st.columns(3)
        m1.metric("to automatic", len(d.to_auto), money(d.dollars_to_auto))
        m2.metric("to a person", len(d.to_human), money(d.dollars_to_human))
        m3.metric("flipped", d.n_flipped)
        if d.newly_bad_detectable:
            st.error("RED, blocks publishing: the proposal would newly approve past cases that went bad and could have been caught: "
                     + ", ".join(d.newly_bad_detectable))
        if d.newly_bad_undetectable:
            st.warning("YELLOW, accepted risk: newly approved past cases that went bad with nothing to read: " + ", ".join(d.newly_bad_undetectable))
        if d.newly_caught_detectable or d.newly_caught_undetectable:
            st.success("GREEN: past bad cases the proposal would now send to a person: " + ", ".join(d.newly_caught_detectable + d.newly_caught_undetectable))
        if d.per_request:
            with st.expander(f"Flipped requests ({d.n_flipped})"):
                st.dataframe(pd.DataFrame(d.per_request), hide_index=True, width="stretch")
    if dr["history"].n_flipped == 0 and dr["pending"].n_flipped == 0:
        st.info("Nothing flips. If you added an approve rule meant to override a guard (for example 'stolen-card cases go straight "
                "through' must beat the fraud-flag rule), it sits at the bottom by default: set its Position to top and add it again.")
    st.markdown(f"**Backtest verdict for the proposal: {verdict.verdict}** — "
                f"{verdict.n_auto_approve} auto-approved ({verdict.auto_approve_rate:.0%}), {money(verdict.dollars_auto_approved)}, "
                f"{len(verdict.bad_detectable)} detectable bad, {len(verdict.bad_undetectable)} accepted risk.")
    if verdict.bad_detectable:
        st.error("Detectable bad auto-approvals under the proposal: " + ", ".join(f"{b.request_id} ({b.reason})" for b in verdict.bad_detectable))
    if dr["new_fact_answers"]:
        with st.expander("How the new question was answered on past notes"):
            rows = []
            for rid, facts in dr["new_fact_answers"].items():
                for fid, v in facts.items():
                    rows.append({"request_id": rid, "fact": fid, "answer": {True: "yes", False: "no", None: "unknown"}[v.value], "quote": v.quote})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ------------------------------------------------------------------ 7. publish
st.subheader("Publish")
verdict = ss.get("verdict")
if ss["proposal"] and verdict is None:
    st.caption("You can publish without a dry run; the backtest check still runs on publish.")
fail = verdict is not None and verdict.verdict == "FAIL"
publish_anyway = st.checkbox("Publish anyway (the backtest FAILED: the proposal approves past cases that went bad)",
                             key="publish_anyway") if fail else False
instructions = [n for n in ss["proposal_notes"] if n.startswith("instruction: ")]
default_note = "; ".join(i.removeprefix("instruction: ") for i in instructions) or "; ".join(net_notes)
p1, p2 = st.columns([4, 2])
change_note = p1.text_input("Change note (pre-filled from your instruction, editable)", value=default_note, key="change_note")
published_by = p2.text_input("Published by (optional)", key="published_by")
if st.button(f"Publish as v{live.version + 1}", key="btn_publish", type="primary", disabled=not net_notes or (fail and not publish_anyway)):
    prop = proposal()
    if verdict is None:
        provider, _ = get_fact_provider()
        verdict = run_backtest(history_df(), prop, provider)
        ss["verdict"] = verdict
    if verdict.verdict == "FAIL" and not publish_anyway:
        st.error("The backtest FAILED for this proposal. Run the dry run to see why, then tick 'Publish anyway' if you still want it.")
    else:
        prop.changelog = (change_note or default_note or "policy change") + (f" — published by {published_by}" if published_by else "")
        prop.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_policy(prop)
        reset_proposal()
        ss["proposal_base"] = prop.version
        ss["just_published"] = prop.version
        st.rerun()
if ss.get("just_published"):
    v = ss["just_published"]
    st.success(f"Published v{v}. The CLI and the Reviewer Queue use it from now on. Requests already decided keep their version.")
    if st.button(f"Re-run pending.csv with v{v}", key="btn_rerun_pending"):
        provider, _ = get_fact_provider()
        decisions = run_system(settings.DATA_DIR / "pending.csv", load_policy(v), provider)
        st.info(f"{len(decisions)} requests re-decided under v{v}: {sum(d.outcome == 'approve' for d in decisions)} automatic.")
        ss["just_published"] = None

# ------------------------------------------------------------------ 8. versions and rollback
st.subheader("Versions")
versions = list_versions()
for v in reversed(versions):
    pol = load_policy(v)
    st.markdown(f"- **v{v}** ({pol.created_at[:10]}): {pol.changelog}")
older = [v for v in versions if v != versions[-1]]
if older:
    r1, r2 = st.columns([2, 2])
    target = r1.selectbox("Roll back to", older, key="rollback_version", format_func=lambda v: f"v{v}")
    if r2.button(f"Roll back (publishes v{versions[-1] + 1} with v{target}'s rules)", key="btn_rollback"):
        old = load_policy(target)
        rolled = Policy(version=versions[-1] + 1, changelog=f"rollback to v{target}: {old.changelog}",
                        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), facts=old.facts, rules=old.rules)
        save_policy(rolled)
        reset_proposal()
        ss["proposal_base"] = rolled.version
        st.rerun()
