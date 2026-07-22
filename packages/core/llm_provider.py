"""Multi-provider LLM client — MVP restricted to Claude Code + Anthropic API.

Priority (configurable via AI_PROVIDER_ORDER):
1. Claude Code (local CLI subscription) — no API key needed, $0 cost
2. Anthropic API — BYOK, pay per token

If both are available, Claude Code is tried first.
"""

import os
import subprocess
from typing import Any, Optional

from rich.console import Console

from packages.core.config import settings

console = Console()


def _claude_cmd() -> str:
    """The Claude Code executable for the active profile (`claude` on PATH if unset)."""
    return getattr(settings, "claude_binary", None) or "claude"


def _claude_env() -> Optional[dict]:
    """Env for the active profile's Claude account (CLAUDE_CONFIG_DIR), or None
    to inherit the process env unchanged."""
    cfg = getattr(settings, "claude_config_dir", None)
    if cfg:
        return {**os.environ, "CLAUDE_CONFIG_DIR": cfg}
    return None


# ─── Provider availability detection ────────────────────────────────────


def claude_code_available() -> bool:
    """True if the active profile's `claude` CLI is installed."""
    try:
        result = subprocess.run(
            [_claude_cmd(), "--version"], capture_output=True, timeout=3, text=True, env=_claude_env()
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def vision_available() -> bool:
    """True if image input is possible. Vision is Claude-Code-only (no Anthropic
    fallback, by product decision): the user's CLI subscription reads the image
    via its Read tool, at $0 cost."""
    return claude_code_available()


def claude_code_authenticated() -> Optional[dict]:
    """Returns auth info dict if Claude Code is authenticated, else None."""
    if not claude_code_available():
        return None
    try:
        # `claude` CLI doesn't have a stable JSON status command, so we run a
        # trivial query and infer auth from exit code.
        result = subprocess.run(
            [_claude_cmd(), "-p", "say only the word ok", "--tools", ""],
            capture_output=True,
            timeout=15,
            text=True,
            env=_claude_env(),
        )
        if result.returncode == 0 and "ok" in result.stdout.lower():
            return {"method": "subscription", "active": True}
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


# ─── Multi-provider client ──────────────────────────────────────────────


class VisionUnavailable(Exception):
    """No vision-capable provider (Claude Code) is available."""


class MultiProviderLLM:
    """LLM client that tries Claude Code, then Anthropic API, with fallback."""

    def __init__(self):
        self.providers = self._init_providers()

    def _init_providers(self) -> list[dict]:
        """Build the provider list in user-configured order."""
        order_str = getattr(settings, "ai_provider_order", "claude_code,anthropic")
        order = [p.strip().lower() for p in order_str.split(",") if p.strip()]

        available: dict[str, dict] = {}

        if "claude_code" in order and claude_code_available():
            available["claude_code"] = {
                "name": "claude-code-cli",
                "type": "claude_code",
            }

        if "anthropic" in order and settings.anthropic_api_key:
            model = settings.anthropic_model or "claude-sonnet-4-6"
            if model.startswith("anthropic/"):
                model = model.replace("anthropic/", "")
            available["anthropic"] = {
                "name": model,
                "model": model,
                "type": "anthropic",
                "api_key": settings.anthropic_api_key,
            }

        providers = [available[name] for name in order if name in available]

        if not providers:
            raise ValueError(
                "No LLM providers available. Configure Anthropic API key in Settings, "
                "or install Claude Code (https://claude.com/download) and authenticate."
            )

        console.print(f"[dim]LLM providers: {[p['name'] for p in providers]}[/dim]")
        return providers

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_retries: int = 2,
        response_format: Any = None,
    ) -> str:
        """Send a chat message, falling back across providers on failure."""
        import time

        last_error: Optional[Exception] = None

        for provider in self.providers:
            for attempt in range(max_retries):
                try:
                    if provider["type"] == "claude_code":
                        return self._call_claude_code(provider, system_prompt, user_message, temperature)
                    if provider["type"] == "anthropic":
                        return self._call_anthropic(provider, system_prompt, user_message, temperature)
                except Exception as e:
                    last_error = e
                    err = str(e).lower()
                    if "rate" in err or "429" in str(e) or "quota" in err:
                        console.print(f"[yellow]Rate limit on {provider['name']}, trying next…[/yellow]")
                        break
                    wait = 2**attempt
                    console.print(f"[yellow]Attempt {attempt+1} failed on {provider['name']}: {e}[/yellow]")
                    time.sleep(wait)

        raise Exception(f"All LLM providers failed. Last error: {last_error}")

    # ─── Provider implementations ───────────────────────────────────────

    def _call_anthropic(self, provider: dict, system_prompt: str, user_message: str, temperature: float) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=provider["api_key"])
        response = client.messages.create(
            model=provider["model"],
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            temperature=temperature,
        )
        return response.content[0].text

    def _call_claude_code(self, provider: dict, system_prompt: str, user_message: str, temperature: float) -> str:
        """Invoke Claude Code CLI in non-interactive mode.

        `claude -p` doesn't have a separate system prompt slot, so we concatenate.
        Temperature is ignored (CLI uses defaults).

        `--tools ""` disables ALL tools: the prompt embeds untrusted transcript
        and user text, and a text-only completion must never be able to run
        Bash/Write/etc. via prompt injection.
        """
        full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"
        try:
            result = subprocess.run(
                [_claude_cmd(), "-p", full_prompt, "--tools", ""],
                capture_output=True,
                text=True,
                timeout=300,
                env=_claude_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise Exception("Claude Code timed out after 5 minutes") from e

        if result.returncode != 0:
            raise Exception(f"Claude Code error (exit {result.returncode}): {result.stderr[:500]}")
        return result.stdout.strip()

    def chat_vision(self, system_prompt: str, user_message: str, image_path: str, temperature: float = 0.7) -> str:
        """Vision turn — Claude-Code-only (no Anthropic fallback).

        The CLI reads the image off disk via its Read tool, so we reference the
        absolute path in the prompt and allow only Read. Verified: `claude -p`
        with `--allowedTools Read` resolves image files.
        """
        if not claude_code_available():
            raise VisionUnavailable(
                "Adjuntar una imagen requiere Claude Code instalado y autenticado."
            )
        full_prompt = (
            f"{system_prompt}\n\n---\n\n"
            f"Imagen de referencia (léela con tu herramienta Read): {image_path}\n\n"
            f"{user_message}"
        )
        try:
            result = subprocess.run(
                [
                    _claude_cmd(), "-p", full_prompt,
                    "--tools", "Read", "--allowedTools", "Read",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                env=_claude_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise Exception("Claude Code timed out after 5 minutes") from e

        if result.returncode != 0:
            raise Exception(f"Claude Code vision error (exit {result.returncode}): {result.stderr[:500]}")
        return result.stdout.strip()


# ─── Singleton ──────────────────────────────────────────────────────────

_llm_instance: Optional[MultiProviderLLM] = None


def get_llm() -> MultiProviderLLM:
    """Get or create the singleton LLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiProviderLLM()
    return _llm_instance


def reset_llm() -> None:
    """Force the next get_llm() to reinitialize (e.g. after Settings change)."""
    global _llm_instance
    _llm_instance = None


def chat(system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
    """Convenience: chat using current provider order."""
    return get_llm().chat(system_prompt, user_message, temperature)
