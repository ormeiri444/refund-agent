"""Turn the messy CSV rows into clean, typed rows the engine can trust.

The data dictionary says what each column *should* hold; this module makes it so,
and reports what it had to fix. Free text is PII-redacted here so nothing
downstream (LLM, logs, UI) ever sees a card number or phone number.
"""
from __future__ import annotations

import re

import pandas as pd

from src.logging_setup import get_logger

log = get_logger("normalize")

CANONICAL_REASONS: frozenset[str] = frozenset({
    "wrong_size", "changed_mind", "arrived_damaged", "wrong_item", "never_arrived", "late_delivery",
})

REASON_ALIASES: dict[str, str] = {
    "changed mind": "changed_mind",
    "damaged": "arrived_damaged",
    "arrived damaged": "arrived_damaged",
    "late": "late_delivery",
    "wrong item": "wrong_item",
    "wrong size": "wrong_size",
    "never arrived": "never_arrived",
    "late delivery": "late_delivery",
}

_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}

INT_COLUMNS = ["tenure_months", "prior_refunds_12m", "days_since_delivery"]
NOTE_COLUMNS = ["customer_note", "support_note"]

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_PHONE = re.compile(r"\+\d(?:[ \-]?\d){7,}")              # international format with leading +
_RE_LONG_DIGITS = re.compile(r"(?<![\d+])\d(?:[ \-]?\d){7,}")  # 8+ digits: card numbers, bare phones


def _clean_str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s if s else None


def normalize_fraud_flag(value) -> bool | None:
    s = _clean_str(value)
    if s is None:
        return None
    s = s.lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


def parse_amount(value) -> float | None:
    s = _clean_str(value)
    if s is None:
        return None
    s = re.sub(r"(?i)usd", "", s).replace("$", "").replace(" ", "")
    # "42,5" -> decimal comma; "1,250.50" -> thousands comma
    if re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        amount = float(s)
    except ValueError:
        return None
    return amount if amount >= 0 else None


def normalize_reason(value) -> str | None:
    s = _clean_str(value)
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s.lower())
    return REASON_ALIASES.get(s, s)


_RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value) -> pd.Timestamp | None:
    """Accept YYYY-MM-DD, ISO datetimes (with T/Z), and DD/MM/YYYY. Returns a date (no time) or None."""
    s = _clean_str(value)
    if s is None:
        return None
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        ts = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    else:
        ts = pd.to_datetime(s, errors="coerce", utc=True)
        if not pd.isna(ts):
            ts = ts.tz_convert(None)
    return None if pd.isna(ts) else ts.normalize()


def redact_pii(text: str) -> str:
    if not text:
        return text
    text = _RE_EMAIL.sub("[email]", text)
    text = _RE_PHONE.sub("[phone]", text)
    text = _RE_LONG_DIGITS.sub("[digits]", text)
    return text


def _has_pii(text) -> bool:
    s = _clean_str(text)
    return bool(s) and redact_pii(s) != s


def _source(request_id) -> str:
    s = _clean_str(request_id) or ""
    if s.startswith("RF-1"):
        return "web_form"
    if s.startswith("RF-2"):
        return "support_desk"
    return "unknown"


def find_issues(raw: pd.DataFrame) -> dict[str, int]:
    """Count the ways the raw file departs from the data dictionary."""
    amounts = raw["amount_usd"]
    reasons = raw["stated_reason"].map(_clean_str)
    cats = raw["category"].map(_clean_str)
    flags = raw["fraud_flag"].map(_clean_str)
    dup_ids = raw.loc[raw["request_id"].duplicated(), "request_id"].unique()
    conflicting = sum(
        1 for rid in dup_ids if len(raw[raw["request_id"] == rid].drop_duplicates()) > 1
    )
    return {
        "duplicate_request_id": int(raw["request_id"].duplicated().sum()),
        "duplicate_request_id_conflicting": int(conflicting),
        "amount_unparseable": int(amounts.map(parse_amount).isna().sum()),
        "amount_whitespace": int(amounts.map(lambda v: _clean_str(v) is not None and str(v) != str(v).strip()).sum()),
        "fraud_flag_nonstandard": int(flags.map(lambda v: v is not None and v not in {"yes", "no"}).sum()),
        "missing_fraud_flag": int(flags.isna().sum()),
        "reason_alias": int(reasons.map(lambda v: v is not None and v not in CANONICAL_REASONS).sum()),
        "category_case": int(cats.map(lambda v: v is not None and v != v.lower()).sum()),
        "missing_tenure": int(raw["tenure_months"].map(_clean_str).isna().sum()),
        "missing_days_since_delivery": int(raw["days_since_delivery"].map(_clean_str).isna().sum()),
        "missing_customer_id": int(raw["customer_id"].map(_clean_str).isna().sum()),
        "pii_in_notes": int(sum(raw[c].map(_has_pii).sum() for c in NOTE_COLUMNS if c in raw)),
        "date_nonstandard": int(raw["requested_at"].map(
            lambda v: _clean_str(v) is not None and not _RE_ISO_DATE.match(_clean_str(v))).sum()),
    }


def normalize_requests(raw: pd.DataFrame) -> pd.DataFrame:
    """Return a clean copy: typed columns, canonical labels, redacted notes, no duplicate ids."""
    issues = find_issues(raw)
    df = raw.copy()
    conflicting_ids = {
        rid for rid in df.loc[df["request_id"].duplicated(), "request_id"].unique()
        if len(df[df["request_id"] == rid].drop_duplicates()) > 1
    }
    df = df.drop_duplicates(subset="request_id", keep="first").reset_index(drop=True)
    df["duplicate_conflict"] = df["request_id"].isin(conflicting_ids)

    df["request_id"] = df["request_id"].map(_clean_str)
    df["source"] = df["request_id"].map(_source)
    df["amount_usd"] = df["amount_usd"].map(parse_amount).astype(float)
    for col in INT_COLUMNS:
        df[col] = pd.to_numeric(df[col].map(_clean_str), errors="coerce").round().astype("Int64")
    df["fraud_flag"] = df["fraud_flag"].map(normalize_fraud_flag).astype(object)
    df["category"] = df["category"].map(lambda v: (_clean_str(v) or "").lower())
    df["payment_method"] = df["payment_method"].map(lambda v: (_clean_str(v) or "").lower())
    df["stated_reason"] = df["stated_reason"].map(normalize_reason)
    for col in NOTE_COLUMNS:
        df[col] = df[col].map(lambda v: redact_pii(_clean_str(v) or "")).astype(str)
    df["has_note"] = (df["customer_note"].str.len() > 0) | (df["support_note"].str.len() > 0)
    df["requested_at"] = pd.to_datetime(df["requested_at"].map(parse_date))
    if "decided_at" in df:
        df["decided_at"] = pd.to_datetime(df["decided_at"], errors="coerce")
    if "review_minutes" in df:
        df["review_minutes"] = pd.to_numeric(df["review_minutes"].map(_clean_str), errors="coerce").astype(float)
    for col in ("customer_id", "decision", "decided_by", "outcome_note"):
        if col in df:
            df[col] = df[col].map(_clean_str)

    log.info("normalized %d rows (%d raw); issues=%s", len(df), len(raw), issues)
    return df


def load_requests(path) -> pd.DataFrame:
    return normalize_requests(pd.read_csv(path, dtype=str))
