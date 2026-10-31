"""Build the write-up deck (8 slides, plain words) from the numbers in the repo.

Run: python scripts/build_slides.py            -> docs/writeup.pptx (or docs/writeup_v2.pptx if the first is open in PowerPoint)
Layout rules that keep PowerPoint from drifting: at most two columns, one kind of element per column,
short sentences, generous boxes, tables with short cells and nothing placed below them in the same column.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "eda" / "figures"
OUT = ROOT / "docs" / "writeup.pptx"
if (ROOT / "docs" / "~$writeup.pptx").exists():          # PowerPoint lock file: the deck is open, do not overwrite it
    OUT = ROOT / "docs" / "writeup_v2.pptx"

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

# ---------------------------------------------------------------- 2. the line
s = prs.slides.add_slide(BLANK)
title(s, "The line: what the system decides alone, and what goes to a person")
card(s, M, 1.35, COL, 5.6, "Goes to a person (checked first)", [
    "Fraud flag from the payment provider: goes to the fraud team.",
    "Anything we cannot read: blank amount, blank fraud flag, unknown account age.",
    "Over $200.",
    "Two or more refunds in the last 12 months, or an account under 3 months old.",
    "Change of mind after 14 days (the manager said: no exceptions).",
    "Never arrived, and late delivery: these need a human judgment call.",
    "The same request id twice with different details.",
])
card(s, COL2_X, 1.35, COL, 3.35, "Approved automatically (only if nothing above applies)", [
    "The warehouse confirmed we sent the wrong item.",
    "Damage claim of $50 or less.",
    "Damage claim over $50 where the note says a photo shows the damage.",
    "Wrong size, or change of mind within 14 days.",
])
card(s, COL2_X, 4.9, COL, 2.05, "Two outcomes only", [
    "Approve, or send to a person. The system never rejects: a wrong rejection costs an appeal and maybe the customer.",
    "Every automatic approval records which rule fired and which words in the note it relied on.",
])
notes(s, "The rules live in policies/v1.json: a list of yes/no questions about the notes and an ordered list of rules. First matching rule wins.")

# ---------------------------------------------------------------- 3. the evidence
s = prs.slides.add_slide(BLANK)
title(s, "The evidence: we replayed the rules on the 248 past requests")
text(s, M, 1.3, COL, 0.9, "Because we know what happened afterwards (chargebacks, appeals, the reviewer's decision), we can check every automatic approval the rules would have made.", size=13)
table(s, M, 2.3, COL, [
    ["", "old automatic rule", "our rules"],
    ["approved automatically", "111 (45%)  $3,377", "120 (48%)  $5,015"],
    ["reviewer minutes saved", "—", "156 of 1,119"],
    ["agreed with the final human decision", "—", "100%"],
    ["bad approvals we could have caught", "0", "0"],
    ["bad approvals nobody could catch", "1 ($49)", "1 ($49)"],
], widths=[2.55, 1.7, 1.7], size=11)
text(s, M, 4.45, COL, 2.5, [
    ("What 'bad' means", {"size": 14, "bold": True, "color": TEAL_DARK}),
    ("The refund was approved, and later the bank took the money back, or the fraud team was never asked about a fraud flag, or a reviewer had said no.", {"size": 12, "gap": 8}),
    ("'Could have caught' means a note or a flag was there to read. The one case nobody could catch had no note at all.", {"size": 12, "gap": 8}),
    ("The replay found a wrong rule: 'photo attached' approved two claims where the photo showed the item was fine. The rule now needs a photo that shows damage.", {"size": 12}),
])
bottom = picture(s, FIG / "fig3_old_rule_boundary.png", COL2_X, 1.3, COL)
text(s, COL2_X, bottom + 0.2, COL, 2.3, [
    ("The old rule, worked out from the data", {"size": 14, "bold": True, "color": TEAL_DARK}),
    ("Amount up to $54, no earlier refunds, account at least 9 months old. It skipped 22 small clean requests from newer accounts (21 approved anyway) and approved one later chargeback.", {"size": 12, "gap": 8}),
    ("The $200 limit is the highest one with zero catchable bad approvals. Above $150 there are only 5 past cases, so the evidence is thin; the manager can lower it with one change.", {"size": 12}),
])
notes(s, "Numbers from docs/eda/findings.md, section 'The line', generated by refund-agent backtest.")

# ---------------------------------------------------------------- 4. the two mechanisms
s = prs.slides.add_slide(BLANK)
title(s, "The two screens: the reviewer's queue, and the manager's rules")
card(s, M, 1.35, COL, 5.6, "The reviewer", [
    "What lands here: every request the rules did not take, oldest first. Fraud cases have their own filter.",
    "What they see: why it is here, in plain words. What the model read in the notes, with the exact quote. The customer's history. The manager's policy note that applies.",
    "What they can do: approve, approve part of it, reject, or send to the fraud team. Part and reject need a reason.",
    "What happens after: one line in the decision log with the reviewer's name, the time and the rules version. The request leaves the queue.",
], size=12)
card(s, COL2_X, 1.35, COL, 5.6, "The manager", [
    "Types a sentence: 'From now on, anything over $300 comes to us.' The model turns it into a rule, or explains why it cannot ('nothing in the data says if a customer is angry').",
    "Checks the rule in a form. Several changes can be collected into one new version.",
    "Dry run: the old rules and the new rules are replayed on the 248 past requests and the 20 waiting. She sees what changes, the dollars, and a red list of past bad cases the change would approve. Red blocks publishing.",
    "Publishes a new version with a note. Any old version can be brought back with one click.",
], size=12)
notes(s, "Nothing on these screens is a mock: they call the same engine and logs as the command line.")

# ---------------------------------------------------------------- 5. how we'd know it's wrong
s = prs.slides.add_slide(BLANK)
title(s, "How we would know it is wrong: before switch-on, and after")
card(s, M, 1.35, COL, 2.6, "Before: the replay is a test", [
    "If the rules would approve a past case that went bad and could have been caught, the test fails and the change cannot be published.",
    "The model's reading of notes is checked separately on 205 notes labelled by hand (next slide).",
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

# ---------------------------------------------------------------- 6. where AI is used
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

# ---------------------------------------------------------------- 7. what was cut, next
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

# ---------------------------------------------------------------- 8. appendix: the data
s = prs.slides.add_slide(BLANK)
title(s, "Appendix: the data, and what was wrong with it")
table(s, M, 1.35, COL, [
    ["problem in the file", "how many", "what we do"],
    ["same request id twice", "3 (+1 pending)", "keep the first; if details differ, a person"],
    ["fraud flag as Y, N, false, blank", "10", "read them; blank = unknown = a person"],
    ["reason spelled differently", "6", "map to the six official reasons"],
    ["amounts like 'USD 120.00'", "6", "read them; unreadable = a person"],
    ["dates in three formats", "8", "read them"],
    ["card or phone number in a note", "1", "hidden before the model or a log sees it"],
    ["reviewer went against the written policy", "10", "truth = what happened after appeals"],
], widths=[2.6, 1.15, 2.2], size=10)
bottom = picture(s, FIG / "fig5_bad_outcomes.png", COL2_X, 1.35, COL)
text(s, COL2_X, bottom + 0.2, COL, 1.5, "The bad outcomes sit above $150, on fraud flags, or on 'never arrived' claims where the carrier had a signature. Three rejections were overturned on appeal; one of those customers closed the account.", size=12, color=MUTED)
notes(s, "Everything regenerates from the repo: scripts/eda.py, refund-agent backtest, scripts/eval_extractor.py, scripts/build_slides.py.")

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"wrote {OUT} with {len(prs.slides)} slides")
