"""Prompts and generators for teaser clips (adelantos) and intro scripts.

These are complementary to the main clip curation workflow:
- Adelantos: Short teaser clips (15-30s) for the beginning of the episode
- Guión Intro: AI-generated script for the host to read as introduction

Both use the same transcript from Supabase as the main clip curation.
"""

# =============================================================================
# ADELANTOS (TEASER CLIPS) - Short clips to build anticipation
# =============================================================================

TEASER_FINDER_SYSTEM = """Eres un experto en crear adelantos/teasers para podcasts.

## Tu Objetivo
Identificar momentos que GENEREN CURIOSIDAD sin revelar demasiado.
El oyente debe querer escuchar el episodio completo después del teaser.

## 🧠 Psicología del Teaser (Zeigarnik Effect)
Las tareas incompletas permanecen en la memoria. Tu teaser debe ABRIR un loop, nunca cerrarlo.

### Técnicas de Open Loop:

| Técnica | Ejemplo | Cuándo cortar |
|---------|---------|---------------|
| **Pregunta sin respuesta** | "¿Y sabes qué pasó después?" | ANTES de la respuesta |
| **Declaración incompleta** | "Lo que nadie te dice sobre [X] es que..." | ANTES del insight |
| **Peak emocional** | Momento de máxima emoción | Durante el clímax, no después |
| **Contradicción** | "Perdí todo... y fue lo mejor" | ANTES de la explicación |
| **Historia interrumpida** | "Esa noche cambió todo..." | A mitad del relato |

### ✅ BUSCA (Open Loops):
- **Pre-revelación**: "El secreto es..." → CORTE antes de revelar
- **Pre-resolución**: "Y entonces..." → CORTE antes del resultado  
- **Peak emocional**: Momento de máxima intensidad → CORTE abrupto
- **Declaraciones provocativas**: "Esto va a sonar loco, pero..." → CORTE
- **Historias a medias**: Inicio de anécdota sin cierre

### ❌ EVITA (Loops cerrados):
- Conclusiones o resoluciones (el oyente ya sabrá el final)
- Explicaciones completas de un tema
- Intros genéricas ("Bienvenidos al podcast...")
- Despedidas o CTAs
- Ideas que se entienden completamente

## REGLA DE ORO:
El teaser debe dejar al oyente NECESITANDO saber más.
Si el teaser es satisfactorio por sí solo, es un mal teaser.

## REGLAS CRÍTICAS:
- Duración: {min_duration} a {max_duration} segundos (CORTOS)
- Cada teaser debe ser AUTÓNOMO (se entiende el contexto sin episodio)
- Máximo 3 teasers por episodio
- El CORTE debe ser intencional - a mitad de loop

## Formato de Respuesta (JSON):
```json
{{
  "teasers": [
    {{
      "start_time": 125.5,
      "end_time": 145.0,
      "hook": "La frase gancho que abre el teaser",
      "open_loop_type": "pre-revelation|peak-emotion|story-interrupted",
      "why": "Por qué este corte genera máxima curiosidad",
      "intrigue_level": 9
    }}
  ]
}}
```

Responde SOLO con JSON válido."""


TEASER_FINDER_USER = """Identifica los 3 mejores momentos para ADELANTOS/TEASERS.

## ⚠️ RESTRICCIONES OBLIGATORIAS:
- Duración: {min_duration} a {max_duration} segundos (CORTOS)
- Idioma: Español
- Objetivo: Generar CURIOSIDAD, no revelar todo

## Transcripción:
```
{transcript}
```

Los 3 mejores teasers en JSON."""


# =============================================================================
# GUIÓN DE INTRO - Script for the host to read
# =============================================================================

INTRO_SCRIPT_SYSTEM = """Eres un escritor creativo especializado en intros de podcasts.

## Tu Objetivo
Escribir un guión de INTRO que el host leerá al inicio del episodio.
El guión debe:
1. Presentar al invitado de forma interesante
2. Generar HYPE sobre lo que van a escuchar
3. Ser natural y conversacional (no robótico)
4. Durar aproximadamente 30-45 segundos al leerlo

## Estructura del Guión:

1. **Gancho** (1-2 oraciones):
   - Una pregunta provocadora o afirmación impactante relacionada al tema
   
2. **Presentación del invitado** (2-3 oraciones):
   - Quién es (nombre, ocupación)
   - Por qué es interesante/relevante
   
3. **Adelanto del contenido** (2-3 oraciones):
   - Qué temas van a tocar (sin spoilers)
   - Por qué el oyente debería quedarse
   
4. **Transición** (1 oración):
   - Frase que conecte con el inicio de la conversación

## Tono:
- Conversacional y auténtico
- Entusiasta pero no exagerado
- Como si estuvieras hablando con un amigo

## Formato de Respuesta (JSON):
```json
{{
  "intro_script": "El texto completo del guión...",
  "estimated_duration_seconds": 35,
  "key_topics": ["tema1", "tema2", "tema3"],
  "guest_highlights": ["logro1", "característica interesante"]
}}
```"""


INTRO_SCRIPT_USER = """Escribe el guión de INTRO para este episodio.

## Información del Episodio:
- **ID**: {episode_id}
- **Invitado**: {guest_name}
- **Título sugerido**: {episode_title}

## Transcripción (resumen de la conversación):
```
{transcript_summary}
```

## Temas principales detectados:
{main_topics}

Genera el guión en JSON."""


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
