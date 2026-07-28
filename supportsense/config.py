from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    api_keys: str
    database_url: str
    jwt_issuer: str | None
    jwt_audience: str | None
    jwt_secret: str | None
    jwt_public_key: str | None
    max_upload_bytes: int
    max_ticket_rows: int
    conversation_window: int
    rollout_stage: str
    redis_url: str | None
    rate_limit_per_minute: int
    tool_backend: str
    tool_api_url: str | None
    tool_api_token: str | None
    sentry_dsn: str | None
    traces_sample_rate: float
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    langfuse_base_url: str | None
    upload_bucket: str | None
    chroma_url: str | None
    embedding_provider: str
    gemini_api_key: str | None
    gemini_embedding_model: str
    openai_api_key: str | None
    openai_embedding_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("SUPPORTSENSE_ENV", "development").lower()
        api_keys = os.getenv("SUPPORTSENSE_API_KEYS", "")
        database_url = os.getenv("DATABASE_URL")
        jwt_secret = os.getenv("SUPPORTSENSE_JWT_SECRET") or None
        jwt_public_key = (
            os.getenv("SUPPORTSENSE_JWT_PUBLIC_KEY", "").replace("\\n", "\n")
            or None
        )
        tool_backend = os.getenv(
            "SUPPORTSENSE_TOOL_BACKEND",
            "sandbox" if environment != "production" else "disabled",
        ).lower()
        embedding_provider = os.getenv(
            "SUPPORTSENSE_EMBEDDING_PROVIDER",
            "local",
        ).lower()
        if embedding_provider not in {"local", "gemini", "openai"}:
            raise RuntimeError(
                "SUPPORTSENSE_EMBEDDING_PROVIDER must be local, gemini, or openai"
            )
        if embedding_provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("Gemini embeddings require GEMINI_API_KEY")
        if embedding_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI embeddings require OPENAI_API_KEY")
        if not api_keys and environment != "production":
            api_keys = "dev-admin-key:demo-tenant:admin"
        if environment == "production" and not database_url:
            raise RuntimeError("DATABASE_URL is required in production")
        if environment == "production" and not database_url.startswith(
            ("postgresql://", "postgresql+psycopg://")
        ):
            raise RuntimeError("Production DATABASE_URL must use PostgreSQL")
        if environment == "production" and not os.getenv("REDIS_URL"):
            raise RuntimeError("REDIS_URL is required in production")
        if environment == "production" and not (
            api_keys or jwt_secret or jwt_public_key
        ):
            raise RuntimeError(
                "Production authentication requires API keys or a JWT verification key"
            )
        if environment == "production" and tool_backend == "sandbox":
            raise RuntimeError("The sandbox tool backend is forbidden in production")
        if tool_backend == "http" and not (
            os.getenv("SUPPORTSENSE_TOOL_API_URL")
            and os.getenv("SUPPORTSENSE_TOOL_API_TOKEN")
        ):
            raise RuntimeError("HTTP tool backend requires its URL and token")
        if (
            environment == "production"
            and tool_backend == "http"
            and not os.getenv("SUPPORTSENSE_TOOL_API_URL", "").startswith("https://")
        ):
            raise RuntimeError("Production tool gateway must use HTTPS")
        return cls(
            environment=environment,
            api_keys=api_keys,
            database_url=database_url or "sqlite:///./supportsense.db",
            jwt_issuer=os.getenv("SUPPORTSENSE_JWT_ISSUER") or None,
            jwt_audience=os.getenv("SUPPORTSENSE_JWT_AUDIENCE") or None,
            jwt_secret=jwt_secret,
            jwt_public_key=jwt_public_key,
            max_upload_bytes=int(os.getenv("SUPPORTSENSE_MAX_UPLOAD_BYTES", "10485760")),
            max_ticket_rows=int(os.getenv("SUPPORTSENSE_MAX_TICKET_ROWS", "100000")),
            conversation_window=int(os.getenv("SUPPORTSENSE_CONVERSATION_WINDOW", "12")),
            rollout_stage=os.getenv(
                "SUPPORTSENSE_ROLLOUT_STAGE",
                "limited_automation" if environment != "production" else "offline",
            ),
            redis_url=os.getenv("REDIS_URL") or None,
            rate_limit_per_minute=int(
                os.getenv("SUPPORTSENSE_RATE_LIMIT_PER_MINUTE", "120")
            ),
            tool_backend=tool_backend,
            tool_api_url=os.getenv("SUPPORTSENSE_TOOL_API_URL") or None,
            tool_api_token=os.getenv("SUPPORTSENSE_TOOL_API_TOKEN") or None,
            sentry_dsn=os.getenv("SENTRY_DSN") or None,
            traces_sample_rate=float(
                os.getenv("SUPPORTSENSE_TRACES_SAMPLE_RATE", "0.1")
            ),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
            langfuse_base_url=os.getenv("LANGFUSE_BASE_URL") or None,
            upload_bucket=os.getenv("UPLOAD_BUCKET") or None,
            chroma_url=os.getenv("CHROMA_URL") or None,
            embedding_provider=embedding_provider,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_embedding_model=os.getenv(
                "GEMINI_EMBEDDING_MODEL",
                "gemini-embedding-001",
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_embedding_model=os.getenv(
                "OPENAI_EMBEDDING_MODEL",
                "text-embedding-3-small",
            ),
        )


settings = Settings.from_env()
