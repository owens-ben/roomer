# Adding a provider

A *provider* is the piece of Roomer that sends sensor context to a language model and turns the reply into a room guess. Roomer ships with two registered providers, `ollama` (the default) and `crewai`. This page covers the contract every provider implements, how providers are registered and selected, and how to add and test a new one.

## The contract: `providers/base.py`

Everything a provider needs lives in [`custom_components/roomer/providers/base.py`](https://github.com/owens-ben/roomer/blob/main/custom_components/roomer/providers/base.py).

### `PresenceGuess`

The value every provider returns:

```python
@dataclass
class PresenceGuess:
    room: str  # one of the configured rooms, or "unknown"
    confidence: float  # 0.0 to 1.0
    raw_response: str  # what the model said (shown as a sensor attribute)
    indicators: list[str]  # human-readable signals that support the guess
    source: str = "llm"  # llm, sensor, device_room, device_tracker, prior, sticky, manual_correction

    def to_dict(self) -> dict[str, Any]: ...
```

The coordinator overwrites `room`, `confidence` and `indicators` after `ConfidenceCombiner` has merged your guess with sensor and habit signals (see [Architecture](architecture.md#the-update-cycle)). Your job is to return the model's honest opinion, not a final answer.

### `BaseLLMProvider`

```python
class BaseLLMProvider(ABC):
    def __init__(self, url: str, model: str, timeout: int = 30, **kwargs) -> None
```

The constructor stores `self.url`, `self.model`, `self.timeout` and any extra keyword arguments in `self._extra_config`.

**Abstract methods you must implement:**

| Method | Called by | Must return |
| --- | --- | --- |
| `async deduce_presence(hass, context, entity_name, entity_type, rooms) -> PresenceGuess` | `LLMPresenceCoordinator._process_entity()` on every poll, for every person and pet | A `PresenceGuess`. Do not raise on network errors; return a fallback guess instead (see below). |
| `async test_connection() -> bool` | `LLMPresenceConfigFlow.async_step_user()` when the user submits the provider form | `True` if the server is reachable. A `False` shows the `cannot_connect` error. |
| `async get_available_models() -> list[str]` | The config flow, right after a successful `test_connection()` | Model names for the model dropdown. Return `[]` on failure; the flow then offers `DEFAULT_MODEL`. |

`entity_type` is `"person"` or `"pet"`. `rooms` is the user's configured room list.

**Helpers you inherit:**

| Helper | Use it for |
| --- | --- |
| `_get_session()` / `async_close()` | A shared `aiohttp.ClientSession`, created lazily and closed by `async_unload_entry` in `__init__.py`. Use it instead of opening your own session on every call. |
| `_call_with_retry(coro_factory, max_retries=1, backoff=2.0)` | Pass a zero-argument callable that returns a **new** coroutine each time, such as an inner `async def`. It retries on `aiohttp.ClientError` and timeouts (sleeping `backoff × attempt` seconds), then re-raises the last error. `aiohttp.ClientResponseError` is a `ClientError`, so raising it on a non-200 status gets you a retry. |
| `_format_context_for_prompt(context, entity_name, entity_type)` | Turns the coordinator's context dict into a plain-text prompt: time, camera AI, motion, computers, media, lights, doors, device trackers and climate, in that priority order, then the habit hint and active indicators. The result is capped at `MAX_CONTEXT_CHARS` (4000); lower-priority sections are dropped first. Each section also has its own `_format_*` method if you need to build a custom prompt. |
| `_get_system_prompt(entity_name, entity_type, rooms)` | The standard system prompt (separate rules for people and pets) that asks for `ROOM: <room_name>`. |
| `_extract_indicators(context, room, entity_name=None, room_entities=None)` | Lists the lights, motion, media, PCs and camera detections in the context that support a given room. |
| `_create_fallback_guess(context, entity_name, entity_type, rooms, error_msg="Fallback")` | A rule-based guess for when the model can't be reached: PC on → its room, media playing → its room, otherwise a default room, at 0.3–0.55 confidence. `raw_response` is set to `error_msg`. |

### `parse_llm_response()`

A module-level function, not a method:

```python
def parse_llm_response(response: str, valid_rooms: list[str]) -> tuple[str, float, str]:
    """Returns (room, confidence, reason)."""
```

It accepts, in order of preference:

1. JSON: `{"room": "office", "confidence": 0.8, "reason": "..."}`
2. Structured text: `ROOM: office` with optional `CONFIDENCE: 0.8` and `REASON: ...` lines. Confidence defaults to 0.7.
3. Any valid room name appearing in the text, with an optional `NN%` confidence. Defaults to 0.6.
4. A single-word reply that matches a room. Gets 0.6.

Anything else returns `("unknown", 0.0, "Could not parse response")`. The returned room is lower-cased and always one of `valid_rooms` or `"unknown"`, so you don't need to validate it again.

## How providers are registered and selected

Three files are involved.

**[`providers/__init__.py`](https://github.com/owens-ben/roomer/blob/main/custom_components/roomer/providers/__init__.py)** holds the registry and factory:

```python
_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "ollama": OllamaProvider,
    "crewai": CrewAIProvider,
}


def get_provider(provider_type: str, url: str, model: str, **kwargs) -> BaseLLMProvider:
    ...
    return provider_class(url=url, model=model, **kwargs)
```

An unknown `provider_type` raises `ValueError`. `get_available_providers()` returns the registry keys.

**[`const.py`](https://github.com/owens-ben/roomer/blob/main/custom_components/roomer/const.py)** names the providers and decides which ones users can pick:

```python
PROVIDER_OLLAMA = "ollama"
PROVIDER_CREWAI = "crewai"
PROVIDER_OPENAI = "openai"  # Stubbed
PROVIDER_ANTHROPIC = "anthropic"  # Stubbed

SUPPORTED_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI]
ALL_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI, PROVIDER_OPENAI, PROVIDER_ANTHROPIC]
```

**[`config_flow.py`](https://github.com/owens-ben/roomer/blob/main/custom_components/roomer/config_flow.py)**: `async_step_user` shows `SUPPORTED_PROVIDERS` in a dropdown next to a URL field (default `DEFAULT_URL`, the Ollama address) and a poll interval. On submit it calls `get_provider(provider_type, url, model)`, then `test_connection()` and `get_available_models()`. The chosen provider is saved as `CONF_PROVIDER` in the config entry.

At runtime, `LLMPresenceCoordinator.__init__` builds the provider once:

```python
self.provider = get_provider(
    provider_type=self.provider_type,
    url=self.provider_url,
    model=self.model,
    timeout=self.timeout,
)
```

!!! note "Why OpenAI and Anthropic aren't selectable"
    `providers/openai.py` and `providers/anthropic.py` are implemented and tested, but both require an `api_key` keyword argument. Neither the config flow nor the coordinator passes one (`CONF_API_KEY` exists in `const.py` but nothing uses it), so they are left out of `_PROVIDERS` and `SUPPORTED_PROVIDERS`. Adding an API-key step is a good self-contained contribution. See [If your provider needs extra settings](#if-your-provider-needs-extra-settings).

## Walkthrough: a minimal provider

This example adds a provider for a hypothetical local server, `myserver`, with a `POST /generate` endpoint that returns `{"text": "..."}` and a `GET /models` endpoint that returns `{"models": ["..."]}`. The structure follows [`providers/ollama.py`](https://github.com/owens-ben/roomer/blob/main/custom_components/roomer/providers/ollama.py) closely. Replace the endpoints and payloads with your backend's real API.

### 1. Create `providers/myserver.py`

```python
"""MyServer LLM provider for room presence detection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from .base import BaseLLMProvider, PresenceGuess, parse_llm_response

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class MyServerProvider(BaseLLMProvider):
    """MyServer provider implementation."""

    async def deduce_presence(
        self,
        hass: HomeAssistant,
        context: dict[str, Any],
        entity_name: str,
        entity_type: str,
        rooms: list[str],
    ) -> PresenceGuess:
        """Ask MyServer which room the entity is in."""
        prompt = self._format_context_for_prompt(context, entity_name, entity_type)
        system_prompt = self._get_system_prompt(entity_name, entity_type, rooms)

        try:

            async def _do_request():
                session = self._get_session()
                async with session.post(
                    f"{self.url}/generate",
                    json={"model": self.model, "system": system_prompt, "prompt": prompt},
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        # ClientResponseError is a ClientError, so this is retried
                        raise aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                        )
                    return await resp.json()

            result = await self._call_with_retry(_do_request)
            raw_answer = result.get("text", "").strip()

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
            _LOGGER.warning("MyServer request failed for %s: %s", entity_name, err)
            return self._create_fallback_guess(context, entity_name, entity_type, rooms, str(err))
        except Exception:
            _LOGGER.exception("Unexpected error querying MyServer for %s", entity_name)
            return self._create_fallback_guess(context, entity_name, entity_type, rooms, "Unexpected error")

    async def test_connection(self) -> bool:
        """Return True if MyServer answers."""
        try:
            session = self._get_session()
            async with session.get(
                f"{self.url}/models",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to connect to MyServer: %s", err)
            return False

    async def get_available_models(self) -> list[str]:
        """List models MyServer can run."""
        try:
            session = self._get_session()
            async with session.get(
                f"{self.url}/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []
                data = await response.json()
                return [m for m in data.get("models", []) if m]
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to get MyServer models: %s", err)
            return []
```

Things to copy from the Ollama provider:

- **Never let a network error escape `deduce_presence`.** The coordinator turns an exception into `UpdateFailed`, which makes every Roomer entity unavailable. Return `_create_fallback_guess(...)` instead.
- **Keep responses short.** Ollama sends `temperature: 0.1` and `num_predict: 20`. One `ROOM:` line is all `parse_llm_response` needs, and long generations slow every poll. The default poll interval is 10 seconds and the coordinator queries each person and pet one after another.
- **Respect `self.timeout`.** It comes from the `llm_timeout` option (`CONF_TIMEOUT`, default 30 seconds).

### 2. Register it

In `providers/__init__.py`:

```python
from .myserver import MyServerProvider

_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "ollama": OllamaProvider,
    "crewai": CrewAIProvider,
    "myserver": MyServerProvider,
}

__all__ = [..., "MyServerProvider"]
```

In `const.py`:

```python
PROVIDER_MYSERVER = "myserver"

SUPPORTED_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI, PROVIDER_MYSERVER]
ALL_PROVIDERS = [PROVIDER_OLLAMA, PROVIDER_CREWAI, PROVIDER_MYSERVER, PROVIDER_OPENAI, PROVIDER_ANTHROPIC]
```

Keep the registry key, the `PROVIDER_*` value and the dropdown option identical. The config flow stores the dropdown value and the coordinator passes it straight to `get_provider()`.

### 3. Check the config flow

With only a URL and a model, nothing else in the config flow needs to change. Your provider appears in the dropdown and the URL field accepts any address. The URL field defaults to the Ollama address (`DEFAULT_URL`), so tell users what to enter. If you want a provider-specific default (like `DEFAULT_CREWAI_URL` in `const.py`), you have to add that logic to `async_step_user` yourself.

### If your provider needs extra settings

API keys or other options need changes in three places:

1. **Config flow**: add a field (or a separate step) to `LLMPresenceConfigFlow`, store it under a key in `self._data` (for example `CONF_API_KEY`), and add its label to `strings.json` and `translations/en.json`.
2. **Config flow connection test**: pass the value to `get_provider(...)` in `async_step_user` so `test_connection()` can authenticate.
3. **Coordinator**: pass the value to `get_provider(...)` in `LLMPresenceCoordinator.__init__`, for example `api_key=self._get_config(entry, CONF_API_KEY)`.

Inside your provider, read extra keyword arguments from `kwargs` in `__init__` (as `OpenAIProvider` does with `api_key`) or later from `self._extra_config`.

## Testing your provider

Provider tests are plain pytest with `unittest.mock`. No running HA or LLM is needed. Model yours on:

- [`tests/test_providers.py`](https://github.com/owens-ben/roomer/blob/main/tests/test_providers.py): `PresenceGuess`, prompt formatting, system prompts, `OllamaProvider` connection tests, indicators and fallback guesses.
- [`tests/test_multi_providers.py`](https://github.com/owens-ben/roomer/blob/main/tests/test_multi_providers.py): the `get_provider` factory, `SUPPORTED_PROVIDERS` / `ALL_PROVIDERS`, OpenAI/Anthropic `deduce_presence` with `_call_api` patched, and `parse_llm_response`.
- [`tests/test_providers_crewai.py`](https://github.com/owens-ben/roomer/blob/main/tests/test_providers_crewai.py): a full `deduce_presence` round trip with a mocked `aiohttp.ClientSession`, including the fallback on HTTP 500.

Shared fixtures such as `sample_context` live in [`tests/conftest.py`](https://github.com/owens-ben/roomer/blob/main/tests/conftest.py).

A starting `tests/test_providers_myserver.py`:

```python
"""Tests for the MyServer provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.roomer.const import SUPPORTED_PROVIDERS, VALID_ROOMS
from custom_components.roomer.providers import get_provider
from custom_components.roomer.providers.base import PresenceGuess
from custom_components.roomer.providers.myserver import MyServerProvider


def test_factory_returns_myserver():
    provider = get_provider("myserver", "http://localhost:9000", "tiny")
    assert isinstance(provider, MyServerProvider)
    assert "myserver" in SUPPORTED_PROVIDERS


@pytest.mark.asyncio
async def test_deduce_presence_parses_room(sample_context):
    provider = MyServerProvider(url="http://localhost:9000", model="tiny")
    # Bypass HTTP entirely: _call_with_retry returns the decoded JSON body
    provider._call_with_retry = AsyncMock(return_value={"text": "ROOM: office"})

    result = await provider.deduce_presence(
        hass=MagicMock(),
        context=sample_context,
        entity_name="Alice",
        entity_type="person",
        rooms=VALID_ROOMS,
    )

    assert isinstance(result, PresenceGuess)
    assert result.room == "office"
    assert result.confidence == 0.7  # parse_llm_response default for "ROOM:" with no CONFIDENCE


@pytest.mark.asyncio
async def test_deduce_presence_falls_back_on_network_error(sample_context):
    provider = MyServerProvider(url="http://localhost:9000", model="tiny")
    provider._call_with_retry = AsyncMock(side_effect=aiohttp.ClientError("boom"))

    result = await provider.deduce_presence(
        MagicMock(),
        sample_context,
        "Alice",
        "person",
        VALID_ROOMS,
    )

    assert isinstance(result, PresenceGuess)
    assert result.raw_response == "boom"  # _create_fallback_guess stores error_msg here
    assert result.confidence <= 0.55
```

Patching `_call_with_retry` keeps the tests fast. If you go through a mocked `aiohttp.ClientSession` instead, as `test_providers_crewai.py` does, a non-200 response triggers one real retry and a 2-second `asyncio.sleep`. To test the HTTP layer itself (URL, payload, status handling), copy the `ClientSession` mocking pattern from `test_providers_crewai.py`, and patch `aiohttp.ClientSession` before the provider creates its session: `_get_session()` caches the first session it creates.

Also test `test_connection()` for both success and failure, and `get_available_models()` returning `[]` on error, because the config flow depends on both. Then run the suite and ruff as described in [Dev setup](dev-setup.md).
