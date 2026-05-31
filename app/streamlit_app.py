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


st.set_page_config(page_title="SupportSense", page_icon="SS", layout="wide")

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


@st.cache_data(show_spinner=False)
def load_sample_data() -> pd.DataFrame:
    return load_ticket_csv(sample_dataset_path())


@st.cache_data(show_spinner=False)
def add_themes_cached(df: pd.DataFrame) -> pd.DataFrame:
    return add_theme_column(df)


def main() -> None:
    st.title("SupportSense")
    st.caption("AI customer support analyzer for executive insight, product prioritization, and trusted follow-up questions.")
    st.sidebar.caption(f"AI provider: {active_ai_provider()}")
    st.sidebar.caption(f"Theme discovery: {theme_discovery_method()}")

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
        render_executive_view(filtered, themes, kpis)
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


def render_kpis(kpis: dict[str, object]) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Tickets", kpis["total_tickets"])
    col2.metric("High/Critical", f"{kpis['critical_high_pct']}%")
    col3.metric("Avg CSAT", kpis["avg_csat"])
    col4.metric("Median Resolve", f"{kpis['median_resolution_hours']}h")
    col5.metric("Open Work", f"{kpis['open_pct']}%")


def render_executive_view(filtered: pd.DataFrame, themes: list, kpis: dict[str, object]) -> None:
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Executive Summary")
        summary = generate_executive_summary(filtered, themes, kpis)
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
    recommendations = build_product_recommendations(themes, filtered)
    for rec in recommendations[:4]:
        ticket_ids = normalize_ticket_ids(rec["ticket_ids"])
        with st.container(border=True):
            st.markdown(f"**{rec['title']}**")
            st.write(rec["why_it_matters"])
            st.caption(f"Impact: {rec['impact']} | Evidence: {rec['evidence']}")
            st.caption("Example tickets: " + ", ".join(ticket_ids))
            render_source_tickets(filtered, ticket_ids, "View example tickets")


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
    with st.form("ticket_question_form", clear_on_submit=False):
        question = st.text_input("Question", placeholder="Example: show me angry enterprise customers this month")
        submitted = st.form_submit_button("Ask")

    if submitted and question:
        response = answer_question(question, filtered)
        st.markdown(response["answer"].replace("\n", "  \n"))
        ticket_ids = normalize_ticket_ids(response["ticket_ids"])
        if ticket_ids:
            st.caption("Evidence: " + ", ".join(ticket_ids))
            render_source_tickets(filtered, ticket_ids, "View matching tickets")
        st.caption(f"Method: {response['method']}")


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
