from __future__ import annotations

from sqlalchemy import create_engine, inspect

from supportsense import db_models  # noqa: F401
from supportsense.database import Base


def test_production_domain_schema_contains_required_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())

    assert {
        "users",
        "conversations",
        "messages",
        "tickets",
        "knowledge_sources",
        "tool_logs",
        "audit_logs",
        "evaluations",
        "agent_versions",
        "approvals",
        "datasets",
        "analyses",
        "memory_facts",
        "knowledge_chunks",
    } <= tables

    constraints = inspect(engine).get_unique_constraints("agent_versions")
    assert any(
        constraint["column_names"] == ["tenant_id", "name", "version"]
        for constraint in constraints
    )
