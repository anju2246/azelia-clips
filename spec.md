# Spec: Recorte por texto confiable en el chat del brief

## Status
Approved

## Purpose
Hacer que, en el chat del brief, **pegar un fragmento del transcript** sobre el clip en foco recorte el clip
al tramo correcto de forma confiable — aun con pequeñas diferencias de transcripción/copiado y aun si el
fragmento cae parcialmente fuera del rango actual del clip — y eliminar la excusa del modelo de que "solo
conoce los rangos del clip / no puede cortar en el medio". Un clip sigue siendo UN rango contiguo
`[start_time, end_time]`; NO se introducen cortes internos multi-span.

## Scope
### In Scope
- `packages/clips/curation/agents/brief_agent.py`: system prompt + inclusión del transcript del clip en foco
  en el mensaje al modelo.
- `packages/clips/curation/brief_actions.py`: `match_text_span` (matching robusto + sesgo de proximidad) y
  `_trim_to_text` (búsqueda en todo el episodio).
- Tests unitarios y un test de validación con fixture real-ish.
### Out of Scope
- Cortes internos / multi-span / concatenación al render.
- Render, reframe, subtítulos, pipeline de video.
- UI (`BriefChatModal.tsx`) salvo contrato forzado por test.
- Otras acciones del applier.

## Tech Stack
- Python 3 (mismo que el repo), Pydantic v2.
- Test runner: `python -m pytest` (comando: `python -m pytest -q`).
- Matching difuso con stdlib (`re`, `difflib`); **sin dependencias nuevas**.

## Core Entities
Sin cambios de modelo. Se reutilizan:

### BriefCandidate (`brief_models.py`)
Campos relevantes: `id:int`, `start_time:float`, `end_time:float`, `transcript:str`, `selected:bool`.

### BriefContext (`brief_actions.py`)
| Campo | Tipo | Notas |
|-------|------|-------|
| episode_duration | float | duración total del episodio (en server real ≈ duración; default 1e9) |
| finder | Callable | sin cambios |
| words_provider | Callable[[float,float], list[(word,start,end)]] | devuelve palabras timed que solapan [ws,we] |

## Features

### F1 — El BriefAgent ve el transcript del clip en foco

**Cambio en `_build_user_message` (`brief_agent.py:85-107`):**
Cuando `focus_id is not None` y existe el candidato en foco con `transcript` no vacío, añadir un bloque:

```
## Transcript del clip en foco #<id>
<texto del transcript del clip en foco, tal cual c.transcript>
```

ubicado justo después del bloque "## Clip en foco" y antes de la conversación previa.

**Reglas:**
1. Si el candidato en foco no tiene `transcript` (vacío), no se añade el bloque (degradación silenciosa; el
   backend sigue resolviendo por matching).
2. El transcript se incluye sin timestamps (texto legible); el modelo no necesita tiempos, solo reconocer la
   zona y emitir `trim_to_text` con `keep_text`.
3. Límite de tamaño defensivo: truncar el transcript del clip en foco a 4000 caracteres (los clips son
   cortos; esto es solo un guard). Si se trunca, añadir " …" al final.

**Cambio en `_SYSTEM_PROMPT` (`brief_agent.py:20-52`):** ampliar la sección "RECORTE POR TEXTO" con:
> Tienes abajo el transcript del clip en foco. **NUNCA** respondas que "solo conoces los rangos del clip" ni
> que "no puedes cortar en el medio": SÍ puedes. Si el usuario pega, cita o describe un fragmento del clip,
> emite `trim_to_text` con `keep_text` = el fragmento citado (o, si lo describe, el tramo correspondiente del
> transcript que ves arriba). El backend resuelve ese texto a tiempos exactos, incluso si el fragmento cae un
> poco fuera del rango actual del clip. Solo usa `noop` si el pedido es genuinamente ambiguo, nunca para
> excusarte de cortar.

**Business Rules:**
1. No cambia el contrato de salida: sigue devolviendo `{"actions":[...]}`.
2. No cambia ninguna otra sección del prompt (foco individual, priorización, etc.).

**Edge Cases:**
| Input | Expected |
|-------|----------|
| `focus_id` con transcript vacío | mensaje sin bloque de transcript; no rompe |
| `focus_id=None` | comportamiento actual (sin bloque de transcript) |
| transcript > 4000 chars | truncado a 4000 + " …" |

### F2 — `match_text_span` robusto con sesgo de proximidad

**Nueva firma (retrocompatible):**
```python
def match_text_span(
    words: List[Tuple[str, float, float]],
    keep_text: str,
    anchor_time: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
```
`anchor_time` es opcional; si es `None`, el comportamiento de desempate por proximidad se omite (se elige la
primera/mejor ocurrencia), preservando los tests actuales que llaman sin anchor.

**Algoritmo (determinista, sin red):**
1. Normalizar a tokens `(token, start, end)` con `_tokens` (igual que hoy). Sea `wt` la lista de tokens del
   transcript y `q` los tokens del `keep_text`. Si `q` o `wt` vacíos → `None`.
2. **Generar candidatos de span.** Buscar TODAS las ventanas contiguas plausibles, no solo la primera:
   - **Ancla exacta de cabeza:** todas las posiciones `i` donde `wt[i:i+k] == q[:k]` (con `k=min(5,len(q))`);
     si ninguna, posiciones donde `wt[i] == q[0]`.
   - **Ancla exacta de cola:** todas las posiciones `j` donde `wt[j-k:j] == q[-k:]`; si ninguna, donde
     `wt[j-1] == q[-1]`.
   - Cada par válido `(i, j)` con `j > i` y longitud razonable (`j-i` entre `0.5*len(q)` y `2.0*len(q)+5`)
     es un candidato de span.
