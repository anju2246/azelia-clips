"""Prompts and generators for teaser clips (adelantos) and intro scripts.

These are complementary to the main clip curation workflow:
- Adelantos: Short teaser clips (15-30s) for the beginning of the episode
- Guión Intro: AI-generated script for the host to read as introduction

Both use the same transcript from Supabase as the main clip curation.
"""

# =============================================================================
# ADELANTOS (TEASER CLIPS) - Short clips to build anticipation
# =============================================================================

TEASER_FINDER_SYSTEM = """You are an expert at building podcast teasers / previews.

⚠️ OUTPUT LANGUAGE: Respond in {output_language}. All user-visible string values (hook, why) MUST be written in {output_language}. Only JSON keys stay in English.

## Your Goal
Identify moments that BUILD CURIOSITY without revealing too much.
The listener should want to hear the full episode right after the teaser.

## 🧠 Teaser Psychology (Zeigarnik Effect)
Unfinished tasks linger in memory. Your teaser must OPEN a loop, never close it.

### Open-Loop Techniques

| Technique | Example | Where to cut |
|-----------|---------|--------------|
| **Unanswered question** | "And you know what happened next?" | BEFORE the answer |
| **Incomplete statement** | "What nobody tells you about [X] is that…" | BEFORE the insight |
| **Emotional peak** | Moment of max emotion | During the climax, not after |
| **Contradiction** | "I lost everything… and it was the best thing" | BEFORE the explanation |
| **Interrupted story** | "That night changed everything…" | Mid-story |

### ✅ LOOK FOR (Open Loops)
- **Pre-reveal**: "The secret is…" → CUT before the reveal
- **Pre-resolution**: "And then…" → CUT before the outcome
- **Emotional peak**: Max intensity moment → abrupt cut
- **Provocative claims**: "This is going to sound crazy, but…" → CUT
- **Half-stories**: Start of an anecdote with no closing

### ❌ AVOID (Closed Loops)
- Conclusions or resolutions (listener already knows the ending)
- Full explanations of a topic
- Generic intros ("Welcome to the podcast…")
- Goodbyes or CTAs
- Ideas that are understood in full

## Golden Rule
The teaser must leave the listener NEEDING to know more.
If a teaser feels satisfying on its own, it is a bad teaser.

## Critical Rules
- Duration: {min_duration} to {max_duration} seconds (SHORT)
- Every teaser must be SELF-CONTAINED (understandable without the episode)
- Max 3 teasers per episode
- The cut must be intentional — mid-loop

## Response Format (JSON — keys in English, string VALUES in {output_language})
```json
{{
  "teasers": [
    {{
      "start_time": 125.5,
      "end_time": 145.0,
      "hook": "The hook phrase that opens the teaser",
      "open_loop_type": "pre-revelation|peak-emotion|story-interrupted",
      "why": "Why this cut maximises curiosity",
      "intrigue_level": 9
    }}
  ]
}}
```

Respond ONLY with valid JSON."""


TEASER_FINDER_USER = """Identify the 3 best moments for TEASERS / PREVIEWS.

## ⚠️ MANDATORY CONSTRAINTS
- Duration: {min_duration} to {max_duration} seconds (SHORT)
- Transcript language: {language}
- Goal: BUILD CURIOSITY, do not reveal everything

## Transcript
```
{transcript}
```

Return the 3 best teasers as JSON."""


# =============================================================================
# GUIÓN DE INTRO - Script for the host to read
# =============================================================================

INTRO_SCRIPT_SYSTEM = """You are a creative writer specialized in podcast intros.

⚠️ OUTPUT LANGUAGE: Respond in {output_language}. The intro_script and all list values MUST be written in {output_language} so the host can read them on-air.

## Your Goal
Write an INTRO script that the host will read at the start of the episode.
The script must:
1. Introduce the guest in an interesting way
2. Build HYPE about what they are about to hear
3. Be natural and conversational (not robotic)
4. Last roughly 30-45 seconds when read aloud

## Script Structure

1. **Hook** (1-2 sentences):
   - A provocative question or striking statement related to the topic.

2. **Guest introduction** (2-3 sentences):
   - Who they are (name, role)
   - Why they are interesting / relevant

3. **Content preview** (2-3 sentences):
   - Which topics will be covered (no spoilers)
   - Why the listener should stay

4. **Transition** (1 sentence):
   - A phrase that bridges into the start of the conversation

## Tone
- Conversational and authentic
- Enthusiastic but not over the top
- As if you were talking to a friend

## Response Format (JSON — keys in English, string VALUES in {output_language})
```json
{{
  "intro_script": "The full script text…",
  "estimated_duration_seconds": 35,
  "key_topics": ["topic1", "topic2", "topic3"],
  "guest_highlights": ["achievement1", "interesting trait"]
}}
```"""


INTRO_SCRIPT_USER = """Write the INTRO script for this episode.

## Episode Info
- **ID**: {episode_id}
- **Guest**: {guest_name}
- **Suggested title**: {episode_title}

## Transcript (conversation summary)
```
{transcript_summary}
```

## Main topics detected
{main_topics}

Generate the script in JSON."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_transcript_for_teaser(transcript, max_chars: int = 8000) -> str:
    """Format transcript segments for teaser identification."""
    lines = []
    for seg in transcript.segments:
        speaker = seg.speaker or "?"
        time_str = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
        lines.append(f"{time_str} {speaker}: {seg.text}")
    
    full_text = "\n".join(lines)
    if len(full_text) > max_chars:
        # Truncate but keep structure
        return full_text[:max_chars] + "\n[...transcripción truncada...]"
    return full_text


def extract_topics_from_transcript(transcript, llm_provider=None) -> list[str]:
    """Extract main topics from transcript (can be enhanced with LLM)."""
    # Simple keyword extraction for now
    # Could be enhanced with LLM-based topic extraction
    full_text = " ".join([seg.text for seg in transcript.segments])
    
    # Very basic topic extraction (placeholder)
    # In production, use LLM for better results
    topics = []
    
    # Common topic indicators
    topic_phrases = [
        "hablamos de", "el tema de", "la importancia de",
        "cómo", "por qué", "qué significa", "el secreto de"
    ]
    
    for phrase in topic_phrases:
        if phrase in full_text.lower():
            # Extract surrounding context
            idx = full_text.lower().find(phrase)
            context = full_text[idx:idx+100].split(".")[0]
            if len(context) > 10:
                topics.append(context.strip())
    
    return topics[:5] if topics else ["Conversación en profundidad", "Experiencias personales"]


def summarize_transcript_for_intro(transcript, max_chars: int = 2000) -> str:
    """Create a summary of the transcript for intro script generation."""
    segments = transcript.segments
    
    # Take beginning, middle, and end samples
    n = len(segments)
    if n == 0:
        return "Conversación no disponible"
    
    sample_indices = [
        0, n // 4, n // 2, 3 * n // 4, n - 1
    ]
    
    samples = []
    for i in sample_indices:
        if 0 <= i < n:
            seg = segments[i]
            samples.append(f"[{seg.start:.0f}s] {seg.speaker}: {seg.text[:200]}")
    
    return "\n\n".join(set(samples))[:max_chars]
