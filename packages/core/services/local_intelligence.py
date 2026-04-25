"""
Local Intelligence Service — User-scoped pattern analysis for personalized curation.

Architecture:
  - Reads ONLY the user's own telemetry from Supabase (ic_telemetry_events)
  - Three modes (cascade priority):
    1. API (Groq + Llama 3.3): Cloud-based analysis, fastest, uses existing API key
    2. Deep (Ollama + Qwen3.5): Local LLM analysis, no data leaves device
    3. Basic (SQL-only): Statistical aggregation, no LLM needed
  - Results are EPHEMERAL in memory and cached in Supabase with 7-day TTL
  - Never writes intelligence to local disk (protects IC moat)

Rules:
  1. Minimum 5 processing runs before activating (insufficient data otherwise)
  2. Graceful fallback: API → Ollama → basic mode, no Supabase → empty dict
  3. Cache TTL: 7 days in ic_user_intelligence table
  4. Fire-and-forget: never blocks or crashes the pipeline
  5. Only anonymized aggregated stats are sent to API (no titles, transcripts, PII)
"""

import json
import time
import requests
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from rich.console import Console

console = Console()

# TTL for cached intelligence (7 days in seconds)
CACHE_TTL_SECONDS = 7 * 24 * 3600
MIN_EVENTS_THRESHOLD = 5


