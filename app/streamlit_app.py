from __future__ import annotations

import pandas as pd
import streamlit as st

from app.analytics import compute_kpis, count_by, segment_priority_matrix, tickets_over_time, top_customer_examples
from app.charts import bar_chart, theme_chart, ticket_volume_chart
from app.chat import answer_question
from app.data_loader import filter_tickets, load_ticket_csv, sample_dataset_path
from app.llm import active_ai_provider, generate_executive_summary
from app.recommendations import build_product_recommendations, classify_automation_opportunity
from app.theme_discovery import add_theme_column, discover_themes, theme_discovery_method
from app.ui_theme import apply_custom_theme, render_kpi_cards, render_lens_card, render_product_header


st.set_page_config(page_title="SupportSense", page_icon="SS", layout="wide", initial_sidebar_state="collapsed")

SOURCE_TICKET_COLUMNS = [
    "ticket_id",
    "created_at",
    "customer_name",
    "customer_segment",
    "priority",
    "product_area",
    "subject",
    "description",
    "csat_score",
]

AUDIENCE_OPTIONS = ["CEO", "Product", "Support"]
AUDIENCE_BRIEFS = {
    "CEO": "Customer risk, renewal exposure, and operating focus.",
    "Product": "Root causes, product areas, and roadmap tradeoffs.",
    "Support": "Queue health, escalation patterns, and automation opportunities.",
}


@st.cache_data(show_spinner=False)
def load_sample_data() -> pd.DataFrame:
    return load_ticket_csv(sample_dataset_path())


@st.cache_data(show_spinner=False)
def add_themes_cached(df: pd.DataFrame) -> pd.DataFrame:
    return add_theme_column(df)


def main() -> None:
    apply_custom_theme()
    provider = active_ai_provider()
    theme_method = theme_discovery_method()
    render_product_header(provider, theme_method)
    st.sidebar.caption(f"AI provider: {provider}")
    st.sidebar.caption(f"Theme discovery: {theme_method}")
    audience = render_audience_selector()

    uploaded = st.sidebar.file_uploader("Upload support tickets CSV", type=["csv"])
    if uploaded:
        raw_df = load_ticket_csv(uploaded)
        st.sidebar.success("Uploaded dataset loaded")
    else:
        raw_df = load_sample_data()
        st.sidebar.info("Using the included sample dataset")

    filtered = render_filters(raw_df)
    with st.spinner("Discovering ticket themes..."):
        filtered = add_themes_cached(filtered)
    themes = discover_themes(filtered)
    kpis = compute_kpis(filtered)

    render_kpis(kpis)

    tab_overview, tab_themes, tab_automation, tab_chat, tab_data = st.tabs(
        ["Executive View", "Themes", "Automation", "Ask", "Data"]
    )

    with tab_overview:
        render_executive_view(filtered, themes, kpis, audience)
    with tab_themes:
        render_themes(filtered, themes)
    with tab_automation:
        render_automation(filtered, themes)
    with tab_chat:
        render_chat(filtered)
    with tab_data:
        render_data(filtered)


