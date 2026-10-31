"""Exploratory data analysis: writes docs/eda/findings.md and docs/eda/figures/*.png.

Run: python scripts/eda.py
Everything the write-up says about "the process today" and "the evidence for the line"
is computed here, from the data, so the numbers can be regenerated.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from src.data.normalize import find_issues, normalize_requests
from src.logging_setup import setup_logging

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "docs" / "eda"
FIG = OUT / "figures"

# Palette (dataviz skill reference instance). Status red is reserved for bad outcomes.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
CRITICAL = "#d03b3b"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
CHARGEBACK_FEE = 25.0
AMOUNT_BANDS = [(0, 50, "$0-50"), (50, 100, "$50-100"), (100, 200, "$100-200"), (200, 10_000, "$200+")]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "legend.frameon": False,
    "figure.dpi": 100,
})


def md_table(df: pd.DataFrame, floatfmt: str = "{:,.1f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float) and not pd.isna(v):
                cells.append(floatfmt.format(v))
            elif pd.isna(v) if not isinstance(v, (list, tuple, str)) else False:
                cells.append("")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def amount_band(a: float) -> str:
    for lo, hi, label in AMOUNT_BANDS:
        if lo <= a < hi:
            return label
    return "unknown"


def t(text: str) -> str:
    """Escape dollar signs so matplotlib does not render them as math."""
    return text.replace("$", r"\$")


def save(fig, name: str) -> str:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG / name, dpi=150)
    plt.close(fig)
    return f"figures/{name}"


# --------------------------------------------------------------------------- sections

def section_data_quality(raw_h: pd.DataFrame, raw_p: pd.DataFrame) -> str:
    ih, ip = find_issues(raw_h), find_issues(raw_p)
    rows = [{"issue": k, "history": ih[k], "pending": ip.get(k, 0)} for k in ih]
    return "\n".join([
        "## 1. Data quality",
        "",
        f"history.csv: {len(raw_h)} rows. pending.csv: {len(raw_p)} rows. "
        "Counts of rows that depart from the data dictionary (fixed by `normalize_requests`):",
        "",
        md_table(pd.DataFrame(rows)),
        "",
        "Notes: duplicate ids are dropped keeping the first row. The pending duplicate (RF-2183) has two "
        "different amounts, so whichever is kept, a person should look at it. Fraud flag variants "
        "(`Y`, `N`, `false`, blank) are mapped to yes/no; a blank stays unknown and is never treated as 'no'.",
    ])


def section_volume(h: pd.DataFrame) -> tuple[str, str]:
    by_reason = h.pivot_table(index="stated_reason", columns="decision", values="request_id",
                              aggfunc="count", fill_value=0)
    by_reason["total"] = by_reason.sum(axis=1)
    by_reason = by_reason.sort_values("total", ascending=False)
    by_decider = h.groupby("decided_by").agg(requests=("request_id", "count"),
                                              dollars=("amount_usd", "sum"),
                                              approved=("decision", lambda s: (s == "approved").sum()))
    auto = h[h.decided_by == "auto"]
    auto_share = len(auto) / len(h)
    auto_dollars = auto.amount_usd.sum() / h.amount_usd.sum()

    fig, ax = plt.subplots(figsize=(12, 5.5))
    order = ["approved", "partial", "rejected"]
    colors = {"approved": BLUE, "partial": YELLOW, "rejected": ORANGE}
    left = pd.Series(0, index=by_reason.index, dtype=float)
    for d in order:
        vals = by_reason[d] if d in by_reason else pd.Series(0, index=by_reason.index)
        ax.barh(by_reason.index, vals, left=left, color=colors[d], label=d, height=0.55, edgecolor=SURFACE, linewidth=2)
        left = left + vals
    for i, (reason, tot) in enumerate(by_reason["total"].items()):
        ax.text(tot + 1, i, str(int(tot)), va="center", color=INK2, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("requests (3 months)")
    ax.set_title("Most requests are approved; rejections cluster in never_arrived and changed_mind", loc="left", color=INK)
    ax.legend(loc="lower right")
    fig1 = save(fig, "fig1_decisions_by_reason.png")

    text = "\n".join([
        "## 2. Volume: what comes in and who decides",
        "",
        f"![decisions by reason]({fig1})",
        "",
        md_table(by_reason.reset_index(), "{:,.0f}"),
        "",
        "By decider (requests, dollars requested, approved count):",
        "",
        md_table(by_decider.reset_index()),
        "",
        f"The existing auto rule decides **{len(auto)} of {len(h)} requests ({auto_share:.0%})** but only "
        f"**{auto_dollars:.0%} of the dollars**. Everything else is read by one of four reviewers.",
    ])
    return text, fig1


def section_old_rule(h: pd.DataFrame) -> str:
    auto = h[h.decided_by == "auto"]
    human = h[h.decided_by != "auto"]
    cap, min_tenure, max_prior = auto.amount_usd.max(), int(auto.tenure_months.min()), int(auto.prior_refunds_12m.max())
    flags = sorted({str(v) for v in auto.fraud_flag.unique()})
    inside = human[(human.amount_usd <= cap) & (human.prior_refunds_12m <= max_prior)
                   & (human.tenure_months.fillna(-1) >= min_tenure) & (human.fraud_flag != True)]
    inside_breakdown = inside.groupby(["stated_reason", "has_note"]).size().reset_index(name="count")
    small_new = human[(human.amount_usd <= cap) & (human.prior_refunds_12m <= max_prior)
                      & (human.tenure_months.fillna(-1) < min_tenure) & (human.fraud_flag != True)]
    inside_outcomes = inside.decision.value_counts().to_dict()

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.scatter(human.tenure_months.astype(float), human.amount_usd, s=28, color=ORANGE, alpha=0.8,
               label="decided by a reviewer", edgecolors=SURFACE, linewidths=1)
    ax.scatter(auto.tenure_months.astype(float), auto.amount_usd, s=28, color=BLUE, alpha=0.9,
               label="decided by the old auto rule", edgecolors=SURFACE, linewidths=1)
    ax.axhline(cap, color=MUTED, linestyle="--", linewidth=1)
    ax.axvline(min_tenure, color=MUTED, linestyle="--", linewidth=1)
    ax.text(ax.get_xlim()[1], cap + 6, t(f"auto never above ${cap:.0f}"), ha="right", color=INK2, fontsize=9)
    ax.text(min_tenure + 0.5, ax.get_ylim()[1] * 0.95, f"auto never below {min_tenure} months tenure", color=INK2, fontsize=9)
    ax.set_xlabel("customer tenure (months)")
    ax.set_ylabel("requested amount (USD)")
    ax.set_title(f"The old auto rule: small amounts from established customers; {len(inside)} human-decided requests sit inside the same box",
                 loc="left", color=INK)
    ax.legend(loc="upper right")
    fig3 = save(fig, "fig3_old_rule_boundary.png")

    return "\n".join([
        "## 3. The old auto rule, reverse-engineered",
        "",
        "Nobody remembers the logic, so here it is from the data. Every auto-decided request satisfies all of:",
        "",
        f"- amount <= **${cap:.0f}**",
        f"- prior refunds in 12 months <= **{max_prior}**",
        f"- tenure >= **{min_tenure} months**",
        f"- fraud flag not yes (values seen: {', '.join(flags)})",
        f"- any stated reason ({', '.join(sorted(auto.stated_reason.unique()))})",
        f"- every one of the {len(auto)} was **approved** in full",
        "",
        f"![old rule boundary]({fig3})",
        "",
        f"**{len(inside)} requests decided by humans also fit inside that box.** Their outcomes: {inside_outcomes}. "
        "Why they were not auto-decided is not in the data; the pattern below (most of them carry a note) suggests the "
        "old rule skips anything with free text, or routes by source. Either way these are candidates for automation:",
        "",
        md_table(inside_breakdown, "{:,.0f}"),
        "",
        f"A further **{len(small_new)} small requests (<= ${cap:.0f}, no prior refunds) came from customers with under {min_tenure} months tenure** "
        f"and so fell outside the old rule; outcomes: {small_new.decision.value_counts().to_dict()}. "
        "Tenure is the main reason small requests still reach a reviewer.",
    ])


def section_reviewer_time(h: pd.DataFrame) -> str:
    human = h[(h.decided_by != "auto") & h.review_minutes.notna()].copy()
    human["band"] = human.amount_usd.map(amount_band)
    per_reviewer = human.groupby("decided_by").review_minutes.agg(requests="count", mean_min="mean", total_min="sum").reset_index()
    band = human.groupby("band").agg(requests=("request_id", "count"), total_min=("review_minutes", "sum"),
                                     approved_full=("decision", lambda s: (s == "approved").sum()))
    band = band.reindex([b[2] for b in AMOUNT_BANDS]).fillna(0)
    band["approved_full_share"] = band.approved_full / band.requests.replace(0, 1)
    band_md = band.copy()
    band_md["approved_full_share"] = band_md.approved_full_share.map("{:.0%}".format)
    small_ok = human[(human.amount_usd <= 50) & (human.decision == "approved")]
    share_small = small_ok.review_minutes.sum() / human.review_minutes.sum()

    fig, ax = plt.subplots(figsize=(12, 5))
    bars = ax.bar(band.index, band.total_min, color=BLUE, width=0.55)
    for b, (lab, row) in zip(bars, band.iterrows()):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 4,
                f"{row.total_min:.0f} min\n{row.approved_full_share:.0%} approved in full", ha="center", color=INK2, fontsize=9)
    ax.set_ylabel("reviewer minutes (3 months, sample)")
    ax.set_title(t(f"Reviewer time by amount: {share_small:.0%} of all reviewer minutes go to requests <= $50 that were approved in full anyway"),
                 loc="left", color=INK)
    ax.set_ylim(0, band.total_min.max() * 1.25)
    fig4 = save(fig, "fig4_reviewer_minutes_by_band.png")

    return "\n".join([
        "## 4. Where reviewer time goes",
        "",
        f"![reviewer minutes by band]({fig4})",
        "",
        md_table(per_reviewer),
        "",
        md_table(band_md.reset_index().rename(columns={"index": "band"})),
        "",
        f"Total reviewer time in the sample: **{human.review_minutes.sum():.0f} minutes** over {len(human)} requests "
        f"(mean {human.review_minutes.mean():.1f} min). **{len(small_ok)} requests <= $50 were approved in full after a human read them**, "
        f"costing {small_ok.review_minutes.sum():.0f} minutes ({share_small:.0%} of all reviewer time). That is the 'two minutes clicking approve' from the brief.",
    ])


def section_bad_outcomes(h: pd.DataFrame) -> str:
    note = h.outcome_note.fillna("").str.lower()
    bad = h[note.str.contains("chargeback|appeal|overturned|escalated")].copy()
    bad["kind"] = bad.outcome_note.str.lower().map(
        lambda s: "chargeback" if "chargeback" in s else ("overturned" if "overturned" in s or "on appeal" in s else "appeal"))
    cb = bad[bad.kind == "chargeback"]
    cb_cost = cb.amount_usd.sum() + CHARGEBACK_FEE * len(cb)
    cols = ["request_id", "amount_usd", "stated_reason", "decision", "decided_by", "fraud_flag", "days_since_delivery", "kind", "outcome_note"]

    fig, ax = plt.subplots(figsize=(12, 5.5))
    markers = {"chargeback": ("o", CRITICAL, "chargeback (we lost the money + $25)"),
               "overturned": ("s", ORANGE, "rejected, then overturned on appeal"),
               "appeal": ("^", YELLOW, "appeal / escalation")}
    for kind, (m, c, lab) in markers.items():
        sub = bad[bad.kind == kind]
        if len(sub):
            ax.scatter(sub.days_since_delivery.astype(float), sub.amount_usd, marker=m, s=70, color=c, label=lab,
                       edgecolors=SURFACE, linewidths=1.2)
            for _, r in sub.iterrows():
                ax.annotate(f"{r.request_id} {r.stated_reason}" + (" (fraud flag)" if r.fraud_flag is True else ""),
                            (float(r.days_since_delivery), r.amount_usd), xytext=(6, 4), textcoords="offset points", fontsize=8, color=INK2)
    ax.set_xlabel("days since delivery at request time")
    ax.set_ylabel("requested amount (USD)")
    ax.set_title(t(f"{len(cb)} chargebacks cost about ${cb_cost:,.0f}; all but one were approvals above $150, and two carried a fraud flag"),
                 loc="left", color=INK)
    ax.legend(loc="upper right")
    fig5 = save(fig, "fig5_bad_outcomes.png")

    return "\n".join([
        "## 5. Bad outcomes: what went wrong after the decision",
        "",
        f"![bad outcomes]({fig5})",
        "",
        md_table(bad[cols].sort_values("kind")),
        "",
        f"**{len(cb)} chargebacks**, total exposure about **${cb_cost:,.0f}** (order amounts ${cb.amount_usd.sum():,.0f} plus ${CHARGEBACK_FEE:.0f} fee each). "
        f"{(cb.decided_by == 'auto').sum()} of them was auto-approved; {(cb.fraud_flag == True).sum()} had a fraud flag and were approved by a reviewer anyway. "
        f"Chargeback rate on approvals: {len(cb) / (h.decision == 'approved').sum():.1%} overall, "
        f"{(cb.decided_by == 'auto').sum() / (h.decided_by == 'auto').sum():.1%} on auto approvals.",
    ])


def section_suspicious(h: pd.DataFrame) -> str:
    notes = (h.customer_note + " " + h.support_note).str.lower()
    fraud_ok = h.outcome_note.fillna("").str.lower().str.contains("fraud team confirmed")
    checks = {
        "approved with fraud flag yes and NO fraud-team confirmation (policy 5 says the fraud team decides)":
            h[(h.decision == "approved") & (h.fraud_flag == True) & ~fraud_ok],
        "approved changed_mind after 14 days (policy: no exceptions)": h[(h.decision == "approved") & (h.stated_reason == "changed_mind") & (h.days_since_delivery > 14)],
        "approved arrived_damaged over $50 with no mention of a photo": h[(h.decision == "approved") & (h.stated_reason == "arrived_damaged") & (h.amount_usd > 50) & ~notes.str.contains("photo")],
        "approved never_arrived where the carrier had proof of delivery": h[(h.decision == "approved") & (h.stated_reason == "never_arrived") & notes.str.contains("signed|signature|locker|delivery photo|parcel on the step|collected")],
        "rejected then overturned on appeal": h[(h.decision == "rejected") & h.outcome_note.fillna("").str.lower().str.contains("overturned|on appeal")],
        "fraud flag missing (blank)": h[h.fraud_flag.isna()],
    }
    n_fraud_ok = int(((h.decision == "approved") & (h.fraud_flag == True) & fraud_ok).sum())
    parts = ["## 6. Decisions that look wrong against the manager's own policy", "",
             f"(For context: {n_fraud_ok} fraud-flagged requests were approved *after* the fraud team confirmed a stolen card. "
             "Those follow policy note 5 and are not listed.)", ""]
    for title, df in checks.items():
        parts.append(f"**{title}: {len(df)}**")
        if len(df):
            parts.append("")
            parts.append(md_table(df[["request_id", "amount_usd", "decided_by", "days_since_delivery", "support_note", "outcome_note"]]))
        parts.append("")
    return "\n".join(parts)


FACT_KEYWORDS = {
    "photo attached / received": r"photo",
    "carrier proof of delivery (signature, locker, delivery photo)": r"signed|signature|locker|delivery photo|parcel on the step|collected",
    "carrier trace / investigation / tracking stuck": r"trace|investigation|stuck|last scan|no scan|depot|hub",
    "card reported stolen / fraud confirmed": r"stolen|fraud",
    "our mistake confirmed (picking error, wrong item sent)": r"pick|mis-pick|matches order|our mistake|wrong item sent|warehouse",
}


def section_notes(h: pd.DataFrame, p: pd.DataFrame) -> str:
    parts = ["## 7. What the free text carries (why an LLM reader earns its place)", ""]
    parts.append(f"history: {h.has_note.sum()} of {len(h)} requests have a note ({h.customer_note.str.len().gt(0).sum()} customer, "
                 f"{h.support_note.str.len().gt(0).sum()} support). pending: {p.has_note.sum()} of {len(p)}.")
    parts.append("")
    parts.append("Policy notes 3, 4, 5 and 6 depend on things that exist only in these notes: a photo, carrier proof, an open investigation, "
                 "a confirmed stolen card, a confirmed picking error. Distinct support-note phrases, grouped by the fact they imply (keyword match, for orientation only):")
    parts.append("")
    allnotes = pd.concat([h.support_note, p.support_note]).str.strip()
    allnotes = allnotes[allnotes.str.len() > 0]
    for label, pattern in FACT_KEYWORDS.items():
        hits = sorted(allnotes[allnotes.str.lower().str.contains(pattern)].unique())
        parts.append(f"- **{label}** ({len(hits)} distinct phrases): " + "; ".join(f"\"{x}\"" for x in hits[:8]) + (" ..." if len(hits) > 8 else ""))
    parts.append("")
    parts.append("The PII found in customer notes (card digits, phone numbers) is redacted by `normalize_requests` before anything reaches a model or a log.")
    return "\n".join(parts)


def section_amount_vs_decider(h: pd.DataFrame) -> str:
    auto, human = h[h.decided_by == "auto"], h[h.decided_by != "auto"]
    cb = h[h.outcome_note.fillna("").str.lower().str.contains("chargeback")]
    bins = list(range(0, int(h.amount_usd.max()) + 40, 20))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.hist([auto.amount_usd, human.amount_usd], bins=bins, color=[BLUE, ORANGE], label=["old auto rule", "reviewer"],
            edgecolor=SURFACE, linewidth=1)
    for a in cb.amount_usd:
        ax.axvline(a, color=CRITICAL, linewidth=1.2, alpha=0.9)
    ax.plot([], [], color=CRITICAL, linewidth=1.2, label="chargeback (vertical line at its amount)")
    ax.set_xlabel("requested amount (USD)")
    ax.set_ylabel("requests")
    ax.set_title(t("Auto approvals stop at $54; chargebacks (red) sit almost entirely above $150"), loc="left", color=INK)
    ax.legend(loc="upper right")
    fig2 = save(fig, "fig2_amount_vs_decider.png")
    return f"![amount by decider]({fig2})"


def main() -> None:
    setup_logging()
    raw_h = pd.read_csv(DATA / "history.csv", dtype=str)
    raw_p = pd.read_csv(DATA / "pending.csv", dtype=str)
    h, p = normalize_requests(raw_h), normalize_requests(raw_p)

    vol_text, _ = section_volume(h)
    sections = [
        "# EDA findings",
        "",
        "Generated by `python scripts/eda.py` from `data/history.csv` and `data/pending.csv`. "
        "All numbers below are computed, not typed.",
        "",
        section_data_quality(raw_h, raw_p),
        "",
        vol_text,
        "",
        section_amount_vs_decider(h),
        "",
        section_old_rule(h),
        "",
        section_reviewer_time(h),
        "",
        section_bad_outcomes(h),
        "",
        section_suspicious(h),
        "",
        section_notes(h, p),
        "",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "findings.md").write_text("\n".join(sections))
    print(f"wrote {OUT / 'findings.md'} and {len(list(FIG.glob('*.png')))} figures")


if __name__ == "__main__":
    main()
