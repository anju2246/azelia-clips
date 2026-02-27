"""Multi-provider LLM client with automatic fallback.

Priority order:
1. Llama 4 Scout (Vertex AI) - Primary
2. Llama 3.3 70B (Vertex AI) - Fallback
3. Groq (Llama 3.3 70B) - Free fallback
"""

from typing import Optional
from rich.console import Console

from packages.core.config import settings

console = Console()


class MultiProviderLLM:
    """
    LLM client that tries multiple providers with automatic fallback.
    
    Usage:
        llm = MultiProviderLLM()
        response = llm.chat(system_prompt, user_message)
    """
    
    def __init__(self):
        self.providers = self._init_providers()
        
    def _init_providers(self) -> list[dict]:
        """Initialize available providers from environment based on configured priority order."""
        providers = []
        
        # Determine order from settings or use default fallback order
        provider_order_str = getattr(settings, "ai_provider_order", "groq,openai,anthropic,vertex")
        order_list = [p.strip().lower() for p in provider_order_str.split(",") if p.strip()]
        
        # Build a dictionary of available valid provider configs
        available_configs = {}

        # 1. Anthropic (Claude 3.5 Sonnet)
        if hasattr(settings, "anthropic_api_key") and settings.anthropic_api_key:
            available_configs["anthropic"] = [{
                "name": "claude-3-5-sonnet",
                "model": "claude-3-5-sonnet-20241022",
                "type": "anthropic",
                "api_key": settings.anthropic_api_key,
            }]

        # 2. OpenAI (GPT-4o)
        if hasattr(settings, "openai_api_key") and settings.openai_api_key:
            available_configs["openai"] = [{
                "name": "gpt-4o",
                "model": "gpt-4o",
                "type": "openai",
                "api_key": settings.openai_api_key,
            }]
            
        # 3. Groq (Llama 3.3 70B)
        if hasattr(settings, "groq_api_key") and settings.groq_api_key:
            available_configs["groq"] = [{
                "name": "llama-3.3-70b-groq",
                "model": getattr(settings, "llm_model", "llama-3.3-70b-versatile"),
                "type": "groq",
                "api_key": settings.groq_api_key,
            }]

        # 4. Vertex AI (Google Cloud)
        vertexai_available = True
        try:
            import google.auth
        except ImportError:
            vertexai_available = False
            console.print("[dim]Vertex AI SDKs not installed, skipping cloud providers[/dim]")
        
        if vertexai_available and hasattr(settings, "gcp_project_id") and settings.gcp_project_id:
            available_configs["vertex"] = [
                {
                    "name": "llama-4-scout-vertexai",
                    "model": "meta/llama-4-scout-17b-16e-instruct-maas",
                    "type": "vertexai",
                    "project": settings.gcp_project_id,
                    "location": "us-east5",
                },
                {
                    "name": "llama-3.3-70b-vertexai",
                    "model": "meta/llama-3.3-70b-instruct-maas",
                    "type": "vertexai",
                    "project": settings.gcp_project_id,
                    "location": getattr(settings, "gcp_location", "us-central1"),
                }
            ]
            
        # Assemble standard list ordered by user's AI_PROVIDER_ORDER
        for p_name in order_list:
            if p_name in available_configs:
                providers.extend(available_configs[p_name])
                del available_configs[p_name] # Mark as added

        # Add any remaining configured providers that weren't in the order string
        for remaining_configs in available_configs.values():
            providers.extend(remaining_configs)
        
        if not providers:
            raise ValueError(
                "No LLM providers configured. Please configure at least one API key (Groq, OpenAI, Anthropic, or Vertex) in the Settings Dashboard."
            )
        
        console.print(f"[dim]LLM providers available: {[p['name'] for p in providers]}[/dim]")
        return providers
    
    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        max_retries: int = 2,
    ) -> str:
        """
        Send a chat message, with automatic fallback on failure.
        
        Args:
            system_prompt: System/context prompt
            user_message: User message
            temperature: Sampling temperature
            max_retries: Max retries per provider before fallback
            
        Returns:
            Response text from LLM
        """
        import time
        last_error = None
        
        for provider in self.providers:
            for attempt in range(max_retries):
                try:
                    if provider["type"] == "anthropic":
                        return self._call_anthropic(provider, system_prompt, user_message, temperature)
                    elif provider["type"] == "openai":
                        return self._call_openai(provider, system_prompt, user_message, temperature)
                    elif provider["type"] == "anthropic_vertex":
                        return self._call_anthropic_vertex(provider, system_prompt, user_message, temperature)
                    elif provider["type"] == "vertexai":
                        return self._call_vertexai(provider, system_prompt, user_message, temperature)
                    elif provider["type"] == "groq":
                        return self._call_groq(provider, system_prompt, user_message, temperature)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    
                    # Rate limit -> try next provider immediately
                    if "rate" in error_str or "429" in str(e) or "quota" in error_str:
                        console.print(f"[yellow]Rate limit on {provider['name']}, trying next...[/yellow]")
                        break
                    
                    # Other errors, retry with exponential backoff
                    wait_time = 2 ** attempt  # 1s, 2s, 4s, ...
                    console.print(f"[yellow]Attempt {attempt+1} failed on {provider['name']}: {e}[/yellow]")
                    console.print(f"[dim]   Waiting {wait_time}s before retry...[/dim]")
                    time.sleep(wait_time)
                    continue
        
        raise Exception(f"All LLM providers failed. Last error: {last_error}")
    
    def _call_anthropic(
        self,
        provider: dict,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Call Anthropic API directly."""
        from anthropic import Anthropic
        
        client = Anthropic(api_key=provider["api_key"])
        
        response = client.messages.create(
            model=provider["model"],
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ],
            temperature=temperature,
        )
        
        return response.content[0].text
        
    def _call_openai(
        self,
        provider: dict,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Call OpenAI API."""
        from openai import OpenAI
        
        client = OpenAI(api_key=provider["api_key"])
        
        response = client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=4096,
        )
        
        return response.choices[0].message.content
    
    def _call_anthropic_vertex(
        self,
        provider: dict,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Call Claude via Anthropic's Vertex AI integration."""
        from anthropic import AnthropicVertex
        
        client = AnthropicVertex(
            project_id=provider["project"],
            region=provider["location"],
        )
        
        response = client.messages.create(
            model=provider["model"],
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ],
            temperature=temperature,
        )
        
        return response.content[0].text
    
    def _call_vertexai(
        self,
        provider: dict,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Call Vertex AI using google.genai SDK."""
        from google import genai
        from google.genai.types import GenerateContentConfig
        
        client = genai.Client(
            vertexai=True,
            project=provider["project"],
            location=provider["location"],
        )
        
        # Combine system and user prompts
        full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"
        
        response = client.models.generate_content(
            model=provider["model"],
            contents=full_prompt,
            config=GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=4096,
                response_mime_type="application/json",  # Force valid JSON output
            ),
        )
        
        return response.text
    
    def _call_groq(
        self,
        provider: dict,
        system_prompt: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Call Groq API."""
        from groq import Groq
        
        client = Groq(api_key=provider["api_key"])
        
        response = client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=4000,
        )
        
        return response.choices[0].message.content


# Singleton instance
_llm_instance: Optional[MultiProviderLLM] = None


def get_llm() -> MultiProviderLLM:
    """Get or create the singleton LLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = MultiProviderLLM()
    return _llm_instance


def chat(system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
    """Convenience function to chat with LLM using multi-provider fallback."""
    return get_llm().chat(system_prompt, user_message, temperature)
