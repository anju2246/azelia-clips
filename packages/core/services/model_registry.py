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
        
        # 1. Anthropic (Native)
        if hasattr(settings, "anthropic_api_key") and settings.anthropic_api_key:
            try:
                # We do this asynchronously to avoid blocking the thread
                # Native SDK uses sync calls if we don't use AsyncAnthropic
                # To be safe, we use the async client if possible or just run in executor
                from anthropic import AsyncAnthropic
                client = AsyncAnthropic(api_key=settings.anthropic_api_key)
                
                # Fetching models natively
                page = await client.models.list(limit=100)
                for m in page.data:
                    m_id = m.id
                    # Only keep Claude models, no embedding or old claude-1/2/3.0
                    if "claude" in m_id and not "claude-1" in m_id and not "claude-2" in m_id:
                        is_reasoning = "thinking" in m.display_name.lower() if hasattr(m, "display_name") else False
                        name = m.display_name if hasattr(m, "display_name") else m_id.replace("claude-", "Claude ").replace("-", " ").title()
                        
                        # Fix ugly API names
                        if "Sonnet" in name:
                            name = name.replace("Sonnet Latest", "Sonnet").replace("Sonnet 2024", "Sonnet")
                        
                        new_models[m_id] = ModelInfo(
                            id=m_id,
                            name=name,
                            provider="anthropic",
                            context_length=200000,
                            description=f"Anthropic {name}",
                            is_reasoning=is_reasoning
                        )
            except Exception as e:
                logger.error(f"Anthropic model fetch failed: {e}")

        # 2. OpenAI
        if hasattr(settings, "openai_api_key") and settings.openai_api_key:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.openai_api_key)
                models_page = await client.models.list()
                
                for m in models_page.data:
                    m_id = m.id
                    # Strict filtering for premium/modern models
                    if m_id.startswith("gpt-4") or m_id.startswith("o1") or m_id.startswith("o3"):
                        # Exclude weird variations
                        if "audio" in m_id or "realtime" in m_id or "-preview" in m_id:
                            continue
                            
                        name = "GPT-4o" if m_id == "gpt-4o" else "GPT-4o Mini" if m_id == "gpt-4o-mini" else m_id.upper()
                        is_reasoning = "o1" in m_id or "o3" in m_id
                        
                        new_models[m_id] = ModelInfo(
                            id=m_id,
                            name=name,
                            provider="openai",
                            context_length=128000,
                            description=f"OpenAI {name}",
                            is_reasoning=is_reasoning
                        )
            except Exception as e:
                logger.error(f"OpenAI model fetch failed: {e}")

        # 3. Groq
        if hasattr(settings, "groq_api_key") and settings.groq_api_key:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=settings.groq_api_key)
                models_page = await client.models.list()
                
                for m in models_page.data:
                    m_id = m.id
                    if "llama-3" in m_id:
                        name = m_id.replace("llama-3.3-", "Llama 3.3 ").replace("llama-3.1-", "Llama 3.1 ").replace("-versatile", " Versatile").replace("-instant", " Instant").title()
                        
                        new_models[m_id] = ModelInfo(
                            id=m_id,
                            name=name,
                            provider="groq",
                            context_length=131072,  # Typical Llama 3 length
                            description=f"Meta {name}",
                            is_reasoning=False
                        )
            except Exception as e:
                logger.error(f"Groq model fetch failed: {e}")

        # 4. Fallback Google / Vertex
        # Vertex enumeration requires active GCP auth which can be flaky
        # We'll inject known stable aliases for Vertex
        if hasattr(settings, "gcp_project_id") and settings.gcp_project_id:
            for gem in ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-pro-exp-02-05", "gemini-2.0-flash"]:
                new_models[gem] = ModelInfo(
                    id=gem,
                    name=gem.replace("-", " ").title().replace("Exp", "Experimental"),
                    provider="vertex",
                    context_length=1000000,
                    description=f"Google {gem}",
                    is_reasoning="think" in gem.lower()
                )
                
        # Swap memory safely
        if new_models:
            self._models = new_models

    async def get_all_models(self) -> List[ModelInfo]:
        """Return all discovered models sorted newest-first by provider then family."""
        await self._refresh_if_needed()
        
        def _sort_key(m: ModelInfo):
            # Provider priority order shown in UI
            provider_order = {"anthropic": 0, "openai": 1, "groq": 2, "vertex": 3}
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
            
            # --- Vertex: gemini-2 > gemini-1, pro > flash ---
            if m.provider == "vertex":
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
        
        provider_order_str = getattr(settings, "ai_provider_order", "groq,openai,anthropic,vertex")
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
            elif p == "vertex" and getattr(settings, "gcp_project_id", None):
                current_provider = "vertex"
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
            return getattr(settings, "vertex_model", "gemini-2.5-pro")

# Singleton instance
model_registry = ModelRegistry()
