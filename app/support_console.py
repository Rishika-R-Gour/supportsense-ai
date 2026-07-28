from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="SupportSense",
    page_icon="💬",
    layout="wide",
)


@dataclass
class ApiError(RuntimeError):
    status: int
    message: str


def api_request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
) -> dict | list:
    base_url = st.session_state.api_url.rstrip("/")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {st.session_state.token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = str(detail.get("message") or detail.get("code"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = f"API request failed with HTTP {exc.code}"
        raise ApiError(exc.code, message) from exc
    except (URLError, TimeoutError) as exc:
        raise ApiError(503, "The SupportSense API is unavailable.") from exc
    return json.loads(body.decode("utf-8")) if body else {}


def connect() -> dict | None:
    try:
        identity = api_request("GET", "/api/v1/auth/me")
    except ApiError as exc:
        st.sidebar.error(exc.message)
        return None
    st.sidebar.success(
        f"{identity['role'].replace('_', ' ').title()} · {identity['tenant_id']}"
    )
    return identity


def customer_workspace() -> None:
    st.header("Customer support")
    st.caption("Live, multi-turn support with citations and human escalation.")
    conversations = api_request("GET", "/api/v1/conversations?limit=50")
    options = {
        f"{item['updated_at'][:19]} · {item.get('intent') or 'New request'}": item[
            "conversation_id"
        ]
        for item in conversations
    }
    selected = st.selectbox(
        "Conversation history",
        ["Start a new conversation", *options],
    )
    if selected != "Start a new conversation":
        st.session_state.customer_conversation_id = options[selected]

    conversation_id = st.session_state.get("customer_conversation_id")
    if conversation_id:
        try:
            detail = api_request(
                "GET",
                f"/api/v1/conversations/{conversation_id}",
            )
            for message in detail["messages"]:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    references = [
                        item["reference"]
                        for item in message.get("citations", [])
                        if item.get("reference")
                    ]
                    if references:
                        st.caption("Sources: " + ", ".join(references))
        except ApiError:
            st.session_state.pop("customer_conversation_id", None)

    if prompt := st.chat_input("Ask about payments, refunds, invoices, or subscriptions"):
        try:
            response = api_request(
                "POST",
                "/api/v1/chat",
                payload={
                    "conversation_id": conversation_id,
                    "message": prompt,
                    "idempotency_key": f"web-{uuid4()}",
                },
            )
            st.session_state.customer_conversation_id = response["conversation_id"]
            st.rerun()
        except ApiError as exc:
            st.error(exc.message)

    with st.expander("My tickets"):
        with st.form("customer-ticket"):
            subject = st.text_input("Subject")
            description = st.text_area("Description")
            submitted = st.form_submit_button("Create ticket")
        if submitted:
            try:
                api_request(
                    "POST",
                    "/api/v1/tickets",
                    payload={
                        "subject": subject,
                        "description": description,
                        "priority": "Medium",
                    },
                )
                st.success("Ticket created.")
            except ApiError as exc:
                st.error(exc.message)
        tickets = api_request("GET", "/api/v1/tickets")
        st.dataframe(pd.DataFrame(tickets), hide_index=True, use_container_width=True)


def agent_workspace(identity: dict) -> None:
    st.header("Agent Assist")
    st.caption(
        "Suggested replies, evidence, customer history, ticket history, tool plans, and confidence."
    )
    left, right = st.columns([2, 1])
    conversations = api_request("GET", "/api/v1/conversations?limit=100")
    with left:
        conversation_id = st.selectbox(
            "Live conversation",
            ["New agent-assist conversation"]
            + [item["conversation_id"] for item in conversations],
        )
        message = st.text_area(
            "Customer message",
            placeholder="Example: resend invoice inv_123 for customer cus_demo",
        )
        if st.button("Generate suggestion", type="primary", disabled=not message):
            try:
                suggestion = api_request(
                    "POST",
                    "/api/v1/agent-assist",
                    payload={
                        "conversation_id": (
                            None
                            if conversation_id == "New agent-assist conversation"
                            else conversation_id
                        ),
                        "message": message,
                        "idempotency_key": f"assist-{uuid4()}",
                    },
                )
                st.session_state.last_suggestion = suggestion
            except ApiError as exc:
                st.error(exc.message)
        suggestion = st.session_state.get("last_suggestion")
        if suggestion:
            st.subheader("Suggested reply")
            st.info(suggestion["answer"])
            metrics = st.columns(3)
            metrics[0].metric("Intent", suggestion["intent"])
            metrics[1].metric(
                "AI confidence",
                f"{(suggestion.get('confidence') or 0):.0%}",
            )
            metrics[2].metric(
                "Tool suggestion",
                suggestion.get("tool_suggestion") or "None",
            )
            if suggestion["citations"]:
                st.write("Retrieved evidence", suggestion["citations"])
            st.caption("Agent review is required before this suggestion reaches a customer.")

    with right:
        st.subheader("Customer history")
        if conversation_id != "New agent-assist conversation":
            detail = api_request(
                "GET",
                f"/api/v1/conversations/{conversation_id}",
            )
            st.write(detail.get("summary") or "No summary yet.")
            st.json(detail.get("memory") or {})
        else:
            st.info("Select a conversation to view its context.")
        st.subheader("Assigned tickets")
        st.dataframe(
            pd.DataFrame(api_request("GET", "/api/v1/tickets?limit=50")),
            hide_index=True,
            use_container_width=True,
        )

    if identity["role"] in {"supervisor", "admin"}:
        approval_workspace()


def approval_workspace() -> None:
    st.divider()
    st.subheader("Sensitive action approvals")
    approvals = api_request("GET", "/api/v1/approvals?status=pending")
    if not approvals:
        st.success("No pending approvals.")
        return
    for approval in approvals:
        with st.container(border=True):
            st.write(
                f"**{approval['tool_name']}** · conversation "
                f"`{approval['conversation_id']}`"
            )
            st.json(approval["requested_arguments"])
            approve, deny = st.columns(2)
            if approve.button(
                "Approve",
                key=f"approve-{approval['approval_id']}",
                type="primary",
            ):
                api_request(
                    "POST",
                    f"/api/v1/approvals/{approval['approval_id']}/decision",
                    payload={"approved": True, "reason": "Approved in support console"},
                )
                st.rerun()
            if deny.button("Deny", key=f"deny-{approval['approval_id']}"):
                api_request(
                    "POST",
                    f"/api/v1/approvals/{approval['approval_id']}/decision",
                    payload={"approved": False, "reason": "Denied in support console"},
                )
                st.rerun()


def admin_workspace(identity: dict) -> None:
    st.header("Conversation Intelligence")
    dashboard = api_request("GET", "/api/v1/admin/dashboard")
    metrics = st.columns(6)
    metrics[0].metric("Conversations", dashboard["total_conversations"])
    metrics[1].metric("Containment", f"{dashboard['containment_rate']:.1%}")
    metrics[2].metric("Escalation", f"{dashboard['escalation_rate']:.1%}")
    metrics[3].metric("Tool failures", dashboard["failed_tool_calls"])
    metrics[4].metric(
        "Avg response",
        f"{dashboard['average_response_time_ms']:.0f} ms",
    )
    metrics[5].metric(
        "Knowledge gaps",
        sum(item["count"] for item in dashboard["knowledge_gaps"]),
    )
    panels = [
        ("Top intents", "top_intents"),
        ("Top customer issues", "top_customer_issues"),
        ("Customer sentiment", "customer_sentiment"),
        ("Automation opportunities", "automation_opportunities"),
        ("Tool failures", "tool_failures"),
        ("Conversation outcomes", "conversation_outcomes"),
    ]
    for row_start in range(0, len(panels), 2):
        columns = st.columns(2)
        for column, (title, key) in zip(columns, panels[row_start : row_start + 2]):
            with column:
                st.subheader(title)
                st.dataframe(
                    pd.DataFrame(dashboard[key]),
                    hide_index=True,
                    use_container_width=True,
                )

    st.divider()
    st.subheader("Agent versions")
    versions = api_request("GET", "/api/v1/admin/agent-versions")
    st.dataframe(pd.DataFrame(versions), hide_index=True, use_container_width=True)
    if identity["role"] == "admin":
        with st.form("agent-version"):
            name = st.text_input("Agent name", value="support-agent")
            version = st.text_input("Version", value="v1")
            prompt_version = st.text_input("Prompt version", value="supportsense-agent-v2")
            rollout_stage = st.selectbox(
                "Rollout stage",
                [
                    "offline",
                    "shadow",
                    "agent_assist",
                    "limited_automation",
                    "full_automation",
                ],
            )
            active = st.checkbox("Activate this version")
            create = st.form_submit_button("Register version")
        if create:
            try:
                api_request(
                    "POST",
                    "/api/v1/admin/agent-versions",
                    payload={
                        "name": name,
                        "version": version,
                        "prompt_version": prompt_version,
                        "model_config": {},
                        "tool_policy": {},
                        "rollout_stage": rollout_stage,
                        "active": active,
                    },
                )
                st.success("Agent version registered.")
                st.rerun()
            except ApiError as exc:
                st.error(exc.message)

    if st.button("Run 140-case release evaluation"):
        with st.spinner("Running release gates…"):
            try:
                result = api_request("POST", "/api/v1/evals/run")
                st.success(
                    f"{result['suite']} {'passed' if result['passed'] else 'failed'}."
                )
                st.json(result["metrics"])
            except ApiError as exc:
                st.error(exc.message)

    with st.expander("Audit log"):
        events = api_request("GET", "/api/v1/admin/audit-events?limit=100")
        st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)


def main() -> None:
    st.sidebar.title("SupportSense")
    st.session_state.setdefault(
        "api_url",
        os.getenv("SUPPORTSENSE_API_URL", "http://localhost:8000"),
    )
    st.session_state.api_url = st.sidebar.text_input(
        "API URL",
        value=st.session_state.api_url,
    )
    st.session_state.token = st.sidebar.text_input(
        "Bearer token",
        value=st.session_state.get("token", "dev-admin-key"),
        type="password",
    )
    identity = connect()
    if not identity:
        st.title("SupportSense")
        st.info("Enter valid API credentials to open the support workspace.")
        return

    pages = ["Customer"]
    if identity["role"] in {"agent", "supervisor", "admin"}:
        pages.append("Agent Assist")
    if identity["role"] in {"supervisor", "admin"}:
        pages.append("Conversation Intelligence")
    page = st.sidebar.radio("Workspace", pages)

    try:
        if page == "Customer":
            customer_workspace()
        elif page == "Agent Assist":
            agent_workspace(identity)
        else:
            admin_workspace(identity)
    except ApiError as exc:
        st.error(exc.message)


if __name__ == "__main__":
    main()