class LocalIntelligenceService:
    """
    Reads the user's own telemetry and generates personalized curation insights.
    
    Cascade architecture:
      1. API mode (Groq + Llama 3.3) — if groq_api_key configured
      2. Deep mode (Ollama + Qwen3.5-2B) — if Ollama installed locally
      3. Basic mode (SQL aggregation) — always available as fallback
    """

    def __init__(self):
        self._ollama_available: Optional[bool] = None  # Lazy-checked
        self._api_available: bool = False
        self._supabase = None
        self._init_supabase()
        self._init_api()

    def _init_supabase(self):
        """Initialize Supabase client (reuses config from telemetry)."""
        try:
            from packages.core.config import settings
            if settings.supabase_url and settings.supabase_key:
                from supabase import create_client
                self._supabase = create_client(settings.supabase_url, settings.supabase_key)
        except Exception as e:
            console.print(f"[dim][LI] Supabase not available: {e}[/dim]")

    def _init_api(self):
        """Check if any cloud API is configured."""
        try:
            from packages.core.config import settings
            self._api_available = bool(
                settings.groq_api_key or 
                settings.openai_api_key or 
                settings.anthropic_api_key or 
                settings.gcp_project_id
            )
        except Exception:
            self._api_available = False

    @property
    def api_available(self) -> bool:
        """Check if API-based intelligence is available."""
        return self._api_available

    def _check_ollama(self) -> bool:
        """Check if Ollama is running locally and qwen3.5 model is available."""
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code == 200:
                models = [m.get("name", "") for m in r.json().get("models", [])]
                has_qwen = any("qwen3.5" in m for m in models)
                if has_qwen:
                    console.print("[dim]   🧠 Ollama + Qwen3.5 detected → Deep Intelligence enabled[/dim]")
                return has_qwen
        except Exception:
            pass
        return False

    @property
    def ollama_available(self) -> bool:
        """Lazy-check Ollama availability (only checked once per session)."""
        if self._ollama_available is None:
            self._ollama_available = self._check_ollama()
        return self._ollama_available

    def get_user_patterns(self, user_id: str) -> Dict[str, Any]:
        """
        Returns personalized curation insights based on the user's telemetry history.
        
        The result is EPHEMERAL — it lives only in the caller's RAM and is never
        written to local disk. Cached in Supabase with 7-day TTL.

        Args:
            user_id: The user's UUID from Supabase auth
            
        Returns:
            {
                "high_retention_patterns": ["Pattern description 1", ...],
                "preferred_clip_formats": ["Format preference 1", ...],
                "based_on_runs": int,
                "mode": "deep" | "basic" | "inactive"
            }
        """
        if not self._supabase or user_id == "anonymous":
            return self._empty_result("inactive")

        try:
            # 1. Check cache first (ic_user_intelligence table with TTL)
            cached = self._get_cached_intelligence(user_id)
            if cached:
                # If cached result has podintel_public IC signals, verify user
                # still has Pro tier — podintel is Pro-only. creator_self hints
                # are Free-eligible and must survive the strip.
                if cached.get("ic_signals_count", 0) > 0:
                    tier = self._get_user_tier(user_id)
                    if tier != "pro":
                        cached.pop("ic_signals_count", None)
                        cached.pop("blend_weights", None)
                        # Drop hints prefixed "NICHE SIGNAL" (podintel_public)
                        # but keep "CREATOR SELF" hints — those describe the
                        # user's own content patterns and are free-tier OK.
                        all_patterns = cached.get("high_retention_patterns", []) or []
                        cached["high_retention_patterns"] = [
                            p for p in all_patterns
                            if not str(p).startswith("NICHE SIGNAL")
                        ]

                # Always re-blend creator_self on cache hit — their own
                # signals may have been extracted AFTER the cache was written.
                cached = self._blend_with_creator_self(cached, user_id)

                console.print(
                    f"[green]✓[/green] Local Intelligence: "
                    f"{len(cached.get('high_retention_patterns', []))} patterns loaded "
                    f"from {cached.get('based_on_runs', 0)} runs "
                    f"(mode: {cached.get('mode', 'cached')})"
                )
                return cached

            # 2. Fetch raw telemetry aggregations
            aggregated = self._aggregate_user_events(user_id)
            if not aggregated or aggregated.get("total_events", 0) < MIN_EVENTS_THRESHOLD:
                return self._empty_result("inactive")

            # 3. Generate intelligence (cascade: API → Ollama → SQL basic)
            if self.api_available:
                result = self._generate_api_intelligence(aggregated, user_id)
            elif self.ollama_available:
                result = self._generate_deep_intelligence(aggregated, user_id)
            else:
                result = self._generate_basic_intelligence(aggregated, user_id)

            # 4a. Creator-self signals (always, free or pro). These are the user's
            #     OWN patterns extracted from their YouTube via the Creator Signals
            #     flow, so they should inform every run for that user.
            result = self._blend_with_creator_self(result, user_id)

            # 4b. IC Cascade: blend market signals for Pro users
            tier = self._get_user_tier(user_id)
            if tier in ("pro", "cloud", "enterprise"):
                result = self._blend_with_ic(result, user_id)

            # 5. Cache result in Supabase (fire-and-forget)
            self._cache_intelligence(user_id, result)

            console.print(
                f"[green]✓[/green] Local Intelligence: "
                f"{len(result.get('high_retention_patterns', []))} patterns computed "
                f"from {result.get('based_on_runs', 0)} runs "
                f"(mode: {result.get('mode', 'unknown')})"
            )
            return result

        except Exception as e:
            console.print(f"[dim][LI] Warning: Could not load intelligence: {e}[/dim]")
            return self._empty_result("inactive")

    # ——————————————————————————————————————————————
    # DATA LAYER
    # ——————————————————————————————————————————————

    def _get_cached_intelligence(self, user_id: str) -> Optional[Dict]:
        """Check ic_user_intelligence for a valid (non-expired) cached result."""
        try:
            result = (
                self._supabase.table("ic_user_intelligence")
                .select("weights, based_on_events, mode, expires_at")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if result.data:
                expires_at = result.data.get("expires_at")
                if expires_at:
                    # Parse ISO timestamp and check expiry
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if expiry > datetime.now(timezone.utc):
                        weights = result.data.get("weights", {})
                        return {
                            "high_retention_patterns": weights.get("patterns_text", []),
                            "preferred_clip_formats": weights.get("format_preferences", []),
                            "based_on_runs": result.data.get("based_on_events", 0),
                            "mode": result.data.get("mode", "cached"),
                        }
        except Exception:
            pass  # Table might not exist yet, or no data — that's fine
        return None

    def _aggregate_user_events(self, user_id: str) -> Optional[Dict]:
        """
        Query ic_telemetry_events for this user's clip_signal AND youtube_performance events.
        Returns aggregated stats, NOT raw events.
        When YouTube performance data exists, it overrides predicted scores with real metrics.
        """
        try:
            # Fetch clip_signal events for this user
            result = (
                self._supabase.table("ic_telemetry_events")
                .select("metadata, created_at")
                .eq("user_id", user_id)
                .eq("event_type", "clip_signal")
                .order("created_at", desc=True)
                .limit(500)  # Last 500 signals max
                .execute()
            )

            if not result.data:
                return None

            events = result.data
            total_events = len(events)

            # Aggregate by hook_type
            hook_stats: Dict[str, List[float]] = {}
            durations: List[float] = []
            categories: Dict[str, int] = {}

            for event in events:
                meta = event.get("metadata", {})
                hook = meta.get("hook_type", "unknown")
                score = meta.get("predicted_score", 0)
                duration = meta.get("duration_seconds")
                emotional = meta.get("emotional_charge")

                if hook and score:
                    hook_stats.setdefault(hook, []).append(float(score))

                if duration:
                    durations.append(float(duration))

                if emotional:
                    categories[emotional] = categories.get(emotional, 0) + 1

            # ── YouTube Performance Data (real metrics override predictions) ──
            has_youtube_data = False
            # Deduplicate by youtube_id (keep most recent sync per video)
            latest_yt_metrics: Dict[str, Dict[str, Any]] = {}

            try:
                yt_result = (
                    self._supabase.table("ic_telemetry_events")
                    .select("metadata")
                    .eq("user_id", user_id)
                    .eq("event_type", "youtube_clip_aggregate")
                    .order("created_at", desc=True)
                    .limit(500)
                    .execute()
                )

                if yt_result.data:
                    has_youtube_data = True
                    for yt_event in yt_result.data:
                        meta = yt_event.get("metadata", {})
                        yt_id = meta.get("youtube_id")
                        
                        # Only process if we have an ID and haven't seen it yet
                        # (since we ordered by created_at DESC, the first one we see is the latest)
                        if yt_id and yt_id not in latest_yt_metrics:
                            latest_yt_metrics[yt_id] = meta

            except Exception:
                pass  # YouTube data is optional enhancement

            yt_hook_views: Dict[str, List[int]] = {}
            yt_hook_engagement: Dict[str, List[float]] = {}
            
            for meta in latest_yt_metrics.values():
                hook = meta.get("hook_type")
                views = meta.get("views", 0)
                engagement = meta.get("engagement_rate", 0)

                if hook and views > 0:
                    yt_hook_views.setdefault(hook, []).append(views)
                    yt_hook_engagement.setdefault(hook, []).append(engagement)

            # Compute averages (prefer YouTube real data when available)
            if has_youtube_data and yt_hook_views:
                # Override with YouTube-weighted scores (views as proxy for quality)
                hook_averages = {}
                for hook, views_list in yt_hook_views.items():
                    avg_views = sum(views_list) / len(views_list)
                    engagement_list = yt_hook_engagement.get(hook, [])
                    avg_engagement = sum(engagement_list) / max(len(engagement_list), 1)
                    # Normalize views to 0-100 scale (relative to max)
                    hook_averages[hook] = round(avg_views, 1)

                # Normalize to 0-100 relative scale
                if hook_averages:
                    max_val = max(hook_averages.values()) or 1
                    hook_averages = {
                        h: round(v / max_val * 100, 1) 
                        for h, v in hook_averages.items()
                    }
            else:
                hook_averages = {
                    hook: round(sum(scores) / len(scores), 1)
                    for hook, scores in hook_stats.items()
                    if scores
                }

            # Optimal duration range (from top-scoring clips)
            optimal_duration = None
            if durations:
                sorted_durations = sorted(durations)
                # Use interquartile range for robustness
                q1_idx = len(sorted_durations) // 4
                q3_idx = (len(sorted_durations) * 3) // 4
                optimal_duration = {
                    "min": round(sorted_durations[q1_idx]),
                    "max": round(sorted_durations[q3_idx]),
                }

            return {
                "total_events": total_events,
                "hook_averages": hook_averages,
                "optimal_duration": optimal_duration,
                "top_categories": sorted(categories, key=categories.get, reverse=True)[:3],
                "hook_counts": {h: len(s) for h, s in hook_stats.items()},
                "has_youtube_data": has_youtube_data,
                "youtube_events": len(latest_yt_metrics),
            }

        except Exception as e:
            console.print(f"[dim][LI] Could not aggregate events: {e}[/dim]")
            return None

    # ——————————————————————————————————————————————
    # MODE A: BASIC (SQL + String Templates, no LLM)
    # ——————————————————————————————————————————————

    def _generate_basic_intelligence(self, aggregated: Dict, user_id: str) -> Dict:
        """Generate intelligence using pure statistical analysis (no LLM)."""
        patterns = []
        formats = []

        hook_avgs = aggregated.get("hook_averages", {})
        hook_counts = aggregated.get("hook_counts", {})
        optimal_dur = aggregated.get("optimal_duration")
        top_cats = aggregated.get("top_categories", [])

        # Find best and worst hook types
        if hook_avgs:
            sorted_hooks = sorted(hook_avgs.items(), key=lambda x: x[1], reverse=True)
            best_hook, best_score = sorted_hooks[0]
            overall_avg = sum(hook_avgs.values()) / len(hook_avgs)

            # Patterns are fed INTO the Ranker system prompt, which already
            # has the `Respond in {output_language}` instruction up top — so
            # the LLM will translate these English hints into the creator's
            # language as part of its output. Keep them in English to avoid
            # mixing languages inside the prompt.
            patterns.append(
                f"'{best_hook}' hooks perform best "
                f"(avg score: {best_score}, based on {hook_counts.get(best_hook, 0)} clips)"
            )

            if len(sorted_hooks) > 1:
                second_hook, second_score = sorted_hooks[1]
                patterns.append(
                    f"Second-best hook type: '{second_hook}' "
                    f"(score: {second_score}, {hook_counts.get(second_hook, 0)} clips)"
                )

            # Identify underperformers
            if len(sorted_hooks) > 2:
                worst_hook, worst_score = sorted_hooks[-1]
                if worst_score < overall_avg * 0.85:
                    patterns.append(
                        f"Avoid '{worst_hook}' hooks "
                        f"(score: {worst_score}, significantly below the average {overall_avg:.1f})"
                    )

        # Duration insights
        if optimal_dur:
            formats.append(
                f"Optimal clip duration: {optimal_dur['min']}-{optimal_dur['max']} seconds"
            )

        # Category preferences
        if top_cats:
            formats.append(
                f"Top-retention categories: {', '.join(top_cats[:2])}"
            )

        return {
            "high_retention_patterns": patterns,
            "preferred_clip_formats": formats,
            "based_on_runs": aggregated.get("total_events", 0),
            "mode": "basic",
            "weights": {
                "hook_scores": hook_avgs,
                "optimal_duration": optimal_dur,
                "top_categories": top_cats,
                "patterns_text": patterns,
                "format_preferences": formats,
            },
        }

    # ——————————————————————————————————————————————
    # MODE B: API (MultiProviderLLM)
    # ——————————————————————————————————————————————

    def _generate_api_intelligence(self, aggregated: Dict, user_id: str) -> Dict:
        """Generate intelligence using unified MultiProviderLLM for cloud-based analysis."""
        from packages.core.llm_provider import chat
        from packages.core.ic_contract import VALID_HOOK_TYPES, VALID_CATEGORIES

        # Prepare concise, ANONYMIZED data summary — no PII, no titles
        data_summary = json.dumps({
            "hook_type_scores": aggregated.get("hook_averages", {}),
            "hook_type_counts": aggregated.get("hook_counts", {}),
            "optimal_duration_range": aggregated.get("optimal_duration"),
            "top_emotional_categories": aggregated.get("top_categories", []),
            "total_clips_analyzed": aggregated.get("total_events", 0),
            "has_youtube_data": aggregated.get("has_youtube_data", False),
            "youtube_events": aggregated.get("youtube_events", 0),
        }, indent=2)

        system_prompt = """You are a data analyst specializing in social media content optimization. 
Respond ONLY with valid JSON, no markdown formatting. Do not wrap in ```json."""

        user_prompt = f"""Analyze this content creator's clip performance data and generate specific, actionable curation rules.

DATA:
{data_summary}

Generate exactly 3-5 specific rules for improving this creator's future clip curation.
Focus on:
1. Which hook types work best and why they should be prioritized
2. Optimal clip duration based on their historical performance
3. Any non-obvious correlations between categories, duration, and scores
4. If YouTube real data is available, weight those insights higher than predicted scores

CRITICAL CONSTRAINTS:
You MUST ONLY use words from these exact lists when generating patterns and formats:
VALID HOOK TYPES: {VALID_HOOK_TYPES}
VALID CATEGORIES: {VALID_CATEGORIES}

Respond ONLY with valid JSON matching exactly this schema:
{{
  "patterns": ["rule 1 using canonical words", "rule 2 using canonical words"],
  "format_preferences": ["preference 1", "preference 2"],
  "duration_recommendation": {{"min": 30, "max": 55}}
}}"""

        try:
            content = chat(system_prompt=system_prompt, user_message=user_prompt, temperature=0.3)
            # Remove any markdown backticks if the LLM hallucinated them
            content = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(content)

            patterns = parsed.get("patterns", [])
            formats = parsed.get("format_preferences", [])
            dur_rec = parsed.get("duration_recommendation")
            hook_avgs = aggregated.get("hook_averages", {})

            console.print("[dim]   🌐 API Intelligence → analysis complete[/dim]")

            return {
                "high_retention_patterns": patterns[:5],
                "preferred_clip_formats": formats[:3],
                "based_on_runs": aggregated.get("total_events", 0),
                "mode": "api",
                "weights": {
                    "hook_scores": hook_avgs,
                    "optimal_duration": dur_rec or aggregated.get("optimal_duration"),
                    "top_categories": aggregated.get("top_categories", []),
                    "patterns_text": patterns[:5],
                    "format_preferences": formats[:3],
                },
            }

        except Exception as e:
            console.print(f"[dim][LI] API analysis failed, falling back: {e}[/dim]")

        # Fallback to Ollama or basic
        if self.ollama_available:
            return self._generate_deep_intelligence(aggregated, user_id)
        return self._generate_basic_intelligence(aggregated, user_id)

    # ——————————————————————————————————————————————
    # MODE C: DEEP (Ollama + Qwen3.5-2B)
    # ——————————————————————————————————————————————

    def _generate_deep_intelligence(self, aggregated: Dict, user_id: str) -> Dict:
        """Generate intelligence using local Qwen3.5 LLM for deeper pattern analysis."""
        # Prepare concise data summary for the LLM
        data_summary = json.dumps({
            "hook_type_scores": aggregated.get("hook_averages", {}),
            "hook_type_counts": aggregated.get("hook_counts", {}),
            "optimal_duration_range": aggregated.get("optimal_duration"),
            "top_emotional_categories": aggregated.get("top_categories", []),
            "total_clips_analyzed": aggregated.get("total_events", 0),
        }, indent=2)

        prompt = f"""Analyze this content creator's clip performance data and generate specific, actionable curation rules.

DATA:
{data_summary}

Generate exactly 3-5 specific rules for improving this creator's future clip curation.
Focus on:
1. Which hook types work best and why they should be prioritized
2. Optimal clip duration based on their historical performance
3. Any non-obvious correlations between categories, duration, and scores

Respond ONLY with valid JSON matching this schema:
{{
  "patterns": ["rule 1", "rule 2", "rule 3"],
  "format_preferences": ["preference 1", "preference 2"],
  "duration_recommendation": {{"min": 30, "max": 55}}
}}"""

        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen3.5:2b",
                    "messages": [
                        {"role": "system", "content": "You are a data analyst specializing in social media content optimization. Respond ONLY with valid JSON, no markdown formatting. Disable thinking mode."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 512,
                    },
                },
                timeout=30,
            )

            if response.status_code == 200:
                content = response.json().get("message", {}).get("content", "")
                
                # Clean potential markdown wrapping
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1] if "\n" in content else content
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
                
                parsed = json.loads(content)

                patterns = parsed.get("patterns", [])
                formats = parsed.get("format_preferences", [])
                dur_rec = parsed.get("duration_recommendation")

                hook_avgs = aggregated.get("hook_averages", {})

                return {
                    "high_retention_patterns": patterns[:5],
                    "preferred_clip_formats": formats[:3],
                    "based_on_runs": aggregated.get("total_events", 0),
                    "mode": "deep",
                    "weights": {
                        "hook_scores": hook_avgs,
                        "optimal_duration": dur_rec or aggregated.get("optimal_duration"),
                        "top_categories": aggregated.get("top_categories", []),
                        "patterns_text": patterns[:5],
                        "format_preferences": formats[:3],
                    },
                }

        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            console.print(f"[dim][LI] Deep analysis failed, falling back to basic: {e}[/dim]")

        # Fallback to basic if deep fails
        return self._generate_basic_intelligence(aggregated, user_id)

    # ——————————————————————————————————————————————
    # IC CASCADE (Pro users — market intelligence)
    # ——————————————————————————————————————————————

    def _get_user_tier(self, user_id: str) -> str:
        """Fetch user tier from profiles table. Validates pro_expires_at for Pro users."""
        try:
            result = (
                self._supabase.table("profiles")
                .select("tier, pro_expires_at")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if result.data:
                tier = result.data.get("tier", "free") or "free"
                if tier == "pro":
                    expires_at = result.data.get("pro_expires_at")
                    if not expires_at:
                        return "free"
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if expiry <= datetime.now(timezone.utc):
                        return "free"
                return tier
        except Exception:
            pass
        return "free"

    def _get_user_context(self, user_id: str) -> Dict[str, str]:
        """Fetch user's region, category, episode_format from profiles.preferences."""
        try:
            result = (
                self._supabase.table("profiles")
                .select("preferences, content_niche")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if result.data:
                prefs = result.data.get("preferences") or {}
                return {
                    "region": prefs.get("region", ""),
                    "category": result.data.get("content_niche") or prefs.get("category", ""),
                    "episode_format": prefs.get("episode_format", ""),
                }
        except Exception:
            pass
        return {}

    def _fetch_ic_signals(self, context: Dict[str, str], limit: int = 8) -> list:
        """
        Fetch market intelligence signals from ic_signals (PodFinder data).
        Filtered by user's context (region, category, episode_format).
        """
        try:
            query = (
                self._supabase.table("ic_signals")
                .select("signal_type, pattern, performance_premium, confidence, trend_direction, trend_velocity, saturation")
                .eq("source_type", "podintel_public")
                .eq("is_active", True)
                .gte("confidence", 0.4)
                .order("confidence", desc=True)
                .limit(limit * 3)  # Over-fetch, sort client-side
            )

            # Apply context filters if available
            if context.get("region"):
                query = query.eq("region", context["region"])
            if context.get("category"):
                query = query.eq("category", context["category"])
            if context.get("episode_format"):
                query = query.eq("episode_format", context["episode_format"])

            result = query.execute()

            if not result.data:
                return []

            # Sort by impact score: confidence * abs(premium - 1)
            def impact(s):
                premium = s.get("performance_premium") or 1
                conf = s.get("confidence") or 0
                return conf * abs(premium - 1)

            signals = sorted(result.data, key=impact, reverse=True)
            return signals[:limit]

        except Exception as e:
            console.print(f"[dim][LI] IC signals fetch failed: {e}[/dim]")
            return []

    @staticmethod
    def _signals_to_hints(signals: list) -> List[str]:
        """
        Transform raw IC signals into user-facing hint strings.
        Pure templates, no LLM calls. $0 cost.
        Raw signals NEVER reach the user — only these hints.
        """
        # Hints are fed INTO agent system prompts that already enforce the
        # creator's output language. Keeping these templates in English avoids
        # a second layer of translation and keeps one source of truth.
        TEMPLATES = {
            "clip_hook": "Prioritize '{hook_type}' hooks — high impact in your category",
            "emotion_pattern": "Look for moments with a '{emotional_charge}' tone — they stand out in your segment",
            "duration_pattern": "Optimal duration for your category: {duration_bucket}",
            "temporal_pattern": "Best time to publish: {publish_day} at {publish_hour}h",
            "cta_effect": "Adding a CTA improves engagement in your segment",
            "topic_trend": "The topic '{topic_display}' is gaining traction",
        }

        TREND_PREFIX = {
            "rising": "TRENDING UP: ",
            "falling": "TRENDING DOWN: ",
        }

        hints = []
        for signal in signals:
            st = signal.get("signal_type", "")
            pattern = signal.get("pattern") or {}
            template = TEMPLATES.get(st)
            if not template:
                continue

            try:
                if st == "clip_hook":
                    hint = template.format(hook_type=pattern.get("hook_type", ""))
                elif st == "emotion_pattern":
                    hint = template.format(emotional_charge=pattern.get("emotional_charge", ""))
                elif st == "duration_pattern":
                    hint = template.format(duration_bucket=pattern.get("duration_bucket", ""))
                elif st == "temporal_pattern":
                    hint = template.format(
                        publish_day=pattern.get("publish_day", ""),
                        publish_hour=pattern.get("publish_hour", ""),
                    )
                elif st == "cta_effect":
                    hint = template
                elif st == "topic_trend":
                    hint = template.format(
                        topic_display=pattern.get("topic_display", pattern.get("topic", "")),
                    )
                else:
                    continue
            except (KeyError, TypeError):
                continue

            # Prepend trend context
            trend = signal.get("trend_direction")
            if trend in TREND_PREFIX:
                hint = TREND_PREFIX[trend] + hint

            hints.append(hint)

        return hints

    def _fetch_creator_self_signals(self, user_id: str = "", cohort_hash: str = "", limit: int = 6) -> list:
        """Pull ic_signals where source_type='creator_self' for the given cohort.

        Accepts either a user_id (hash derived here) or a pre-computed cohort
        (used by the Ranker which already has one on the CurationConfig).
        Central implementation — the Ranker and local_intelligence both call it.
        """
        try:
            if not cohort_hash:
                if not user_id:
                    return []
                from packages.core.services.telemetry import _cohort_hash as _ch
                cohort_hash = _ch(user_id) or ""
            if not cohort_hash or not self._supabase:
                return []
            result = (
                self._supabase.table("ic_signals")
                .select("signal_type, pattern, performance_premium, confidence, duration_bucket")
                .eq("source_type", "creator_self")
                .eq("cohort_hash", cohort_hash)
                .eq("is_active", True)
                .order("performance_premium", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as e:
            console.print(f"[dim][LI] creator_self fetch skipped: {e}[/dim]")
            return []

    def fetch_creator_self_hints(self, user_id: str = "", cohort_hash: str = "", limit: int = 6) -> List[str]:
        """Public API: prompt-ready creator_self hints. Used by Ranker."""
        signals = self._fetch_creator_self_signals(user_id=user_id, cohort_hash=cohort_hash, limit=limit)
        return self._creator_self_to_hints(signals)

    @staticmethod
    def _creator_self_to_hints(signals: list) -> List[str]:
        """Render creator_self signals as prompt-ready hints.

        Uses a 'CREATOR SELF' prefix so downstream agents can recognize and
        weight these higher than niche-wide (podintel_public) signals.
        """
        hints: List[str] = []
        for s in signals:
            pat = s.get("pattern") or {}
            hook = pat.get("hook_type")
            emo = pat.get("emotional_charge")
            pp = s.get("performance_premium") or 1.0
            if not hook:
                continue
            line = f"CREATOR SELF · Prefer '{hook}'"
            if emo:
                line += f" ({emo})"
            line += f" — ×{float(pp):.2f} premium in your own past shorts."
            hints.append(line)
        return hints

    def _blend_with_creator_self(self, local_result: Dict, user_id: str) -> Dict:
        """Merge creator_self signals into high_retention_patterns.

        Placed AHEAD of the existing patterns so the agents see these first —
        they describe the creator's own past wins and carry more weight than
        generic or niche-wide signals.
        """
        signals = self._fetch_creator_self_signals(user_id)
        if not signals:
            return local_result
        hints = self._creator_self_to_hints(signals)
        if not hints:
            return local_result

        existing = local_result.get("high_retention_patterns", []) or []
        # Dedupe against anything already present.
        existing_lower = {p.lower() for p in existing}
        new_hints = [h for h in hints if h.lower() not in existing_lower]
        local_result["high_retention_patterns"] = new_hints + existing
        local_result["creator_self_count"] = len(new_hints)
        console.print(
            f"[dim]   🎯 Creator-self signals: {len(new_hints)} hints merged[/dim]"
        )
        return local_result

    def _blend_with_ic(self, local_result: Dict, user_id: str) -> Dict:
        """
        For Pro users: fetch IC market signals, transform to hints,
        and blend with local patterns using bayesian weight.
        """
        context = self._get_user_context(user_id)
        ic_signals = self._fetch_ic_signals(context)

        if not ic_signals:
            return local_result

        ic_hints = self._signals_to_hints(ic_signals)
        if not ic_hints:
            return local_result

        # Bayesian blend: more user data → less weight on market signals
        from packages.core.ic_contract import compute_bayesian_weight
        user_runs = local_result.get("based_on_runs", 0)
        weight_user, weight_podintel = compute_bayesian_weight(user_runs)

        local_patterns = local_result.get("high_retention_patterns", [])

        # Interleave: user patterns first (weighted), then IC hints
        # With 100+ user events → IC hints become supplementary
        # With <20 user events → IC hints dominate
        num_ic_hints = max(1, int(len(ic_hints) * weight_podintel))
        num_local = max(1, int(len(local_patterns) * weight_user)) if local_patterns else 0

        blended_patterns = local_patterns[:num_local] + ic_hints[:num_ic_hints]

        local_result["high_retention_patterns"] = blended_patterns
        local_result["ic_signals_count"] = len(ic_hints)
        local_result["blend_weights"] = {
            "user": round(weight_user, 2),
            "podintel": round(weight_podintel, 2),
        }

        console.print(
            f"[dim]   🌐 IC Cascade: {len(ic_hints)} market hints blended "
            f"(user weight: {weight_user:.0%}, market weight: {weight_podintel:.0%})[/dim]"
        )

        return local_result

    # ——————————————————————————————————————————————
    # CACHING
    # ——————————————————————————————————————————————

    def _cache_intelligence(self, user_id: str, result: Dict):
        """Store intelligence weights in Supabase with TTL (fire-and-forget)."""
        try:
            import threading

            def _upsert():
                try:
                    self._supabase.table("ic_user_intelligence").upsert(
                        {
                            "user_id": user_id,
                            "weights": result.get("weights", {}),
                            "based_on_events": result.get("based_on_runs", 0),
                            "mode": result.get("mode", "basic"),
                            # expires_at is handled by DB default (now() + 7 days)
                        },
                        on_conflict="user_id",
                    ).execute()
                except Exception as e:
                    console.print(f"[dim][LI] Cache write failed: {e}[/dim]")

            threading.Thread(target=_upsert, daemon=True).start()

        except Exception:
            pass  # Never crash the pipeline

    # ——————————————————————————————————————————————
    # HELPERS
    # ——————————————————————————————————————————————

    @staticmethod
    def _empty_result(mode: str = "inactive") -> Dict[str, Any]:
        """Return an empty intelligence result."""
        return {
            "high_retention_patterns": [],
            "preferred_clip_formats": [],
            "based_on_runs": 0,
            "mode": mode,
        }


# Global singleton (matches telemetry.py pattern)
local_intelligence = LocalIntelligenceService()

