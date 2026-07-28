from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from typing import Any

from supportsense.config import settings

LOGGER = logging.getLogger("supportsense.tracing")


def configure_error_monitoring() -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=settings.traces_sample_rate,
            send_default_pii=False,
        )
    except Exception:
        LOGGER.exception("Sentry initialization failed; continuing without it")


class OptionalObservation(AbstractContextManager[None]):
    """Fail-open Langfuse span that never interrupts customer support."""

    def __init__(self, name: str, metadata: dict[str, Any]) -> None:
        self.name = name
        self.metadata = metadata
        self.manager: Any = None

    def __enter__(self) -> None:
        if not (
            settings.langfuse_public_key
            and settings.langfuse_secret_key
        ):
            return None
        try:
            from langfuse import get_client

            self.manager = get_client().start_as_current_observation(
                as_type="agent",
                name=self.name,
                metadata=self.metadata,
            )
            self.manager.__enter__()
        except Exception:
            self.manager = None
            LOGGER.exception("Langfuse span initialization failed")
        return None

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self.manager is not None:
            try:
                self.manager.__exit__(exc_type, exc_value, traceback)
            except Exception:
                LOGGER.exception("Langfuse span export failed")
        return False


def agent_observation(metadata: dict[str, Any]) -> OptionalObservation:
    return OptionalObservation("supportsense-agent-turn", metadata)
