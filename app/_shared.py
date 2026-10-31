"""Helpers shared by the Streamlit pages: fact provider, policy, formatting."""
from __future__ import annotations

import streamlit as st

from src import settings
from src.app_settings import MODEL_CHOICES, AppSettings, load_app_settings, save_app_settings
from src.llm.client import LLMClient
from src.llm.extractor import FactExtractor
from src.logging_setup import setup_logging
from src.policy.engine import unknown_fact_provider
from src.policy.store import list_versions, load_policy
from src.schemas import Policy

setup_logging()


def get_fact_provider():
    """The LLM reads notes only when a key is set; otherwise every note-based fact is unknown."""
    client = LLMClient(model=load_app_settings().extractor_model)
    if client.available:
        return FactExtractor(client), f"notes read by {client.model}"
    return unknown_fact_provider, "no API key: note-based facts unknown, those requests go to a person"


def live_policy() -> Policy | None:
    try:
        return load_policy()
    except FileNotFoundError:
        return None


def _model_label(model: str) -> str:
    if model not in MODEL_CHOICES:
        return f"{model}  (price unknown)"
    price_in, price_out = MODEL_CHOICES[model]
    return f"{model}  (${price_in:.2f} / ${price_out:.2f} per M tokens)"


def sidebar_models() -> AppSettings:
    """Two dropdowns: which model reads notes, which translates rules. Saved to outputs/app_settings.json."""
    current = load_app_settings()
    choices = list(MODEL_CHOICES) + [m for m in (current.extractor_model, current.translator_model) if m not in MODEL_CHOICES]
    st.sidebar.markdown("**Models** (changeable here; saved)")
    extractor = st.sidebar.selectbox("Note reading (per request)", choices, index=choices.index(current.extractor_model),
                                     format_func=_model_label, key="model_extractor")
    translator = st.sidebar.selectbox("Rule translation (manager page)", choices, index=choices.index(current.translator_model),
                                      format_func=_model_label, key="model_translator")
    chosen = AppSettings(extractor_model=extractor, translator_model=translator)
    if chosen != current:
        save_app_settings(chosen)
        st.sidebar.caption("saved")
    return chosen


def sidebar_status() -> None:
    policy = live_policy()
    sidebar_models()
    _, facts_label = get_fact_provider()
    st.sidebar.markdown("**Policy in force**")
    st.sidebar.write(f"v{policy.version}" if policy else "none")
    st.sidebar.caption(policy.changelog if policy else "")
    st.sidebar.markdown("**Note reading**")
    st.sidebar.caption(facts_label)
    st.sidebar.caption(f"versions on disk: {', '.join(f'v{v}' for v in list_versions())}")


def money(x) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "unknown"


def fact_lines(facts_used: dict) -> list[str]:
    """facts_used from a Decision record -> readable lines with the quote that justified each."""
    out = []
    for fact_id, v in (facts_used or {}).items():
        value = v.get("value") if isinstance(v, dict) else getattr(v, "value", None)
        quote = v.get("quote", "") if isinstance(v, dict) else getattr(v, "quote", "")
        word = {True: "yes", False: "no", None: "unknown"}[value]
        out.append(f"**{fact_id.replace('_', ' ')}**: {word}" + (f' — "{quote}"' if quote else ""))
    return out
