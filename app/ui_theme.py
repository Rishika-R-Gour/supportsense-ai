from __future__ import annotations

import html
from typing import Any

import streamlit as st


def apply_custom_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ss-ink: #16202a;
            --ss-ink-soft: #334155;
            --ss-bg: #f4f7fb;
            --ss-card: #ffffff;
            --ss-border: #d9e2ec;
            --ss-teal: #0f766e;
            --ss-blue: #2454a6;
            --ss-coral: #e4572e;
            --ss-gold: #d49b25;
            --ss-plum: #6d5dfc;
        }

        .stApp {
            background:
                linear-gradient(180deg, #f7fafc 0%, var(--ss-bg) 42%, #eef4f8 100%);
            color: var(--ss-ink);
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1280px;
        }

        section[data-testid="stSidebar"] {
            background: #101820;
            border-right: 1px solid rgba(255,255,255,.08);
        }

        section[data-testid="stSidebar"] * {
            color: #edf4f2;
        }

        section[data-testid="stSidebar"] div[data-baseweb="select"] *,
        section[data-testid="stSidebar"] input,
        section[data-testid="stSidebar"] textarea {
            color: var(--ss-ink) !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
        }

        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] *,
        section[data-testid="stSidebar"] div[data-testid="stFileUploaderDropzone"] button {
            color: var(--ss-ink) !important;
        }

        section[data-testid="stSidebar"] [aria-label="Upload support tickets CSV"] {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
        }

        section[data-testid="stSidebar"] [aria-label="Upload support tickets CSV"] * {
            color: var(--ss-ink) !important;
        }

        section[data-testid="stSidebar"] [data-testid="stAlert"] {
            background: rgba(15, 118, 110, .16);
            border: 1px solid rgba(45, 212, 191, .35);
            border-radius: 8px;
        }

        .ss-hero {
            display: grid;
            grid-template-columns: minmax(0, 1.4fr) minmax(280px, .7fr);
            gap: 1rem;
            align-items: stretch;
            background: #16202a;
            border: 1px solid #263849;
            border-radius: 8px;
            padding: 1.35rem;
            margin-bottom: 1rem;
            box-shadow: 0 18px 48px rgba(20, 32, 42, .18);
        }

        .ss-eyebrow {
            color: #7dd3c7;
            font-size: .76rem;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-weight: 800;
            margin-bottom: .45rem;
        }

        .ss-hero h1 {
            color: #ffffff;
            font-size: 2.55rem;
            line-height: 1.06;
            margin: 0 0 .55rem;
            letter-spacing: 0;
        }

        .ss-hero p {
            color: #cdd7df;
            font-size: 1rem;
            max-width: 760px;
            margin: 0;
        }

        .ss-chip-row {
            display: flex;
            gap: .5rem;
            flex-wrap: wrap;
            margin-top: 1rem;
        }

        .ss-chip {
            display: inline-flex;
            align-items: center;
            min-height: 30px;
            border-radius: 999px;
            padding: .32rem .62rem;
            font-size: .78rem;
            font-weight: 700;
            color: #e8f8f5;
            border: 1px solid rgba(255,255,255,.14);
            background: rgba(255,255,255,.08);
        }

        .ss-signal-panel {
            background: #f8fafc;
            border-radius: 8px;
            padding: 1rem;
            display: grid;
            align-content: center;
            gap: .72rem;
        }

        .ss-signal {
            border-left: 5px solid var(--ss-teal);
            padding-left: .72rem;
        }

        .ss-signal:nth-child(2) { border-color: var(--ss-coral); }
        .ss-signal:nth-child(3) { border-color: var(--ss-gold); }

        .ss-signal-label {
            color: var(--ss-ink-soft);
            font-size: .75rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .06em;
        }

        .ss-signal-value {
            color: var(--ss-ink);
            font-size: .95rem;
            font-weight: 800;
            margin-top: .12rem;
        }

        .ss-kpi-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(130px, 1fr));
            gap: .72rem;
            margin: .75rem 0 1.2rem;
        }

        .ss-kpi-card {
            background: var(--ss-card);
            border: 1px solid var(--ss-border);
            border-radius: 8px;
            padding: .9rem .95rem;
            box-shadow: 0 8px 26px rgba(15, 23, 42, .06);
            min-height: 110px;
            position: relative;
            overflow: hidden;
        }

        .ss-kpi-card::before {
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 4px;
            background: var(--accent);
        }

        .ss-kpi-label {
            color: var(--ss-ink-soft);
            font-size: .78rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .06em;
        }

        .ss-kpi-value {
            color: var(--ss-ink);
            font-size: 1.85rem;
            font-weight: 850;
            margin-top: .42rem;
            line-height: 1.05;
        }

        .ss-lens-card {
            background: #ffffff;
            border: 1px solid var(--ss-border);
            border-left: 6px solid var(--ss-teal);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 8px 26px rgba(15, 23, 42, .05);
        }

        .ss-control-strip {
            background: #ffffff;
            border: 1px solid var(--ss-border);
            border-radius: 8px;
            padding: .85rem 1rem;
            margin: .75rem 0 1rem;
            box-shadow: 0 8px 26px rgba(15, 23, 42, .05);
        }

        .ss-control-label {
            color: var(--ss-ink-soft);
            font-size: .76rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: .08em;
            margin-bottom: .35rem;
        }

        div[role="radiogroup"] {
            gap: .85rem;
        }

        .ss-lens-card[data-lens="Product"] { border-left-color: var(--ss-blue); }
        .ss-lens-card[data-lens="Support"] { border-left-color: var(--ss-coral); }

        .ss-lens-meta {
            color: var(--ss-ink-soft);
            font-size: .74rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .08em;
            margin-bottom: .28rem;
        }

        .ss-lens-title {
            color: var(--ss-ink);
            font-size: 1.05rem;
            font-weight: 850;
            margin-bottom: .85rem;
        }

        .ss-mini-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(120px, 1fr));
            gap: .65rem;
        }

        .ss-mini-metric {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: .7rem;
        }

        .ss-mini-label {
            color: var(--ss-ink-soft);
            font-size: .72rem;
            font-weight: 800;
        }

        .ss-mini-value {
            color: var(--ss-ink);
            font-size: 1rem;
            font-weight: 850;
            margin-top: .22rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--ss-border);
            border-radius: 8px;
            box-shadow: 0 8px 26px rgba(15, 23, 42, .05);
            background: #ffffff;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: .45rem;
            background: #e8eef5;
            border: 1px solid #d6e0ea;
            padding: .35rem;
            border-radius: 8px;
        }

        .stTabs [data-baseweb="tab"] {
            border-radius: 7px;
            color: var(--ss-ink-soft);
            font-weight: 800;
            min-height: 38px;
            padding: .35rem .85rem;
        }

        .stTabs [aria-selected="true"] {
            background: #ffffff;
            color: var(--ss-ink);
            box-shadow: 0 5px 14px rgba(15, 23, 42, .08);
        }

        div[data-testid="stExpander"] {
            border: 1px solid var(--ss-border);
            border-radius: 8px;
            background: #ffffff;
        }

        .stDataFrame {
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--ss-border);
        }

        button[kind="primary"], div.stButton > button, div[data-testid="stFormSubmitButton"] button {
            background: var(--ss-teal);
            color: white;
            border: 1px solid rgba(255,255,255,.12);
            border-radius: 8px;
            font-weight: 800;
        }

        h2, h3 {
            color: var(--ss-ink);
            letter-spacing: 0;
        }

        @media (max-width: 900px) {
            .ss-hero {
                grid-template-columns: 1fr;
            }

            .ss-kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .ss-kpi-card {
                min-height: 96px;
            }

            .ss-kpi-value {
                font-size: 1.55rem;
            }

            .ss-mini-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_product_header(provider: str, theme_method: str) -> None:
    st.html(
        f"""
        <section class="ss-hero">
            <div>
                <div class="ss-eyebrow">AI Customer Support Analyzer</div>
                <h1>SupportSense</h1>
                <p>
                    Turn messy support tickets into cited executive insight, product priorities,
                    and automation opportunities your team can defend with source evidence.
                </p>
                <div class="ss-chip-row">
                    <span class="ss-chip">Evidence-backed</span>
                    <span class="ss-chip">Stakeholder lenses</span>
                    <span class="ss-chip">Deterministic counts</span>
                    <span class="ss-chip">CSV-ready demo</span>
                </div>
            </div>
            <aside class="ss-signal-panel">
                <div class="ss-signal">
                    <div class="ss-signal-label">Model layer</div>
                    <div class="ss-signal-value">{html.escape(provider)}</div>
                </div>
                <div class="ss-signal">
                    <div class="ss-signal-label">Theme engine</div>
                    <div class="ss-signal-value">{html.escape(theme_method)}</div>
                </div>
                <div class="ss-signal">
                    <div class="ss-signal-label">Trust layer</div>
                    <div class="ss-signal-value">Source ticket drill-down</div>
                </div>
            </aside>
        </section>
        """
    )


def render_kpi_cards(kpis: dict[str, Any]) -> None:
    cards = [
        ("Tickets", kpis["total_tickets"], "#0f766e"),
        ("High/Critical", f"{kpis['critical_high_pct']}%", "#e4572e"),
        ("Avg CSAT", kpis["avg_csat"], "#2454a6"),
        ("Median Resolve", f"{kpis['median_resolution_hours']}h", "#d49b25"),
        ("Open Work", f"{kpis['open_pct']}%", "#6d5dfc"),
    ]
    body = "".join(
        f"""
        <div class="ss-kpi-card" style="--accent:{accent}">
            <div class="ss-kpi-label">{html.escape(label)}</div>
            <div class="ss-kpi-value">{html.escape(str(value))}</div>
        </div>
        """
        for label, value, accent in cards
    )
    st.html(f'<section class="ss-kpi-grid">{body}</section>')


def render_lens_card(audience: str, brief: str, top_theme: str, urgent_count: int, enterprise_urgent: int) -> None:
    st.html(
        f"""
        <section class="ss-lens-card" data-lens="{html.escape(audience)}">
            <div class="ss-lens-meta">{html.escape(audience)} lens</div>
            <div class="ss-lens-title">{html.escape(brief)}</div>
            <div class="ss-mini-grid">
                <div class="ss-mini-metric">
                    <div class="ss-mini-label">Top theme</div>
                    <div class="ss-mini-value">{html.escape(top_theme)}</div>
                </div>
                <div class="ss-mini-metric">
                    <div class="ss-mini-label">Urgent tickets</div>
                    <div class="ss-mini-value">{urgent_count}</div>
                </div>
                <div class="ss-mini-metric">
                    <div class="ss-mini-label">Enterprise urgent</div>
                    <div class="ss-mini-value">{enterprise_urgent}</div>
                </div>
            </div>
        </section>
        """
    )
