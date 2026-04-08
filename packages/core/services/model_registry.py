import asyncio
import time
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
import logging

try:
    from packages.core.config import settings
except ImportError:
    settings = None

# Configure logger
logger = logging.getLogger(__name__)

class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    context_length: int = 128000
    description: str = ""
    is_reasoning: bool = False

class ModelRegistry:
    """
    Centralized dynamic model registry that queries native SDKs directly.
    Replaces frontend hardcoded lists to prevent 404s.
    """
    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._last_refresh = 0.0
        self._ttl_sec = 1800  # 30 mins caching
        self._is_refreshing = False
    
    async def _refresh_if_needed(self):
        now = time.time()
        if now - self._last_refresh < self._ttl_sec and self._models:
            return
            
        if self._is_refreshing:
            return
            
        self._is_refreshing = True
        try:
            await self._refresh_from_providers()
            self._last_refresh = time.time()
        except Exception as e:
            logger.error(f"Failed to refresh models: {e}")
        finally:
            self._is_refreshing = False

    async def _refresh_from_providers(self):
        """Fetch models dynamically from native SDKs"""
        new_models = {}
        
        from packages.core.config import settings
        
        import re

        def _anthropic_family(m_id: str) -> str:
            if "opus" in m_id: return "opus"
            if "sonnet" in m_id: return "sonnet"
            if "haiku" in m_id: return "haiku"
            return "other"

        def _anthropic_version(m_id: str):
            # Extract (major, minor) — e.g. claude-opus-4-6 → (4,6), claude-3-5-sonnet → (3,5)
            ver = re.search(r'-(\d+)(?:-(\d+))?(?:-\d{8})?(?:-latest)?$', m_id)
            if ver:
                return (int(ver.group(1)), int(ver.group(2) or 0))
            return (0, 0)

        # 1. Anthropic (Native) — keep only the LATEST per family (opus/sonnet/haiku)
        if hasattr(settings, "anthropic_api_key") and settings.anthropic_api_key:
            try:
                from anthropic import AsyncAnthropic
                client = AsyncAnthropic(api_key=settings.anthropic_api_key)
                page = await client.models.list(limit=100)

                # Collect all valid Claude models, then de-duplicate to latest per family
                candidates: dict[str, list] = {"opus": [], "sonnet": [], "haiku": []}
                for m in page.data:
                    m_id = m.id
                    if "claude" not in m_id:
                        continue
                    family = _anthropic_family(m_id)
                    if family not in candidates:
                        continue
                    ver = _anthropic_version(m_id)
                    display = m.display_name if hasattr(m, "display_name") and m.display_name else m_id
                    candidates[family].append((ver, m_id, display))

                for family, items in candidates.items():
                    if not items:
                        continue
                    # Pick the one with the highest version number
                    items.sort(key=lambda x: x[0], reverse=True)
                    _, best_id, best_name = items[0]
                    is_reasoning = "thinking" in best_name.lower()
                    new_models[best_id] = ModelInfo(
                        id=best_id,
                        name=best_name,
                        provider="anthropic",
                        context_length=200000,
                        description=f"Anthropic {best_name}",
                        is_reasoning=is_reasoning,
                    )
            except Exception as e:
                logger.error(f"Anthropic model fetch failed: {e}")

        # 2. OpenAI — keep only flagship models (gpt-4o latest, o3, o4-mini if available)
        if hasattr(settings, "openai_api_key") and settings.openai_api_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.openai_api_key)
                models_page = await client.models.list()

                # Collect candidates per family, pick latest
                oai_families: dict[str, list] = {"gpt-4o": [], "gpt-4o-mini": [], "o3": [], "o4-mini": [], "o1": []}
                for m in models_page.data:
                    m_id = m.id
                    if "audio" in m_id or "realtime" in m_id or "embed" in m_id or "tts" in m_id or "whisper" in m_id or "dall" in m_id:
                        continue
                    if m_id == "gpt-4o" or (m_id.startswith("gpt-4o-") and not "mini" in m_id and not "preview" in m_id):
                        # Date-stamped variants like gpt-4o-2024-11-20 — extract date
                        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', m_id)
                        oai_families["gpt-4o"].append((date_m.group(1) if date_m else "9999", m_id))
                    elif m_id == "gpt-4o-mini" or m_id.startswith("gpt-4o-mini-"):
                        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', m_id)
                        oai_families["gpt-4o-mini"].append((date_m.group(1) if date_m else "9999", m_id))
                    elif m_id.startswith("o4-mini"):
                        oai_families["o4-mini"].append(("0", m_id))
                    elif m_id.startswith("o3") and not "mini" in m_id:
                        oai_families["o3"].append(("0", m_id))
                    elif m_id.startswith("o1") and not "mini" in m_id and not "preview" in m_id:
                        oai_families["o1"].append(("0", m_id))

                oai_display = {
                    "gpt-4o": ("GPT-4o", False, 128000),
                    "gpt-4o-mini": ("GPT-4o Mini", False, 128000),
                    "o3": ("o3", True, 200000),
                    "o4-mini": ("o4-mini", True, 200000),
                    "o1": ("o1", True, 200000),
                }
                for family, items in oai_families.items():
                    if not items:
                        continue
                    items.sort(reverse=True)
                    best_id = items[0][1]
                    name, is_reasoning, ctx = oai_display[family]
                    new_models[best_id] = ModelInfo(
                        id=best_id, name=name, provider="openai",
                        context_length=ctx, description=f"OpenAI {name}",
                        is_reasoning=is_reasoning,
                    )
            except Exception as e:
                logger.error(f"OpenAI model fetch failed: {e}")

        # 3. Groq — keep only the latest Llama version (highest major.minor)
        if hasattr(settings, "groq_api_key") and settings.groq_api_key:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.groq_api_key)
                models_page = await client.models.list()

                groq_candidates: list = []
                for m in models_page.data:
                    m_id = m.id
                    ver = re.search(r'llama-3\.(\d+)-(\d+)b', m_id)
                    if ver:
                        minor, size = int(ver.group(1)), int(ver.group(2))
                        groq_candidates.append((minor, size, m_id))

                if groq_candidates:
                    groq_candidates.sort(reverse=True)
                    best_id = groq_candidates[0][2]
                    name = best_id.replace("llama-3.3-", "Llama 3.3 ").replace("llama-3.1-", "Llama 3.1 ").replace("-versatile", " Versatile").replace("-instant", " Instant").title()
                    new_models[best_id] = ModelInfo(
                        id=best_id, name=name, provider="groq",
                        context_length=131072, description=f"Meta {name}",
                        is_reasoning=False,
                    )
            except Exception as e:
                logger.error(f"Groq model fetch failed: {e}")

        # 4. Google AI (Gemini via AI Studio — google.genai SDK, simple API key)
        if hasattr(settings, "google_api_key") and settings.google_api_key:
            try:
                from google import genai as google_genai
                client = google_genai.Client(api_key=settings.google_api_key)
                raw = client.models.list()
                gemini_candidates: list = []
                for m in raw:
                    m_id = getattr(m, "name", "").replace("models/", "")
                    if "gemini" not in m_id:
                        continue
                    # Skip embedding / image / tts models
                    if any(x in m_id for x in ("embed", "image", "tts", "aqa")):
                        continue
                    display = getattr(m, "display_name", None) or m_id
                    ver = re.search(r"gemini-(\d+)", m_id)
                    major = int(ver.group(1)) if ver else 0
                    tier = 0 if "pro" in m_id else (1 if "flash" in m_id else 2)
                    gemini_candidates.append((major, tier, m_id, display))

                # Keep best per (major, tier) — latest 2.5-pro, latest 2.5-flash, etc.
                seen_tiers: set = set()
                gemini_candidates.sort(reverse=True)
                for major, tier, m_id, display in gemini_candidates:
                    key = (major, tier)
                    if key in seen_tiers:
                        continue
                    seen_tiers.add(key)
                    new_models[m_id] = ModelInfo(
                        id=m_id, name=display, provider="google",
                        context_length=1000000, description=f"Google {display}",
                        is_reasoning=False,
                    )
            except Exception as e:
                logger.error(f"Google AI model fetch failed: {e}")
                
        # Swap memory safely
        if new_models:
            self._models = new_models

    async def get_all_models(self) -> List[ModelInfo]:
        """Return all discovered models sorted newest-first by provider then family."""
        await self._refresh_if_needed()
        
        def _sort_key(m: ModelInfo):
            # Provider priority order shown in UI
            provider_order = {"anthropic": 0, "openai": 1, "groq": 2, "google": 3}
            p = provider_order.get(m.provider, 99)
            
            mid = m.id.lower()
            
            # --- Anthropic: extract major.minor from patterns like claude-opus-4-6, claude-3-5-sonnet ---
            if m.provider == "anthropic":
                import re
                # Match patterns like claude-opus-4-6 or claude-3-7-sonnet (major[-minor])
                ver = re.search(r'-(\d+)(?:-(\d+))?(?:-|$)', mid)
                if ver:
                    major = int(ver.group(1))
                    minor = int(ver.group(2)) if ver.group(2) else 0
                else:
                    major, minor = 0, 0
                # Family rank: opus > sonnet > haiku
                family_rank = 0 if "opus" in mid else (1 if "sonnet" in mid else 2)
                # Negate for descending (newest first)
                return (p, -major, -minor, family_rank, m.id)
            
            # --- OpenAI: gpt-4o > o3 > o1 > gpt-4 ---
            if m.provider == "openai":
                if "gpt-4o" in mid: ver_p = 0
                elif mid.startswith("o3"): ver_p = 1
                elif mid.startswith("o1"): ver_p = 2
                elif "gpt-4" in mid: ver_p = 3
                else: ver_p = 9
                return (p, ver_p, m.id)
            
            # --- Groq: sort by llama version descending ---
            if m.provider == "groq":
                import re
                ver = re.search(r'llama-3\.(\d+)', mid)
                minor = int(ver.group(1)) if ver else 0
                return (p, -minor, m.id)
            
            # --- Google: gemini-2 > gemini-1, pro > flash ---
            if m.provider == "google":
                import re
                ver = re.search(r'gemini-(\d+)', mid)
                major = int(ver.group(1)) if ver else 0
                tier = 0 if "pro" in mid else (1 if "flash" in mid else 2)
                return (p, -major, tier, m.id)
            
            return (p, m.id)
        
        return sorted(self._models.values(), key=_sort_key)

    async def force_refresh(self):
        """Force the cache to refresh immediately"""
        self._last_refresh = 0.0
        await self._refresh_if_needed()
        return list(self._models.values())

    def resolve(self, alias: str) -> str:
        """
        Resolve an alias (e.g. 'primary_reasoner', 'fast_curator', 'cheap_summarizer')
        to the best available literal Model ID string present in the config.
        """
        # We don't block here. We use whatever the user set in their settings,
        # but if they didn't set anything, we fallback safely.
        # It takes the current selected provider based on config priority.
        
        from packages.core.config import settings
        
        provider_order_str = getattr(settings, "ai_provider_order", "groq,openai,anthropic,google")
        order_list = [p.strip().lower() for p in provider_order_str.split(",") if p.strip()]

        # Determine current main provider
        current_provider = None
        for p in order_list:
            if p == "anthropic" and settings.anthropic_api_key:
                current_provider = "anthropic"
                break
            elif p == "openai" and settings.openai_api_key:
                current_provider = "openai"
                break
            elif p == "groq" and settings.groq_api_key:
                current_provider = "groq"
                break
            elif p == "google" and getattr(settings, "google_api_key", None):
                current_provider = "google"
                break
                
        if not current_provider:
            return "claude-3-7-sonnet-latest" # System fallback
            
        if current_provider == "anthropic":
            return getattr(settings, "anthropic_model", "claude-3-7-sonnet-latest")
        elif current_provider == "openai":
            return getattr(settings, "openai_model", "gpt-4o")
        elif current_provider == "groq":
            return getattr(settings, "groq_model", "llama-3.3-70b-versatile")
        else:
            return getattr(settings, "google_model", "gemini-2.5-pro")

# Singleton instance
model_registry = ModelRegistry()
