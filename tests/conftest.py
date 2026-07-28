from __future__ import annotations

import pytest
from sqlalchemy import select

from supportsense.database import SessionFactory, create_development_schema
from supportsense.db_models import AgentVersion


@pytest.fixture(autouse=True)
def isolate_active_agent_versions():
    """Prevent persisted local rollout configuration from leaking between tests."""
    create_development_schema()
    with SessionFactory() as session:
        previously_active = set(
            session.scalars(
                select(AgentVersion.id).where(AgentVersion.active.is_(True))
            ).all()
        )
        for version in session.scalars(select(AgentVersion)).all():
            version.active = False
        session.commit()

    yield

    with SessionFactory() as session:
        for version in session.scalars(select(AgentVersion)).all():
            version.active = version.id in previously_active
        session.commit()