3. **Fallback difuso** (cuando el paso 2 no produce ningún candidato): deslizar una ventana de longitud
   ≈ `len(q)` (probar tamaños en `[max(1,len(q)-2) .. len(q)+2]`) sobre `wt`; para cada ventana calcular el
   ratio de similitud de secuencia con `q` usando `difflib.SequenceMatcher(None, ventana, q).ratio()`.
   Conservar las ventanas con ratio ≥ `0.6` como candidatos.
4. **Selección entre candidatos:**
   - Puntuar cada candidato por (a) calidad de match (anclas exactas > difuso; mayor ratio mejor) y, como
     desempate, (b) **cercanía a `anchor_time`**: menor `abs(span_start - anchor_time)` gana (solo si
     `anchor_time is not None`).
   - Devolver `(words[i].start, words[j-1].end)` del candidato ganador.
5. Si no hay candidatos → `None`.

**Business Rules:**
1. Función pura: mismas entradas → misma salida. Sin estado global, sin `random`, sin red.
2. Tolerante a acentos (se mantienen) y a puntuación/caso (se ignoran), igual que `_tokens` actual.
3. Sin `anchor_time`, ante empate de calidad elige la ocurrencia de menor índice (estable).

**Edge Cases:**
| Input | Expected |
|-------|----------|
| `keep_text` con 1–2 palabras distintas en las puntas vs transcript | resuelve por difuso (ratio ≥ 0.6) |
| frase repetida en el episodio, `anchor_time` cerca de la 2ª | devuelve la 2ª ocurrencia |
| `keep_text` no presente (ratio < 0.6 en todo) | `None` |
| `q` más largo que `wt` | `None` (no hay ventana válida) |
| llamada sin `anchor_time` (tests actuales) | resultado igual o equivalente al actual para casos exactos |

### F3 — `_trim_to_text` busca en todo el episodio

**Cambio en `_trim_to_text` (`brief_actions.py:157-186`):**
1. Reemplazar `words = ctx.words_provider(c.start_time, c.end_time)` por
   `words = ctx.words_provider(0.0, ctx.episode_duration) or []` para obtener TODAS las palabras del episodio.
   (En el server, `words_provider(0, 1e9)` ya devuelve todas las palabras; ver `clips.py:904-917`.)
2. Llamar `span = match_text_span(words, text, anchor_time=c.start_time)` para sesgar a la zona del clip.
3. Validaciones y efectos actuales se conservan: `end > start`; setear `c.start_time/c.end_time`,
   `c.selected = True`, y `c.transcript = _text_in_window(...)`.
4. **Validación de rango contra episodio:** si el span cae fuera de `[0, episode_duration]` (no debería),
   clamp a límites válidos; si tras clamp `end <= start`, tratar como no encontrado.
5. Mensaje de error (no encontrado) más claro:
   `"No encontré ese fragmento en el episodio para #{id}; pégalo un poco más largo o tal cual aparece."`

**Business Rules:**
1. El recorte puede mover el clip **fuera** de su `[start,end]` original (p. ej. extender el final) — es el
   objetivo: el fragmento manda, no la ventana previa.
2. Sigue siendo un único rango contiguo. No se generan múltiples segmentos.
3. Determinista; sin red. La única pieza con red es el BriefAgent (F1).

**Edge Cases:**
| Input | Expected |
|-------|----------|
| fragmento parcialmente fuera del `[a,b]` actual | span final cubre el fragmento (clip se mueve/extiende) |
| fragmento ausente en todo el episodio | mensaje "No encontré…", clip sin cambios, `ok=True` |
| `ctx.words_provider is None` | `BriefActionError` (igual que hoy) |
| `episode_duration` = default grande (1e9) | funciona; `words_provider` devuelve todas las palabras |

## Non-Functional Requirements
- Rendimiento: el matching es sobre las palabras de UN episodio (orden de miles de tokens); el barrido
  difuso debe quedar bajo ~50 ms en el fixture. Acotar el fallback difuso para no ser O(n²) patológico
  (limitar tamaños de ventana probados a un rango pequeño alrededor de `len(q)`).
- Sin red, sin disco, sin estado en el applier (salvo el `words_provider` inyectado).
- Compatibilidad: las llamadas existentes a `match_text_span(words, keep_text)` (sin anchor) siguen válidas.

## Done Conditions
- [ ] `match_text_span` acepta `anchor_time` opcional y resuelve: match exacto, match difuso (1–2 palabras
      distintas en puntas), y elección por proximidad ante frase repetida. Tests unitarios cubren los tres.
- [ ] `_trim_to_text` busca en todo el episodio con `anchor_time=c.start_time` y resuelve fragmentos que
      cruzan el borde del clip. Test unitario lo prueba.
- [ ] `_build_user_message` incluye el transcript del clip en foco; un test con LLM fake/inspección del
      prompt verifica que el texto del clip en foco está presente y que `focus_id=None` no lo incluye.
- [ ] El system prompt prohíbe explícitamente "solo conozco los rangos / no puedo cortar en el medio".
- [ ] `tests/test_brief_realworld.py` + `fixtures/brief_transcript.json` pasan los 5 casos del goal.
- [ ] Suite completa verde; tests de brief existentes sin regresión.
- [ ] security-reviewer: 0 CRITICAL / 0 HIGH sobre el diff.
