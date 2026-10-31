import pandas as pd
import pytest

from src.data.normalize import (
    CANONICAL_REASONS,
    find_issues,
    normalize_fraud_flag,
    normalize_requests,
    parse_amount,
    redact_pii,
)

COLUMNS = [
    "request_id", "requested_at", "customer_id", "tenure_months", "prior_refunds_12m",
    "amount_usd", "category", "payment_method", "stated_reason", "customer_note",
    "support_note", "days_since_delivery", "fraud_flag", "decision", "decided_by",
    "outcome_note", "decided_at", "review_minutes",
]


def raw_with_reasons(reasons):
    rows = []
    for i, r in enumerate(reasons):
        rows.append({
            "request_id": f"RF-1{i:03d}", "requested_at": "2026-06-01", "customer_id": "CU-1",
            "tenure_months": "12", "prior_refunds_12m": "0", "amount_usd": "10", "category": "home",
            "payment_method": "card", "stated_reason": r, "customer_note": None, "support_note": None,
            "days_since_delivery": "3", "fraud_flag": "no", "decision": "pending", "decided_by": None,
            "outcome_note": None, "decided_at": None, "review_minutes": None,
        })
    return pd.DataFrame(rows, columns=COLUMNS, dtype=object)


@pytest.mark.parametrize("value,expected", [
    ("yes", True), ("Y", True), (" TRUE ", True), ("1", True),
    ("no", False), ("N", False), ("false", False), ("0", False),
    (None, None), (float("nan"), None), ("maybe", None), ("", None),
])
def test_fraud_flag_variants(value, expected):
    assert normalize_fraud_flag(value) is expected


@pytest.mark.parametrize("value,expected", [
    (" 42 ", 42.0), ("25.28", 25.28), ("$1,250.50", 1250.5), ("42,5", 42.5),
    ("USD 120.00", 120.0), ("55.00 USD", 55.0), ("usd 24.06", 24.06),
    ("", None), (None, None), ("abc", None), ("-5", None),
])
def test_amount_variants(value, expected):
    assert parse_amount(value) == expected


def test_reason_aliases():
    df = normalize_requests(raw_with_reasons(
        ["changed mind", "damaged", "late", "wrong item", "Arrived Damaged", "wrong_size"]))
    assert df.stated_reason.tolist() == [
        "changed_mind", "arrived_damaged", "late_delivery", "wrong_item", "arrived_damaged", "wrong_size"]


def test_redact_pii():
    assert redact_pii("refund to card ending 4417, call +44 7700 900123 or a@b.com") == \
        "refund to card ending 4417, call [phone] or [email]"
    assert redact_pii("card 4111 1111 1111 1111") == "card [digits]"
    once = redact_pii("x 4111 1111 1111 1111")
    assert redact_pii(once) == once


def test_duplicates_dropped(raw_history_df):
    df = normalize_requests(raw_history_df)
    assert df.request_id.is_unique
    assert (df.request_id == "RF-2111").sum() == 1
    assert len(df) == 248  # 251 rows, 3 exact-duplicate ids


def test_history_normalizes_cleanly(raw_history_df):
    df = normalize_requests(raw_history_df)
    assert df.amount_usd.dtype == float and df.amount_usd.isna().sum() == 0
    assert set(df.stated_reason.unique()) <= CANONICAL_REASONS
    assert set(df.category.unique()) == {"home", "apparel", "electronics"}
    assert set(df.fraud_flag.dropna().unique()) == {True, False}
    assert df.source.isin(["web_form", "support_desk"]).all()
    assert not df.customer_note.str.contains(r"\d{4} ?\d{4}").any()
    assert str(df.tenure_months.dtype) == "Int64" and df.tenure_months.isna().sum() == 2
    assert str(df.days_since_delivery.dtype) == "Int64"
    assert df.customer_note.map(type).eq(str).all()
    assert df.has_note.dtype == bool


def test_pending_keeps_nullable_ints(raw_pending_df):
    df = normalize_requests(raw_pending_df)
    assert str(df.tenure_months.dtype) == "Int64"
    assert len(df) == 20  # RF-2183 appears twice with different amounts; first kept
    assert df.loc[df.request_id == "RF-2183", "amount_usd"].item() == 49.0


def test_find_issues_flags_conflicting_duplicate(raw_pending_df):
    issues = find_issues(raw_pending_df)
    assert issues["duplicate_request_id"] == 1
    assert issues["duplicate_request_id_conflicting"] == 1


def test_find_issues_counts(raw_history_df):
    issues = find_issues(raw_history_df)
    assert issues["duplicate_request_id"] == 3
    assert issues["duplicate_request_id_conflicting"] == 0
    assert issues["amount_unparseable"] == 0
    assert issues["fraud_flag_nonstandard"] >= 8
    assert issues["reason_alias"] >= 6
    assert issues["category_case"] == 2
    assert issues["missing_tenure"] == 2
    assert issues["pii_in_notes"] >= 1


@pytest.mark.parametrize("value,expected", [
    ("2026-06-02", "2026-06-02"), ("2026-06-15T07:11:00Z", "2026-06-15"),
    ("09/06/2026", "2026-06-09"), ("03/08/2026", "2026-08-03"), ("", None), ("not a date", None),
])
def test_parse_date_variants(value, expected):
    from src.data.normalize import parse_date
    got = parse_date(value)
    assert (got.strftime("%Y-%m-%d") if got is not None else None) == expected


def test_history_dates_all_parse(raw_history_df):
    df = normalize_requests(raw_history_df)
    assert df.requested_at.isna().sum() == 0
    assert str(df.requested_at.dtype).startswith("datetime64")


def test_find_issues_counts_date_formats(raw_history_df):
    assert find_issues(raw_history_df)["date_nonstandard"] == 8


def test_conflicting_duplicate_is_flagged(raw_pending_df, raw_history_df):
    df = normalize_requests(raw_pending_df)
    assert df.loc[df.request_id == "RF-2183", "duplicate_conflict"].item() is True
    assert df.duplicate_conflict.sum() == 1
    assert normalize_requests(raw_history_df).duplicate_conflict.sum() == 0   # exact duplicates are not conflicts
