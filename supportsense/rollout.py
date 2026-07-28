from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from supportsense.config import settings
from supportsense.errors import ServiceError


class RolloutStage(StrEnum):
    OFFLINE = "offline"
    SHADOW = "shadow"
    AGENT_ASSIST = "agent_assist"
    LIMITED_AUTOMATION = "limited_automation"
    FULL_AUTOMATION = "full_automation"


STAGE_ORDER = (
    RolloutStage.OFFLINE,
    RolloutStage.SHADOW,
    RolloutStage.AGENT_ASSIST,
    RolloutStage.LIMITED_AUTOMATION,
    RolloutStage.FULL_AUTOMATION,
)


@dataclass(frozen=True)
class RolloutPolicy:
    stage: RolloutStage

    @classmethod
    def current(cls) -> "RolloutPolicy":
        try:
            return cls(RolloutStage(settings.rollout_stage))
        except ValueError as exc:
            raise RuntimeError("Invalid SUPPORTSENSE_ROLLOUT_STAGE") from exc

    @classmethod
    def effective(cls, tenant_stage: RolloutStage | str) -> "RolloutPolicy":
        """Apply a tenant rollout without exceeding the deployment safety ceiling."""
        requested = RolloutStage(tenant_stage)
        global_stage = cls.current().stage
        effective_index = min(
            STAGE_ORDER.index(requested),
            STAGE_ORDER.index(global_stage),
        )
        return cls(STAGE_ORDER[effective_index])

    def enforce_tool(self, risk_level: str) -> None:
        allowed = {
            RolloutStage.OFFLINE: set(),
            RolloutStage.SHADOW: set(),
            RolloutStage.AGENT_ASSIST: {"read"},
            RolloutStage.LIMITED_AUTOMATION: {"read", "write", "sensitive"},
            RolloutStage.FULL_AUTOMATION: {"read", "write", "sensitive"},
        }[self.stage]
        if risk_level not in allowed:
            raise ServiceError(
                "rollout_blocked",
                f"{risk_level} tools are disabled in {self.stage.value} mode.",
                409,
            )

    @property
    def customer_visible(self) -> bool:
        return self.stage in {
            RolloutStage.LIMITED_AUTOMATION,
            RolloutStage.FULL_AUTOMATION,
        }

    @property
    def requires_agent_review(self) -> bool:
        return self.stage == RolloutStage.AGENT_ASSIST