def render_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")
    min_date = df["created_at"].min().date()
    max_date = df["created_at"].max().date()
    selected_dates = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

    segments = st.sidebar.multiselect(
        "Customer segment",
        sorted(df["customer_segment"].dropna().unique()),
        default=sorted(df["customer_segment"].dropna().unique()),
    )
    priorities = st.sidebar.multiselect(
        "Priority",
        sorted(df["priority"].dropna().unique()),
        default=sorted(df["priority"].dropna().unique()),
    )
    plans = st.sidebar.multiselect(
        "Plan",
        sorted(df["plan_type"].dropna().unique()),
        default=sorted(df["plan_type"].dropna().unique()),
    )

    date_range = None
    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
        start = pd.Timestamp(selected_dates[0])
        end = pd.Timestamp(selected_dates[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        date_range = (start, end)

    return filter_tickets(df, date_range=date_range, segments=segments, priorities=priorities, plans=plans)


def render_audience_selector() -> str:
    with st.container(border=True):
        st.caption("Audience lens")
        audience = st.radio(
            "Audience lens",
            AUDIENCE_OPTIONS,
            horizontal=True,
            key="audience_lens",
            label_visibility="collapsed",
        )
    return audience


def render_kpis(kpis: dict[str, object]) -> None:
    render_kpi_cards(kpis)


def render_executive_view(filtered: pd.DataFrame, themes: list, kpis: dict[str, object], audience: str) -> None:
    render_audience_brief(filtered, themes, kpis, audience)
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader(f"{audience} Summary")
        summary = get_cached_summary(filtered, themes, kpis, audience)
        for item in summary:
            ticket_ids = normalize_ticket_ids(item.get("ticket_ids", []))
            with st.container(border=True):
                st.markdown(f"**{item['headline']}**")
                st.write(item["detail"])
                st.caption(f"Business impact: {item['business_impact']}")
                st.caption("Evidence: " + ", ".join(ticket_ids))
                render_source_tickets(filtered, ticket_ids, "View source tickets")
    with right:
        st.subheader("Ticket Volume")
        st.plotly_chart(ticket_volume_chart(tickets_over_time(filtered)), width="stretch")
        st.subheader("Priority Mix")
        priority_df = count_by(filtered, "priority")
        st.plotly_chart(bar_chart(priority_df, "priority", "count"), width="stretch")

    st.subheader("Suggested Product Fixes")
    recommendations = build_product_recommendations(themes, filtered, audience)
    for rec in recommendations[:4]:
        ticket_ids = normalize_ticket_ids(rec["ticket_ids"])
        with st.container(border=True):
            st.markdown(f"**{rec['title']}**")
            st.write(rec["why_it_matters"])
            st.write(f"Recommended action: {rec['recommended_action']}")
            st.caption(f"Impact: {rec['impact']} | Evidence: {rec['evidence']}")
            st.caption(f"Suggested owner: {rec['owner']}")
            st.caption("Example tickets: " + ", ".join(ticket_ids))
            render_source_tickets(filtered, ticket_ids, "View example tickets")


def render_audience_brief(filtered: pd.DataFrame, themes: list, kpis: dict[str, object], audience: str) -> None:
    top_theme = themes[0].name if themes else "No dominant theme"
    urgent_count = int(filtered["priority"].isin(["Critical", "High"]).sum()) if not filtered.empty else 0
    enterprise_urgent = int(
        ((filtered["customer_segment"] == "Enterprise") & filtered["priority"].isin(["Critical", "High"])).sum()
    ) if not filtered.empty else 0

    render_lens_card(
        audience,
        AUDIENCE_BRIEFS.get(audience, AUDIENCE_BRIEFS["CEO"]),
        top_theme,
        urgent_count,
        enterprise_urgent,
    )


def render_themes(filtered: pd.DataFrame, themes: list) -> None:
    if not themes:
        st.info("No themes found for the current filters.")
        return
    themes_df = pd.DataFrame([theme.__dict__ for theme in themes])
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Top Themes")
        st.plotly_chart(theme_chart(themes_df), width="stretch")
    with right:
        st.subheader("Theme Details")
        for theme in themes[:6]:
            with st.expander(f"{theme.name} - {theme.count} tickets - {theme.trend}", expanded=theme == themes[0]):
                st.write(theme.summary)
                st.caption(f"Avg CSAT: {theme.avg_csat} | High/Critical: {theme.critical_high_count}")
                st.caption("Evidence: " + ", ".join(theme.ticket_ids))
                theme_sources = source_ticket_rows(filtered, theme.ticket_ids)
                if not theme_sources.empty:
                    st.dataframe(theme_sources, width="stretch", hide_index=True)

    st.subheader("Segment x Priority")
    st.dataframe(segment_priority_matrix(filtered), width="stretch")


def render_automation(filtered: pd.DataFrame, themes: list) -> None:
    st.subheader("Bot-Solvable vs Human-Required")
    automation = classify_automation_opportunity(filtered)
    left, right = st.columns([1, 1])
    with left:
        st.plotly_chart(bar_chart(automation, "category", "tickets"), width="stretch")
    with right:
        st.dataframe(automation, width="stretch", hide_index=True)

    st.subheader("Automation Guidance")
    st.write(
        "Use automation for repetitive policy, billing, access, and documentation questions. "
        "Keep humans in the loop for bugs, roadmap requests, escalations, and renewal-sensitive accounts."
    )


def render_chat(filtered: pd.DataFrame) -> None:
    st.subheader("Ask Follow-Up Questions")
    st.caption("The demo chat uses deterministic filters and counts so it does not invent numbers.")

    current_data_key = dataframe_view_key(filtered)
    if st.session_state.get("chat_data_key") != current_data_key:
        st.session_state["chat_data_key"] = current_data_key
        st.session_state.pop("last_chat_response", None)
        st.session_state.pop("last_chat_question", None)

    sample_questions = [
        "show me angry enterprise customers",
        "what are the top issues",
        "how many enterprise integration tickets are there",
    ]
    sample_cols = st.columns(3)
    for index, sample_question in enumerate(sample_questions):
        with sample_cols[index]:
            if st.button(sample_question, key=f"sample_question_{index}", width="stretch"):
                st.session_state["chat_question"] = sample_question
                st.session_state["last_chat_response"] = answer_question(sample_question, filtered)
                st.session_state["last_chat_question"] = sample_question

    question = st.text_input(
        "Question",
        placeholder="Example: show me angry enterprise customers this month",
        key="chat_question",
    )
    col_ask, col_clear = st.columns([0.16, 0.84])
    with col_ask:
        ask_clicked = st.button("Ask", type="primary", width="stretch")
    with col_clear:
        clear_clicked = st.button("Clear", width="content")

    if clear_clicked:
        st.session_state.pop("last_chat_response", None)
        st.session_state.pop("last_chat_question", None)

    if ask_clicked and question.strip():
        response = answer_question(question.strip(), filtered)
        st.session_state["last_chat_response"] = response
        st.session_state["last_chat_question"] = question.strip()

    response = st.session_state.get("last_chat_response")
    if response:
        st.caption(f"Answering: {st.session_state.get('last_chat_question', '')}")
        st.markdown(response["answer"].replace("\n", "  \n"))
        ticket_ids = normalize_ticket_ids(response["ticket_ids"])
        if ticket_ids:
            st.caption("Evidence: " + ", ".join(ticket_ids))
            render_source_tickets(filtered, ticket_ids, "View matching tickets")
        st.caption(f"Method: {response['method']}")


def get_cached_summary(filtered: pd.DataFrame, themes: list, kpis: dict[str, object], audience: str) -> list[dict[str, object]]:
    summary_key = (
        audience,
        dataframe_view_key(filtered),
        tuple((theme.name, theme.count, theme.critical_high_count, tuple(theme.ticket_ids)) for theme in themes[:8]),
        tuple(sorted(kpis.items())),
    )
    cache = st.session_state.setdefault("summary_cache", {})
    if summary_key not in cache:
        with st.spinner(f"Generating {audience.lower()} summary..."):
            cache[summary_key] = generate_executive_summary(filtered, themes, kpis, audience)
    return cache[summary_key]


def dataframe_view_key(df: pd.DataFrame) -> tuple[object, ...]:
    if df.empty:
        return (0, None, None)
    return (
        len(df),
        str(df["created_at"].min()),
        str(df["created_at"].max()),
        tuple(sorted(df["ticket_id"].astype(str).head(20).tolist())),
    )


def render_data(filtered: pd.DataFrame) -> None:
    st.subheader("Ticket Examples")
    st.dataframe(top_customer_examples(filtered), width="stretch", hide_index=True)
    st.subheader("Raw Data")
    st.dataframe(filtered, width="stretch", hide_index=True)


def render_source_tickets(df: pd.DataFrame, ticket_ids: list[str] | object, label: str) -> None:
    rows = source_ticket_rows(df, ticket_ids)
    if rows.empty:
        return
    with st.expander(label):
        st.dataframe(rows, width="stretch", hide_index=True)


def source_ticket_rows(df: pd.DataFrame, ticket_ids: list[str] | object) -> pd.DataFrame:
    normalized_ids = normalize_ticket_ids(ticket_ids)
    if not normalized_ids:
        return pd.DataFrame(columns=SOURCE_TICKET_COLUMNS)

    available_columns = [column for column in SOURCE_TICKET_COLUMNS if column in df.columns]
    rows = df[df["ticket_id"].astype(str).isin(normalized_ids)][available_columns].copy()
    if rows.empty:
        return rows

    order = {ticket_id: index for index, ticket_id in enumerate(normalized_ids)}
    rows["_source_order"] = rows["ticket_id"].astype(str).map(order)
    rows = rows.sort_values("_source_order").drop(columns="_source_order")
    rows["created_at"] = pd.to_datetime(rows["created_at"]).dt.date.astype(str)
    return rows


def normalize_ticket_ids(ticket_ids: list[str] | object) -> list[str]:
    if ticket_ids is None:
        return []
    if isinstance(ticket_ids, str):
        raw_ids = ticket_ids.split(",")
    elif isinstance(ticket_ids, list):
        raw_ids = ticket_ids
    else:
        raw_ids = list(ticket_ids) if hasattr(ticket_ids, "__iter__") else []
    return [str(ticket_id).strip() for ticket_id in raw_ids if str(ticket_id).strip()]


if __name__ == "__main__":
    main()
