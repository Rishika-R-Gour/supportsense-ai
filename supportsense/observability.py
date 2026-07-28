from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "supportsense_http_requests_total",
    "HTTP requests by route, method, and status.",
    ["route", "method", "status"],
)
HTTP_LATENCY = Histogram(
    "supportsense_http_request_duration_seconds",
    "HTTP request latency by route.",
    ["route", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
AGENT_OUTCOMES = Counter(
    "supportsense_agent_outcomes_total",
    "Agent conversation outcomes.",
    ["intent", "outcome"],
)
MODEL_REQUESTS = Counter(
    "supportsense_model_requests_total",
    "Model requests by provider, model, and outcome.",
    ["provider", "model", "outcome"],
)
MODEL_TOKENS = Counter(
    "supportsense_model_tokens_total",
    "Model tokens by provider, model, and direction.",
    ["provider", "model", "direction"],
)
MODEL_COST_USD = Counter(
    "supportsense_model_cost_usd_total",
    "Estimated model cost in US dollars.",
    ["provider", "model"],
)
TOOL_EXECUTIONS = Counter(
    "supportsense_tool_executions_total",
    "Tool executions by name, risk, and status.",
    ["tool", "risk", "status"],
)
TOOL_RETRIES = Counter(
    "supportsense_tool_retries_total",
    "Tool retries by name and error code.",
    ["tool", "error_code"],
)
CIRCUIT_BREAKER_REJECTIONS = Counter(
    "supportsense_circuit_breaker_rejections_total",
    "Calls rejected by an open dependency circuit.",
    ["dependency"],
)
CIRCUIT_BREAKER_STATE = Gauge(
    "supportsense_circuit_breaker_state",
    "Dependency circuit state (0 closed, 0.5 half-open, 1 open).",
    ["dependency"],
)
VECTOR_STORE_OPERATIONS = Counter(
    "supportsense_vector_store_operations_total",
    "Vector-store operations by operation and outcome.",
    ["operation", "outcome"],
)
ESCALATIONS = Counter(
    "supportsense_escalations_total",
    "Escalations by reason.",
    ["reason"],
)
ANALYSIS_ROWS = Histogram(
    "supportsense_analysis_rows",
    "Ticket rows per completed analysis.",
    buckets=(10, 50, 100, 500, 1_000, 5_000, 10_000, 50_000, 100_000),
)
INFLIGHT_REQUESTS = Gauge(
    "supportsense_http_inflight_requests",
    "Requests currently executing.",
)
