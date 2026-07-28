from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="SupportSense Operations",
    page_icon="SS",
    layout="wide",
)


def fetch_dashboard(api_url: str, token: str) -> dict:
    request = Request(
        f"{api_url.rstrip('/')}/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def metric_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows or [{"name": "No data", "count": 0}])


def main() -> None:
    st.title("SupportSense Operations")
    st.caption(
        "Conversation outcomes, automation quality, escalations, failures, and knowledge gaps."
    )
    api_url = st.sidebar.text_input("API URL", value="http://localhost:8000")
    token = st.sidebar.text_input(
        "Supervisor token",
        value="dev-admin-key",
        type="password",
    )
    if not st.sidebar.button("Refresh", type="primary"):
        st.info("Connect to the SupportSense API to load operational metrics.")
        return

    try:
        payload = fetch_dashboard(api_url, token)
    except HTTPError as exc:
        st.error(f"API rejected the request with HTTP {exc.code}.")
        return
    except (URLError, TimeoutError, json.JSONDecodeError):
        st.error("The SupportSense API is unavailable or returned invalid data.")
        return

    columns = st.columns(6)
    columns[0].metric("Conversations", payload["total_conversations"])
    columns[1].metric("Contained", payload["contained_conversations"])
    columns[2].metric("Containment", f"{payload['containment_rate']:.1%}")
    columns[3].metric("Escalations", payload["escalated_conversations"])
    columns[4].metric("Tool failures", payload["failed_tool_calls"])
    columns[5].metric(
        "Avg response",
        f"{payload['average_response_time_ms']:.0f} ms",
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Top intents")
        intents = metric_table(payload["top_intents"]).set_index("name")
        st.bar_chart(intents)
        st.subheader("Conversation outcomes")
        st.dataframe(metric_table(payload["conversation_outcomes"]), hide_index=True)
        st.subheader("Top customer issues")
        st.dataframe(metric_table(payload["top_customer_issues"]), hide_index=True)
    with right:
        st.subheader("Knowledge gaps")
        st.dataframe(metric_table(payload["knowledge_gaps"]), hide_index=True)
        st.subheader("Tool failures")
        st.dataframe(metric_table(payload["tool_failures"]), hide_index=True)
        st.subheader("Customer sentiment")
        st.dataframe(metric_table(payload["customer_sentiment"]), hide_index=True)
        st.subheader("Automation opportunities")
        st.dataframe(
            metric_table(payload["automation_opportunities"]),
            hide_index=True,
        )


if __name__ == "__main__":
    main()
