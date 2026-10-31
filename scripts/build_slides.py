"""Build the presentation (8 slides, plain words) from the numbers in the repo.

Run: python scripts/build_slides.py [out.pptx]  -> docs/presentation.pptx by default
Layout rules that keep PowerPoint from drifting: at most two columns, one kind of element per column,
short sentences, generous boxes, tables with short cells and nothing placed below them in the same column.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "eda" / "figures"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "presentation.pptx"
if (OUT.parent / ("~$" + OUT.name)).exists():            # PowerPoint lock file: the deck is open, do not overwrite it
    raise SystemExit(f"{OUT} is open in PowerPoint; close it and run again")

TEAL, TEAL_DARK, SAND, INK, MUTED, CORAL, WHITE = "0F6E6E", "0A4A4A", "F1EDE4", "1B1B1B", "6B6B6B", "E4573D", "FFFFFF"
HEAD, BODY = "Cambria", "Calibri"
W, H = 13.333, 7.5
M = 0.6            # margin
COL = 5.95         # column width
COL2_X = M + COL + 0.25


def rgb(h):
    return RGBColor.from_string(h)


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
BLANK = prs.slide_layouts[6]


def shape(s, x, y, w, h, fill=None, kind=MSO_SHAPE.RECTANGLE):
    sh = s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill:
        sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def text(s, x, y, w, h, paras, size=14, color=INK, bold=False, font=BODY, align=PP_ALIGN.LEFT, gap=6, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05); tf.margin_top = tf.margin_bottom = Inches(0.03)
    if isinstance(paras, str):
        paras = [(paras, {})]
    for i, (t, o) in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = o.get("align", align); p.space_after = Pt(o.get("gap", gap))
        r = p.add_run(); r.text = t
        f = r.font; f.size = Pt(o.get("size", size)); f.bold = o.get("bold", bold)
        f.color.rgb = rgb(o.get("color", color)); f.name = o.get("font", font)
    return tb


def title(s, t, dark=False):
    text(s, M, 0.4, W - 2 * M, 0.75, t, size=28, bold=True, font=HEAD, color=WHITE if dark else TEAL_DARK)


def bullets(s, x, y, w, h, items, size=13):
    text(s, x, y, w, h, [("•  " + it, {"size": size, "gap": 8}) for it in items])


def card(s, x, y, w, h, heading, items, size=13, head_color=TEAL_DARK):
    shape(s, x, y, w, h, fill=SAND, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + 0.25, y + 0.15, w - 0.5, 0.45, heading, size=16, bold=True, font=HEAD, color=head_color)
    bullets(s, x + 0.25, y + 0.7, w - 0.5, h - 0.85, items, size=size)


def stat(s, x, y, w, number, label, color=TEAL):
    shape(s, x, y, w, 1.5, fill=SAND, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + 0.2, y + 0.1, w - 0.4, 0.65, number, size=28, bold=True, font=HEAD, color=color)
    text(s, x + 0.2, y + 0.78, w - 0.4, 0.65, label, size=11, color=MUTED, gap=0)


def table(s, x, y, w, rows, widths, size=11):
    shp = s.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(0.32 * len(rows)))
    tbl = shp.table
    for i, cw in enumerate(widths):
        tbl.columns[i].width = Inches(cw)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = str(val)
            cell.margin_left = cell.margin_right = Inches(0.06); cell.margin_top = cell.margin_bottom = Inches(0.03)
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(size); p.font.name = BODY; p.font.bold = r == 0
            p.font.color.rgb = rgb(WHITE if r == 0 else INK)
            cell.fill.solid(); cell.fill.fore_color.rgb = rgb(TEAL if r == 0 else (SAND if r % 2 else WHITE))
    return shp


def picture(s, path, x, y, w):
    pic = s.shapes.add_picture(str(path), Inches(x), Inches(y), width=Inches(w))
    return y + pic.height / 914400          # bottom edge in inches


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


def node(s, x, y, w, h, heading, sub, fill=SAND, head_color=TEAL_DARK, size=11):
    """One box of a flow diagram: bold heading, muted detail under it."""
    shape(s, x, y, w, h, fill=fill, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + 0.15, y + 0.08, w - 0.3, h - 0.16, [
        (heading, {"size": 13, "bold": True, "font": HEAD, "color": head_color, "gap": 3}),
        (sub, {"size": size, "color": INK if fill == SAND else WHITE, "gap": 0}),
    ])


def arrow(s, x, y, w, h, kind=MSO_SHAPE.DOWN_ARROW, fill=TEAL):
    shape(s, x, y, w, h, fill=fill, kind=kind)


def panel(s, x, y, w, h, heading, body, head_color=TEAL_DARK, size=12):
    """A card with running text instead of bullets."""
    shape(s, x, y, w, h, fill=SAND, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    text(s, x + 0.25, y + 0.15, w - 0.5, 0.45, heading, size=16, bold=True, font=HEAD, color=head_color)
    text(s, x + 0.25, y + 0.65, w - 0.5, h - 0.8, [(b, {"size": size, "gap": 6}) for b in body])


# ---------------------------------------------------------------- 1. the process today
s = prs.slides.add_slide(BLANK)
shape(s, 0, 0, W, H, fill=TEAL_DARK)
text(s, M, 0.45, W - 2 * M, 0.7, "Refund requests: let rules take the easy ones", size=32, bold=True, font=HEAD, color=WHITE)
text(s, M, 1.2, W - 2 * M, 0.45, "What happens today, from 3 months of real decisions (248 requests)", size=14, color=SAND)
stat(s, M, 1.9, 2.85, "45%", "of requests were approved by an old automatic rule nobody remembers. Only 14% of the money.", color=TEAL_DARK)
stat(s, M + 3.1, 1.9, 2.85, "8 min", "is what a person spends per request. 1,119 minutes in the sample, 4 reviewers.", color=TEAL_DARK)
stat(s, M, 3.6, 2.85, "8", "chargebacks: the bank took the money back after we refunded. About $2,519 lost.", color=CORAL)
stat(s, M + 3.1, 3.6, 2.85, "22", "small, clean requests went to a person only because the account was new. 21 were approved anyway.", color=TEAL_DARK)
text(s, M, 5.35, 5.95, 1.8, [
    ("Before: one queue for everything. A $20 shirt in the wrong size waits behind a $495 fraud case.", {"size": 13, "color": WHITE, "gap": 8}),
    ("After: written rules approve the safe cases. People get the rest, with the reason and the evidence. The manager changes the rules herself, and sees the effect before it goes live.", {"size": 13, "color": WHITE}),
])
bottom = picture(s, FIG / "fig4_reviewer_minutes_by_band.png", COL2_X, 1.9, COL)
text(s, COL2_X, bottom + 0.2, COL, 1.2, "Where reviewer time goes. The tiny approvals under $50 are only 6% of it. Most time goes to $50–200 requests, where the answer sits in a note: was there a photo, did the warehouse confirm a mistake.", size=12, color=SAND)
notes(s, "111 of 248 requests were decided automatically, 137 by people. Mean 8.2 minutes per human decision.")

# ---------------------------------------------------------------- 2. today's line, read off the data
s = prs.slides.add_slide(BLANK)
title(s, "Today's line, read off the data")
FW = 7.7
bottom = picture(s, FIG / "fig3_old_rule_boundary.png", M, 1.35, FW)
text(s, M, bottom + 0.15, FW, H - 0.5 - bottom - 0.15, [
    ("Where it breaks", {"size": 14, "bold": True, "font": HEAD, "color": CORAL, "gap": 4}),
    ("Everything the rule does not take sits in one queue: the $495 fraud case next to the $20 shirt. 3 fraud-flagged requests were approved without asking the fraud team; 2 of them charged back. 10 decisions went against the manager's own notes. 3 rejections were overturned on appeal; one of those customers closed the account.", {"size": 12, "color": MUTED}),
])
RX = M + FW + 0.3
card(s, RX, 1.35, W - M - RX, 5.6, "What we read off it", [
    "Nobody wrote the old rule down, so we found it in 248 past decisions: every automatic approval is $54 or less, from an account 9 months or older, with no earlier refund.",
    "It reads nothing: not the reason, not the notes, not the fraud flag beyond 'not yes'.",
    "6 requests inside that box were still decided by a person (3 approved, 3 rejected). Most carry a note, so the rule probably skips anything with free text.",
    "22 small, clean requests fell just outside it because the account was under 9 months old. A person approved 21 of them: the 'two minutes clicking approve'.",
    "111 of 248 requests (45%), but only $3,377, 14% of the money. One of its approvals charged back: $49, with no note to read.",
], size=12)
notes(s, "Figure and numbers from docs/eda/findings.md sections 3 to 6; scripts/eda.py reverse-engineers the old rule as the tightest box around every auto-decided request.")

# ---------------------------------------------------------------- 3. the new line
s = prs.slides.add_slide(BLANK)
title(s, "The new line: her notes set the rules, the data sets the numbers")
table(s, M, 1.35, COL, [
    ["the manager wrote", "what the rules do"],
    ["1. small stuff from good customers goes through", "up to $200 with no red flag: approve (numbers on the right)"],
    ["2. change of mind: 14 days, no exceptions", "within 14 days: approve; after: a person (the system never rejects)"],
    ["3. damage: a photo for anything over $50", "$50 or less: approve; over: only if the note says the photo shows damage"],
    ["4. never arrived: signature means reject", "always a person; a rejection is a person's call"],
    ["5. fraud flag goes to the fraud team", "fraud queue, always; a blank flag is unreadable: a person"],
    ["6. our mistake: full refund; partials are the reviewer's call", "picking error confirmed in the note: approve; late delivery: a person"],
], widths=[2.75, 3.2], size=10)
text(s, M, 4.6, COL, 2.35, [
    ("Four of the six turn on what the note says", {"size": 14, "bold": True, "font": HEAD, "color": TEAL_DARK, "gap": 4}),
    ("A photo, carrier proof, a stolen card, a confirmed picking error. Those became five yes/no questions a model answers, each with the quote it relied on; 'unknown' never approves.", {"size": 12, "gap": 8}),
    ("The replay corrected us once: the first question was 'photo attached', and it approved two claims where the photo showed the item was fine. It became 'does the photo show damage'.", {"size": 12}),
])
bottom = picture(s, FIG / "fig2_amount_vs_decider.png", COL2_X, 1.35, COL)
text(s, COL2_X, bottom + 0.15, COL, 0.4, "Numbers from the data: the cap", size=14, bold=True, font=HEAD, color=TEAL_DARK)
table(s, COL2_X, bottom + 0.6, COL, [
    ["cap", "approved alone", "reviewer minutes saved", "bad approvals a note could catch"],
    ["$54 (old)", "104 (42%)", "48", "0"],
    ["$100", "111 (45%)", "86", "0"],
    ["$150", "115 (46%)", "104", "0"],
    ["$200 (chosen)", "120 (48%)", "156", "0"],
], widths=[1.3, 1.3, 1.55, 1.8], size=10)
text(s, COL2_X, bottom + 0.6 + 0.32 * 5 + 0.15, COL, 1.2, [
    ("$200 is the highest cap with zero catchable bad approvals, and the chargebacks sit above $150. Above $150 there are only 5 past cases, so the evidence is thin; the manager can lower it with one change. Also from the data: accounts under 3 months (both fraud-flagged chargebacks were 1 to 2 months old) and customers with two earlier refunds go to a person.", {"size": 11, "color": MUTED}),
])
notes(s, "Rules: policies/v1.json, each with the policy note it comes from. Cap table and chargeback figure: docs/eda/findings.md section 8 and refund-agent backtest.")

# ---------------------------------------------------------------- 4. what we added
s = prs.slides.add_slide(BLANK)
title(s, "What we added: rules, a note reader, two screens, and a test")
Y1, H1 = 1.35, 1.6
x = M
node(s, x, Y1, 1.5, H1, "A request", "From the web form or the support desk, as a CSV."); x += 1.5
arrow(s, x + 0.05, Y1 + H1 / 2 - 0.17, 0.3, 0.34, kind=MSO_SHAPE.RIGHT_ARROW); x += 0.4
node(s, x, Y1, 2.1, H1, "Clean the file", "Fix dates, amounts, Y/N flags and reason spellings. Hide card numbers. Flag duplicate ids."); x += 2.1
arrow(s, x + 0.05, Y1 + H1 / 2 - 0.17, 0.3, 0.34, kind=MSO_SHAPE.RIGHT_ARROW); x += 0.4
RULES_X = x
node(s, x, Y1, 2.6, H1, "Written rules decide", "An ordered list in a versioned file: 7 'send to a person' rules first, 4 'approve' rules after. First match wins. Unknown never approves.", fill=TEAL_DARK, head_color=WHITE); x += 2.6
arrow(s, x + 0.05, Y1 + H1 / 2 - 0.17, 0.3, 0.34, kind=MSO_SHAPE.RIGHT_ARROW); x += 0.4
node(s, x, Y1, 2.0, 0.75, "Approve", "120 of 248 (48%); rule and quote recorded.")
node(s, x, Y1 + 0.85, 2.0, 0.75, "To a person", "128 of 248, with the reason in plain words."); x += 2.0
arrow(s, x + 0.05, Y1 + 0.85 + 0.375 - 0.17, 0.3, 0.34, kind=MSO_SHAPE.RIGHT_ARROW); x += 0.4
node(s, x, Y1, W - M - x, H1, "Two queues", "The reviewer queue, oldest first. The fraud queue for flagged cases.")
arrow(s, RULES_X + 1.3 - 0.17, Y1 + H1 + 0.06, 0.34, 0.28, kind=MSO_SHAPE.UP_ARROW)
Y2 = Y1 + H1 + 0.4
node(s, RULES_X, Y2, 2.6, 1.3, "A model reads the note, only when a rule asks",
     "Five yes/no questions, each with the quote it relied on. Answers are saved. No key means 'unknown', which goes to a person.")
text(s, M, Y2, 3.8, 1.3, [
    ("The same path on the command line and in the app.", {"size": 12, "bold": True, "color": TEAL_DARK, "gap": 4}),
    ("refund-agent decide any.csv writes one line per request: the outcome, the rule that fired, the facts it used, the rules version. Nothing in the app is a mock.", {"size": 12, "color": MUTED}),
])
text(s, RULES_X + 3.0, Y2, W - M - RULES_X - 3.0, 1.3, [
    ("Two outcomes only.", {"size": 12, "bold": True, "color": TEAL_DARK, "gap": 4}),
    ("Approve, or send to a person. The system never rejects: a wrong rejection costs an appeal and maybe the customer. Rejecting stays with people.", {"size": 12, "color": MUTED}),
])
Y3 = Y2 + 1.3 + 0.25
H3 = H - 0.5 - Y3
PW = (W - 2 * M - 0.5) / 3
panel(s, M, Y3, PW, H3, "The reviewer's screen", [
    "Why the request is here, in plain words; what the model read, with the exact quote; the customer's history; the manager's note that applies.",
    "Approve, approve part, reject, or send to the fraud team. Each goes to the log with the reviewer's name and the rules version.",
], size=11)
panel(s, M + PW + 0.25, Y3, PW, H3, "The manager's screen", [
    "She types a sentence ('anything over $300 comes to us'); the model turns it into a rule, or says why it cannot.",
    "A dry run replays old and new rules on the 248 past requests; then she publishes a new version. Rollback is one click.",
], size=11)
panel(s, M + 2 * (PW + 0.25), Y3, PW, H3, "The replay, as a test", [
    "Every version is run on the 248 decided requests, where we know what happened next.",
    "If it would approve a past bad case that a note or flag could have caught, the test fails and blocks publishing.",
], head_color=CORAL, size=11)
notes(s, "The flow is src/data/normalize.py -> src/policy/engine.py -> src/queue.py; the model is only called from the extractor. Screens are app/pages; the test is refund-agent backtest.")

# ---------------------------------------------------------------- 5. what changes
s = prs.slides.add_slide(BLANK)
title(s, "What changes: today and with the system, side by side")
table(s, M, 1.35, W - 2 * M, [
    ["", "today", "with the system"],
    ["who decides the money", "an old rule nobody remembers, then four reviewers", "written rules in a versioned file; first matching rule wins; people take the rest"],
    ["approved without a person", "111 of 248 (45%), $3,377: $54 or less, no earlier refunds, account 9 months or older", "120 of 248 (48%), $5,015: safe cases up to $200, with the notes read; 100% agreed with the final human decision"],
    ["reviewer time", "1,119 minutes over 137 requests", "963 minutes: 156 saved, and the small clean cases no longer wait"],
    ["why a request was approved", "not recorded", "the rule that fired and the quote from the note, in the decision log"],
    ["what the reviewer sees", "the raw request, in one queue with no order", "why it is here, what the model read, the customer's history, the policy note that applies; oldest first"],
    ["fraud-flagged cases", "same queue; 3 approved without the fraud team, 2 charged back", "their own queue; the rules never approve a fraud flag"],
    ["changing a rule", "find whoever set it up at IT; no way to test it first", "the manager types a sentence, sees the dry run on 248 past cases, publishes a version; rollback in one click"],
    ["catching a bad rule", "a chargeback, weeks later", "the replay before publishing; five weekly numbers and two rollback levels after"],
    ["rejecting a customer", "the reviewer's call", "unchanged: the system never rejects"],
], widths=[2.35, 4.4, 5.38], size=11)
TW = (W - 2 * M - 0.5) / 3
stat(s, M, 5.45, TW, "+$1,638", "approved without a person on the same 248 requests: 120 instead of 111, $5,015 instead of $3,377.")
stat(s, M + TW + 0.25, 5.45, TW, "156 minutes", "of reviewer time saved out of 1,119, and no small clean request waits behind a fraud case.")
stat(s, M + 2 * (TW + 0.25), 5.45, TW, "0", "bad approvals a note or flag could have caught, in the replay. The one it cannot catch is a $49 case with no note.", color=CORAL)
notes(s, "Left column from findings.md sections 2 to 6; right column from the backtest ('The line') and the two screens. Slides 5 to 7 give the detail behind each row.")

# ---------------------------------------------------------------- 6. how we'd know it's wrong
s = prs.slides.add_slide(BLANK)
title(s, "How we would know it is wrong: before switch-on, and after")
card(s, M, 1.35, COL, 2.6, "Before: the replay is a test", [
    "Every version is replayed on the 248 past requests. 'Bad' means approved, then a chargeback, a fraud flag the fraud team never confirmed, or a reviewer's no. If a note or flag could have caught it, the test fails and the change cannot be published.",
    "The model's reading of notes is checked separately on 205 notes labelled by hand (slide 7).",
], size=12)
card(s, M, 4.15, COL, 2.8, "Rollback, two levels", [
    "One bad case: a chargeback on something the system approved. The manager switches off the one rule that approved it. No engineer needed.",
    "A pattern over 4 weeks: more chargebacks on automatic approvals than people had (3.7%), or one week paying out 1.5 times the usual. She publishes a rule that sends everything to people. Same day.",
], size=12, head_color=CORAL)
text(s, COL2_X, 1.35, COL, 0.5, "After: five numbers, checked weekly", size=16, bold=True, font=HEAD, color=TEAL_DARK)
table(s, COL2_X, 1.9, COL, [
    ["number", "good looks like"],
    ["share approved automatically", "about 48%, and stable"],
    ["chargebacks on automatic approvals", "zero; below the human rate of 3.7%"],
    ["dollars approved automatically per week", "about $450; never above 1.5×"],
    ["oldest request waiting for a person", "under one working day"],
    ["appeals on reviewer rejections", "fewer than today's 3 of 24"],
], widths=[3.1, 2.85], size=11)
text(s, COL2_X, 4.3, COL, 1.5, "Honest note: 248 past requests is a small sample. The replay proves we did not repeat a known mistake; the weekly numbers are the real test.", size=12, color=MUTED)
notes(s, "Baselines come from the replay: about $450 per week approved automatically over 11 weeks of history.")

# ---------------------------------------------------------------- 7. where AI is used
s = prs.slides.add_slide(BLANK)
title(s, "Where the AI is used, where it is not, and why")
card(s, M, 1.35, COL, 2.7, "Used, for two narrow jobs", [
    "Reading notes: five yes/no questions per note, with the quote it relied on. Only when a rule needs it. Answers are saved, so a note is read once.",
    "Turning the manager's sentence into a rule. The code checks that the rule only uses things the system can measure.",
], size=12)
card(s, M, 4.25, COL, 2.7, "Deliberately not used", [
    "Deciding money. A rule gives the same answer every time and can be tested; a model does neither.",
    "Rejecting anyone. Rejections stay with people.",
    "A 'risk score' model: 248 rows is too few, and a line you can explain is worth more.",
], size=12, head_color=CORAL)
text(s, COL2_X, 1.35, COL, 0.5, "Model, cost, and how well it reads", size=16, bold=True, font=HEAD, color=TEAL_DARK)
bullets(s, COL2_X, 1.9, COL, 1.9, [
    "Claude Haiku 5.5, the small fast model. About $0.0002 per note read; most requests need no call, so under $0.0001 per decision.",
    "No API key: the answers are 'unknown' and those requests go to a person. It never approves blindly.",
], size=12)
table(s, COL2_X, 3.85, COL, [
    ["question the model answers", "when it says yes, it is right", "finds the yes cases"],
    ["photo shows the damage", "100%", "97%"],
    ["carrier has proof of delivery", "100%", "100%"],
    ["carrier opened an investigation", "100%", "76%"],
    ["card confirmed stolen", "100%", "91%"],
    ["our mistake confirmed", "100%", "100%"],
], widths=[2.75, 1.75, 1.45], size=11)
text(s, COL2_X, 5.9, COL, 1.0, "A wrong 'yes' could approve money, so that is the number that must be perfect. A missed 'yes' only sends the case to a person.", size=12, color=MUTED)
notes(s, "Checked on 205 notes labelled by hand; details and every mismatch in docs/eda/extractor_eval.md.")

# ---------------------------------------------------------------- 8. what was cut, next
s = prs.slides.add_slide(BLANK)
title(s, "What was left out, and what comes next")
card(s, M, 1.35, COL, 5.6, "Left out on purpose", [
    "Login, hosting, real payments, a real fraud-team workflow, a database, notifications.",
    "Editing an existing rule in place: today it is done by sentence, or by switching one rule off and adding another.",
    "Approval rules sit below the guard rules by default; moving one up is possible, and the red list in the dry run is the safety net.",
], size=12)
card(s, COL2_X, 1.35, COL, 5.6, "Next", [
    "A monitoring page fed by the decision logs: the five weekly numbers, with the rollback lines drawn on.",
    "Re-check a sample of the model's answers every week; alert if a question's accuracy drops.",
    "Make the engine always run guard rules before approval rules, and let one sentence become several changes ('stolen-card cases go straight through' really means: narrow the fraud guard, then add an approval).",
    "Real carrier data for signatures and traces, instead of reading support shorthand.",
    "When a reviewer overrides a routed case, suggest the rule change that would have automated it.",
], size=12, head_color=CORAL)
notes(s, "Scope was 4-6 hours; a narrow thing that runs plus a clear list of what was cut.")

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"wrote {OUT} with {len(prs.slides)} slides")
