from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

import pandas as pd

from supportsense.errors import ServiceError


@dataclass(frozen=True)
class AnalysisRecord:
    analysis_id: str
    tenant_id: str
    filename: str
    created_at: datetime
    content_sha256: str
    dataframe: pd.DataFrame
    kpis: dict[str, object]
    themes: list[object]


class AnalysisStore:
    """Thread-safe development store with tenant isolation.

    Production deployments replace this interface with PostgreSQL and object
    storage without changing the API or analytics service.
    """

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._lock = RLock()

    def create(
        self,
        *,
        tenant_id: str,
        filename: str,
        content_sha256: str,
        dataframe: pd.DataFrame,
        kpis: dict[str, object],
        themes: list[object],
    ) -> AnalysisRecord:
        record = AnalysisRecord(
            analysis_id=str(uuid4()),
            tenant_id=tenant_id,
            filename=filename,
            created_at=datetime.now(UTC),
            content_sha256=content_sha256,
            dataframe=dataframe.copy(),
            kpis=kpis,
            themes=themes,
        )
        with self._lock:
            self._records[record.analysis_id] = record
        return record

    def get(self, analysis_id: str, tenant_id: str) -> AnalysisRecord:
        with self._lock:
            record = self._records.get(analysis_id)
        # Do not reveal whether another tenant owns this identifier.
        if record is None or record.tenant_id != tenant_id:
            raise ServiceError("analysis_not_found", "Analysis not found.", 404)
        return record

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


analysis_store = AnalysisStore()
