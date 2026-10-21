"""Tool catalog selection for a gateway turn, including exact-channel overrides."""

from __future__ import annotations

import logging
from typing import Optional

from gateway.session import SessionSource

logger = logging.getLogger(__name__)


class GatewayTurnToolsMixin:
    def _resolve_enabled_toolsets_for_source(
        self, user_config: dict, source: SessionSource, platform_key: str,
    ) -> list:
        """Apply an exact-channel catalog, else the platform and adapter configuration."""
        protected = self._protected_channel_toolsets(source)
        if protected is not None:
            from gateway.protected_channel_tools import effective_toolsets
            return effective_toolsets(protected)
        from hermes_cli.tools_config import _get_platform_tools
        try:
            adapter = self._delivery_adapter_for(source)
            override = adapter.toolsets_for_source(source) if adapter is not None else None
        except Exception:
            logger.debug("Adapter toolset override failed; using platform selection", exc_info=True)
            override = None
        if override and isinstance(override, list):
            pts = dict(user_config.get("platform_toolsets") or {})
            pts[platform_key] = [str(x) for x in override]
            user_config = {**user_config, "platform_toolsets": pts}
        return sorted(_get_platform_tools(user_config, platform_key))

    def _protected_channel_toolsets(self, source: SessionSource):
        """Exact receiving-bot policy, including refusal on missing provenance."""
        from gateway.protected_channel_tools import policy_for_source
        from gateway.session_identity import identity_of

        identity = identity_of(source)
        return policy_for_source(
            getattr(self, "config", None), source,
            transport_profile=identity.transport_profile if identity else "",
            live_adapter=bool(identity and identity.adapter()),
        )

    def _protected_channel_tool_names(self, source: SessionSource, disabled_toolsets: Optional[list[str]]):
        policy = self._protected_channel_toolsets(source)
        if policy is None:
            return None
        from gateway.protected_channel_tools import allowed_tool_names
        return allowed_tool_names(policy, disabled_toolsets)

    def _resolve_turn_toolsets(self, user_config: dict, source: SessionSource, platform_key: str):
        """``(enabled_toolsets, disabled_toolsets)`` for an agent run on ``source``."""
        from agent.skill_utils import parse_config_string_list
        enabled = self._resolve_enabled_toolsets_for_source(user_config, source, platform_key)
        disabled = parse_config_string_list((user_config.get("agent") or {}).get("disabled_toolsets")) or None
        return enabled, disabled
