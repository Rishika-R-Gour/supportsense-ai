from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum

import jwt
from fastapi import Header, Request
from jwt import InvalidTokenError

from supportsense.config import settings
from supportsense.errors import ServiceError


class Role(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    # Backward-compatible names for early development configuration.
    VIEWER = "customer"
    ANALYST = "agent"


ROLE_LEVEL = {
    Role.CUSTOMER: 10,
    Role.AGENT: 20,
    Role.SUPERVISOR: 30,
    Role.ADMIN: 40,
}


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    role: Role


def _configured_principals() -> list[tuple[str, Principal]]:
    principals: list[tuple[str, Principal]] = []
    for item in settings.api_keys.split(","):
        if not item.strip():
            continue
        try:
            token, tenant_id, role_value = (part.strip() for part in item.split(":", 2))
            role = Role(
                {"viewer": "customer", "analyst": "agent"}.get(role_value, role_value)
            )
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Invalid SUPPORTSENSE_API_KEYS configuration") from exc
        if not token or not tenant_id:
            raise RuntimeError("API key and tenant ID must not be empty")
        principals.append(
            (token, Principal(subject=_fingerprint(token), tenant_id=tenant_id, role=role))
        )
    return principals


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise ServiceError("authentication_required", "A bearer API key is required.", 401)
    supplied = authorization.removeprefix("Bearer ").strip()
    for token, principal in _configured_principals():
        if hmac.compare_digest(supplied, token):
            request.state.principal = principal
            return principal
    if supplied.count(".") == 2 and (settings.jwt_secret or settings.jwt_public_key):
        principal = _jwt_principal(supplied)
        request.state.principal = principal
        return principal
    raise ServiceError("invalid_credentials", "The supplied API key is invalid.", 401)


def _jwt_principal(token: str) -> Principal:
    key = settings.jwt_public_key or settings.jwt_secret
    algorithm = "RS256" if settings.jwt_public_key else "HS256"
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["exp", "sub", "tenant_id", "role"],
                "verify_aud": bool(settings.jwt_audience),
                "verify_iss": bool(settings.jwt_issuer),
            },
        )
        return Principal(
            subject=str(claims["sub"]),
            tenant_id=str(claims["tenant_id"]),
            role=Role(str(claims["role"])),
        )
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise ServiceError("invalid_credentials", "The supplied token is invalid.", 401) from exc


def require_role(principal: Principal, minimum: Role) -> None:
    if ROLE_LEVEL[principal.role] < ROLE_LEVEL[minimum]:
        raise ServiceError(
            "permission_denied",
            f"This operation requires the {minimum.value} role or higher.",
            403,
        )
