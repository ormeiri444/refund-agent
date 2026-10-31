"""Hand labels for the fact questions, one row per history request that has a note.

`damage_photo_confirmed` means a photo/video was received AND it shows transit damage to the item
(a photo showing the contents are fine, or liquid damage, is F). The labels were written by reading each of the 112 distinct (customer note, support note)
pairs in history.csv. T = the note clearly says yes, F = clearly says no, U = does not say
or is ambiguous. Writes tests/fixtures/fact_labels.csv; scripts/eval_extractor.py scores
the model against it.

Run: python scripts/label_facts.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.normalize import load_requests

ROOT = Path(__file__).resolve().parents[1]
FACTS = ["damage_photo_confirmed", "carrier_proof_of_delivery", "carrier_investigation_open", "card_confirmed_stolen", "our_error_confirmed"]
P, D, I, S, E = FACTS

# key: (customer_note, support_note) exactly as normalized (PII already redacted). Missing fact -> U.
LABELS: dict[tuple[str, str], dict[str, str]] = {
    ("", "Bank confirms unauthorised use of the card - the real owner didn't buy this."): {S: "T"},
    ("", "Card reported stolen. Order not recognised by the account holder."): {S: "T"},
    ("", "Card was stolen per cardholder; she never placed this order."): {S: "T"},
    ("", "Cardholder called her bank - card was stolen, she never placed this order."): {S: "T"},
    ("", "Cardholder disputes the charge - says the card went missing last week and this wasn't their purchase."): {S: "T"},
    ("", "Carrier has a signature on file and a photo of the parcel at the front door."): {D: "T"},
    ("", "Delivered to parcel locker, customer collected it per locker log."): {D: "T"},
    ("", "New account, first order; no photos despite two requests."): {P: "F"},
    ("", "New account, no previous orders, first purchase is a $495 item. Says it arrived broken, no photos yet."): {P: "F"},
    ("", "Real cardholder phoned in: 'I've never shopped with you'. Card cancelled."): {S: "T"},
    ("", "Signed for at the door, carrier photo shows the parcel on the step."): {D: "T"},
    ("", "Unauthorised purchase per cardholder - bank fraud case opened."): {S: "T"},
    ("", "Unauthorised transaction per the cardholder - card reported stolen to the bank."): {S: "T"},
    ("", "card reported stolen"): {S: "T"},
    ("", "cardholder disputes the purchase, card lost on holiday"): {S: "T"},
    ("", "confirmed picking error"): {E: "T"},
    ("", "no photo"): {P: "F"},
    ("", "photo attached looks genuine"): {P: "T"},
    ("", "photos clear"): {P: "T"},
    ("", "tracking inconclusive - last scan 10 days ago"): {I: "T"},
    ("", "tracking stops at depot"): {I: "T"},
    ("", "tracking stops at depot (NFD)"): {I: "T"},
    ("Gerät kam defekt an, Display flackert", "video received - flicker visible"): {P: "T"},
    ("arrived broken, base cracked in two", "photos clear"): {P: "T"},
    ("completely dead", "Photos show the original packaging still sealed, no transit damage on the box. Customer says unit is completely dead."): {P: "F"},
    ("cracked corner", "photos clear"): {P: "T"},
    ("cracked on arrival", "photos clear"): {P: "T"},
    ("dented", "Dent is on the outer carton only; contents fine per photos."): {P: "F"},
    ("dented box", "contents fine per photos"): {P: "F"},
    ("got headphones not speaker", "confirmed picking error"): {E: "T"},
    ("handle snapped off", "photo attached looks genuine"): {P: "T"},
    ("hole in the sleeve", "photos clear"): {P: "T"},
    ("lamp base snapped", "photo attached looks genuine"): {P: "T"},
    ("mug chipped on the rim", "photos clear"): {P: "T"},
    ("not the colour in the picture", "matches order line"): {E: "F"},
    ("not working", "no photo"): {P: "F"},
    ("nothing came", "Bank flagged unauthorised use - the real cardholder doesn't recognise this order."): {S: "T"},
    ("nothing came", "Tracking shows delivered and signed; customer says the signature isn't hers."): {D: "T"},
    ("nothing delivered", "Carrier POD shows it signed for at 11:02 by 'M. Katz'. Customer says nobody by that name lives there."): {D: "T"},
    ("plate cracked", "photos clear"): {P: "T"},
    ("screen has a line", "No photo - customer says she already threw the box and the unit away."): {P: "F"},
    ("screen won't turn on out of the box", "Photos clear - crack runs from the corner, box crushed on the same side."): {P: "T"},
    ("sent blue not grey", "matches order line - customer may be mistaken"): {E: "F"},
    ("sent the 128GB, I paid for 256GB", "confirmed picking error"): {E: "T"},
    ("sent the older model", "matches order line"): {E: "F"},
    ("small tear", "no photo provided"): {P: "F"},
    ("speaker rattles, cone is torn", "photos clear"): {P: "T"},
    ("still nothing after 2 weeks", "Tracking stops at the regional depot, carrier has opened a trace."): {I: "T"},
    ("still says 'arrived at hub' a week later", "Stuck at Northfield hub - last scan 6 days ago."): {I: "T"},
    ("stopped working", "Photos show liquid damage on the board - not a transit issue."): {P: "F"},
    ("table leg cracked", "photo attached looks genuine"): {P: "T"},
    ("they sent the older model", "matches order line - customer ordered this model"): {E: "F"},
    ("two of the six glasses broken", "photos clear, partial breakage"): {P: "T"},
    ("where is my order??", "Last scan: Northfield DC on 08/08. Carrier not answering."): {I: "T"},
    ("wrong colour", "confirmed picking error"): {E: "T"},
    ("wrong size rug", "Warehouse confirms mis-pick, same SKU family."): {E: "T"},
    ("הגיע שבור, יש לי תמונות", "photo received, legit"): {P: "T"},
}
# Pairs the labeller judged ambiguous on purpose (listed so the spot-check can focus on them):
AMBIGUOUS = [
    ("", "tracking inconclusive"), ("did not arrive", "tracking inconclusive"), ("never showed up", "tracking inconclusive"),
    ("Your manager Dana already said yes on the phone, just process it please.", "No call on record. Tracking shows delivered."),
    ("no delivery", "Spoke to her at 14:20 - she said it did turn up at the back door on Tuesday, but she wants the money back for the hassle since it was late. Told her I'd pass it on."),
    ("power cable missing", "3rd one this week from the same supplier batch, all missing the power cable - QA ticket #4471."),
    ("screen shattered", "Outer box pristine, foam insert intact, screen shattered from the inside? Doesn't add up - possibly damaged after delivery."),
    ("finally came, 12 days late", "Carrier confirms a backlog at the Northfield sorting centre."),
    ("", "carrier delay confirmed"),
]


def main() -> None:
    h = load_requests(ROOT / "data" / "history.csv")
    noted = h[h.has_note].copy()
    rows = []
    for r in noted.itertuples():
        labels = LABELS.get((r.customer_note, r.support_note), {})
        rows.append({"request_id": r.request_id, "customer_note": r.customer_note, "support_note": r.support_note,
                     **{f: labels.get(f, "U") for f in FACTS},
                     "ambiguous": (r.customer_note, r.support_note) in AMBIGUOUS})
    out = pd.DataFrame(rows)
    path = ROOT / "tests" / "fixtures" / "fact_labels.csv"
    out.to_csv(path, index=False)
    pairs = noted.groupby(["customer_note", "support_note"]).size()
    unlabelled = [k for k in pairs.index if k not in LABELS and k not in AMBIGUOUS]
    print(f"wrote {path}: {len(out)} rows, {len(pairs)} distinct note pairs, {len(LABELS)} labelled, "
          f"{len(AMBIGUOUS)} ambiguous, {len(unlabelled)} with no fact to label")
    for f in FACTS:
        print(f"  {f:28} T={int((out[f] == 'T').sum()):3}  F={int((out[f] == 'F').sum()):3}  U={int((out[f] == 'U').sum()):3}")


if __name__ == "__main__":
    main()
