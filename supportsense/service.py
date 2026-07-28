from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import PurePath

from app.analytics import compute_kpis
from app.chat import answer_question
from app.data_loader import load_ticket_csv
from app.theme_discovery import add_theme_column, discover_themes
from supportsense.config import settings
from supportsense.errors import ServiceError
from supportsense.models import AnalysisResponse, ChatResponse
from supportsense.store import AnalysisRecord, AnalysisStore, analysis_store


class AnalysisService:
    def __init__(self, store: AnalysisStore = analysis_store) -> None:
        self.store = store

    def analyze_csv(
        self, *, tenant_id: str, filename: str, content: bytes
    ) -> AnalysisRecord:
        safe_filename = PurePath(filename).name
        if not safe_filename.lower().endswith(".csv"):
            raise ServiceError("unsupported_file_type", "Only CSV files are accepted.")
        if not content:
            raise ServiceError("empty_upload", "The uploaded CSV is empty.")
        if len(content) > settings.max_upload_bytes:
            raise ServiceError(
                "upload_too_large",
                f"CSV exceeds the {settings.max_upload_bytes} byte upload limit.",
                413,
            )
        try:
            dataframe = load_ticket_csv(BytesIO(content))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceError("invalid_csv", str(exc)) from exc
        except Exception as exc:
            raise ServiceError("invalid_csv", "The CSV could not be parsed.") from exc
        if len(dataframe) > settings.max_ticket_rows:
            raise ServiceError(
                "too_many_rows",
                f"CSV exceeds the {settings.max_ticket_rows} ticket limit.",
                413,
            )
        if dataframe["ticket_id"].duplicated().any():
            raise ServiceError("duplicate_ticket_ids", "Ticket IDs must be unique.")

        dataframe = add_theme_column(dataframe)
        themes = discover_themes(dataframe)
        kpis = compute_kpis(dataframe)
        return self.store.create(
            tenant_id=tenant_id,
            filename=safe_filename,
            content_sha256=hashlib.sha256(content).hexdigest(),
            dataframe=dataframe,
            kpis=kpis,
            themes=themes,
        )

    def response(self, record: AnalysisRecord) -> AnalysisResponse:
        return AnalysisResponse(
            analysis_id=record.analysis_id,
            filename=record.filename,
            created_at=record.created_at,
            row_count=len(record.dataframe),
            content_sha256=record.content_sha256,
            kpis=record.kpis,
            themes=[theme.__dict__ for theme in record.themes],
        )

    def chat(self, record: AnalysisRecord, question: str) -> ChatResponse:
        result = answer_question(question, record.dataframe)
        return ChatResponse.model_validate(result)


analysis_service = AnalysisService()
