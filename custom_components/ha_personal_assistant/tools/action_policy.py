"""Action Permission Layer (M7) — gates all HA service calls through a policy engine."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ActionDecision(Enum):
    """Result of a policy check."""
    ALLOWED = "allowed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


@dataclass
class PolicyCheckResult:
    """Result of a policy check on a service call."""
    decision: ActionDecision
    domain: str
    service: str
    entity_id: str
    reason: str = ""


@dataclass
class ActionPolicy:
    """Configurable action policy for HA service calls.

    Controls which HA domains/services the agent is allowed to call.
    Three tiers:
      - allowed: Agent can call directly
      - restricted: Requires user confirmation via Telegram
      - blocked: Never callable

    Attributes:
        allowed_domains: Glob or list of allowed domains ('*' for all).
        restricted_domains: Domains requiring confirmation.
        blocked_domains: Domains that are never callable.
        require_confirmation_services: Specific services needing confirmation.
    """
    allowed_domains: str | list[str] = "*"
    restricted_domains: list[str] = field(default_factory=lambda: ["lock", "camera"])
    blocked_domains: list[str] = field(default_factory=lambda: ["homeassistant"])
    require_confirmation_services: list[str] = field(
        default_factory=lambda: [
            "lock.unlock",
            "lock.lock",
            "camera.turn_on",
            "camera.turn_off",
            "camera.enable_motion_detection",
            "camera.disable_motion_detection",
        ]
    )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ActionPolicy:
        """Create an ActionPolicy from config entry data."""
        from ..const import (
            CONF_ALLOWED_DOMAINS,
            CONF_RESTRICTED_DOMAINS,
            CONF_BLOCKED_DOMAINS,
            CONF_REQUIRE_CONFIRMATION_SERVICES,
            DEFAULT_ALLOWED_DOMAINS,
            DEFAULT_RESTRICTED_DOMAINS,
            DEFAULT_BLOCKED_DOMAINS,
            DEFAULT_REQUIRE_CONFIRMATION_SERVICES,
        )

        return cls(
            allowed_domains=config.get(CONF_ALLOWED_DOMAINS, DEFAULT_ALLOWED_DOMAINS),
            restricted_domains=config.get(CONF_RESTRICTED_DOMAINS, DEFAULT_RESTRICTED_DOMAINS),
            blocked_domains=config.get(CONF_BLOCKED_DOMAINS, DEFAULT_BLOCKED_DOMAINS),
            require_confirmation_services=config.get(
                CONF_REQUIRE_CONFIRMATION_SERVICES, DEFAULT_REQUIRE_CONFIRMATION_SERVICES
            ),
        )

    def check(self, domain: str, service: str, entity_id: str = "") -> PolicyCheckResult:
        """Check whether a service call is allowed.

        Args:
            domain: HA domain (e.g., 'light', 'lock').
            service: Service name (e.g., 'turn_on', 'unlock').
            entity_id: Target entity ID (for logging/display).

        Returns:
            PolicyCheckResult with the decision.
        """
        full_service = f"{domain}.{service}"

        # 1. Check blocked domains first
        if domain in self.blocked_domains:
            _LOGGER.warning(
                "Action BLOCKED by policy: %s (domain '%s' is blocked)",
                full_service,
                domain,
            )
            return PolicyCheckResult(
                decision=ActionDecision.BLOCKED,
                domain=domain,
                service=service,
                entity_id=entity_id,
                reason=f"Domain '{domain}' is blocked by policy",
            )

        # 2. Check if specific service requires confirmation
        if full_service in self.require_confirmation_services:
            _LOGGER.info(
                "Action NEEDS CONFIRMATION: %s on %s (service requires confirmation)",
                full_service,
                entity_id,
            )
            return PolicyCheckResult(
                decision=ActionDecision.NEEDS_CONFIRMATION,
                domain=domain,
                service=service,
                entity_id=entity_id,
                reason=f"Service '{full_service}' requires user confirmation",
            )

        # 3. Check restricted domains
        if domain in self.restricted_domains:
            _LOGGER.info(
                "Action NEEDS CONFIRMATION: %s on %s (domain '%s' is restricted)",
                full_service,
                entity_id,
                domain,
            )
            return PolicyCheckResult(
                decision=ActionDecision.NEEDS_CONFIRMATION,
                domain=domain,
                service=service,
                entity_id=entity_id,
                reason=f"Domain '{domain}' is restricted — requires confirmation",
            )

        # 4. Check allowed domains
        if self.allowed_domains == "*" or domain in self.allowed_domains:
            return PolicyCheckResult(
                decision=ActionDecision.ALLOWED,
                domain=domain,
                service=service,
                entity_id=entity_id,
            )

        # If not explicitly allowed, block
        _LOGGER.warning(
            "Action BLOCKED: %s on %s (domain '%s' not in allowed list)",
            full_service,
            entity_id,
            domain,
        )
        return PolicyCheckResult(
            decision=ActionDecision.BLOCKED,
            domain=domain,
            service=service,
            entity_id=entity_id,
            reason=f"Domain '{domain}' is not in the allowed domains list",
        )
