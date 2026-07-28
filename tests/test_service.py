from __future__ import annotations

from pathlib import Path

import pytest

from supportsense.errors import ServiceError
from supportsense.service import AnalysisService
from supportsense.store import AnalysisStore

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "data" / "sample_tickets.csv").read_bytes()


def test_analysis_service_creates_cited_analysis() -> None:
    service = AnalysisService(AnalysisStore())

    record = service.analyze_csv(
        tenant_id="tenant-a",
        filename="../../tickets.csv",
        content=SAMPLE,
    )
    response = service.response(record)

    assert response.filename == "tickets.csv"
    assert response.row_count > 0
    assert response.kpis["total_tickets"] == response.row_count
    assert response.themes
    assert response.themes[0].ticket_ids


def test_analysis_store_does_not_leak_cross_tenant_records() -> None:
    store = AnalysisStore()
    service = AnalysisService(store)
    record = service.analyze_csv(
        tenant_id="tenant-a", filename="tickets.csv", content=SAMPLE
    )

    with pytest.raises(ServiceError) as error:
        store.get(record.analysis_id, "tenant-b")

    assert error.value.status_code == 404


def test_analysis_rejects_non_csv_files() -> None:
    service = AnalysisService(AnalysisStore())

    with pytest.raises(ServiceError) as error:
        service.analyze_csv(
            tenant_id="tenant-a", filename="tickets.xlsx", content=b"not a csv"
        )

    assert error.value.code == "unsupported_file_type"
