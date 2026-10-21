"""Ollama LLM provider for room presence detection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from .base import BaseLLMProvider, PresenceGuess, parse_llm_response

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Ollama LLM provider implementation."""

    async def deduce_presence(
        self,
        hass: HomeAssistant,
        context: dict[str, Any],
        entity_name: str,
        entity_type: str,
        rooms: list[str],
    ) -> PresenceGuess:
        """Query Ollama to deduce room presence."""
        prompt = self._format_context_for_prompt(context, entity_name, entity_type)
        system_prompt = self._get_system_prompt(entity_name, entity_type, rooms)

        _LOGGER.debug(
            "Ollama query for %s (%s): prompt_len=%d",
            entity_name,
            entity_type,
            len(prompt),
        )

        try:

            async def _do_request():
                session = self._get_session()
                async with session.post(
                    f"{self.url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 32,  # Room and confidence lines
                        },
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                        )
                    return await resp.json()

            result = await self._call_with_retry(_do_request)
            raw_answer = result.get("response", "").strip()

            _LOGGER.debug(
                "Ollama response for %s: '%s'",
                entity_name,
                raw_answer[:200],
            )

            room, confidence, reason = parse_llm_response(raw_answer, rooms)
            indicators = self._extract_indicators(context, room, entity_name)
            if reason:
                indicators.insert(0, reason)

            return PresenceGuess(
                room=room,
                confidence=confidence,
                raw_response=raw_answer,
                indicators=indicators,
            )

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Ollama request failed for %s: %s", entity_name, err)
            return self._create_fallback_guess(context, entity_name, entity_type, rooms, str(err))
        except Exception:
            _LOGGER.exception("Unexpected error querying Ollama for %s", entity_name)
            return self._create_fallback_guess(context, entity_name, entity_type, rooms, "Unexpected error")

    async def test_connection(self) -> bool:
        """Test if Ollama is reachable."""
        try:
            session = self._get_session()
            async with session.get(
                f"{self.url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to connect to Ollama: %s", err)
            return False

    async def get_available_models(self) -> list[str]:
        """Get list of available models from Ollama."""
        try:
            session = self._get_session()
            async with session.get(
                f"{self.url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                models = data.get("models", [])
                return [m.get("name", "") for m in models if m.get("name")]
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to get Ollama models: %s", err)
            return []

    # _extract_indicators, _create_fallback_guess inherited from BaseLLMProvider
