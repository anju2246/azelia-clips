"""Importador de señales niche de PodFinder (resultados ya computados).

Lee los JSON de resultados de PodFinder (`ic_signals_ready.json` y su hermano
`ic_baselines_ready.json`) y los inserta tal cual en las tablas locales
`niche_signals` / `niche_baselines`. NO recomputa ni transforma métricas: solo
ingiere los resultados. Determinista y sin red.

Esto es la capa NICHE de la inteligencia de curación: qué patrones (hooks,
emociones, duraciones, temas, horarios) rinden por nicho. La capa CREATOR SELF
(desempeño propio) vive en `creator_signals`.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

# Identificador SQL seguro. Las columnas vienen SOLO de las constantes de abajo,
# pero validamos defensivamente para que ningún cambio futuro abra inyección por
# nombre de columna (las queries se construyen con f-string sobre estos nombres).
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_cols(cols: list) -> list:
    bad = [c for c in cols if not _SAFE_IDENT.match(c)]
    if bad:
        raise ValueError(f"Unsafe column identifier(s): {bad}")
    return cols

# Columnas de niche_signals que se mapean 1:1 desde el JSON (excepto pattern→pattern_json).
_SIGNAL_FIELDS = (
    "signal_type", "region", "language", "category", "episode_format", "period",
    "duration_bucket", "metric_type", "metric_value", "performance_premium",
    "adoption_rate", "saturation", "trend_direction", "trend_velocity",
    "sample_size", "confidence", "source_type",
)
_BASELINE_FIELDS = (
    "region", "language", "category", "platform", "metric_type",
    "p25", "p50", "p75", "p90", "sample_size",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _baselines_path(signals_path: Path) -> Path:
    """Deriva la ruta de baselines hermana reemplazando 'signals'→'baselines'.

    `ic_signals_ready.json` → `ic_baselines_ready.json`
    `ic_signals_slice.json` → `ic_baselines_slice.json`
    """
    return signals_path.with_name(signals_path.name.replace("signals", "baselines"))


def _insert_signal(conn: sqlite3.Connection, rec: dict, now: str) -> bool:
    """Upsert idempotente de una señal. Retorna False si el registro es inválido."""
    if not isinstance(rec, dict) or not rec.get("signal_type"):
        return False
    values = [rec.get(f) for f in _SIGNAL_FIELDS]
    pattern = rec.get("pattern")
    pattern_json = json.dumps(pattern, ensure_ascii=False, sort_keys=True) if pattern else None
    cols = _safe_cols(list(_SIGNAL_FIELDS) + ["pattern_json", "imported_at"])
    placeholders = ",".join(["?"] * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO niche_signals ({','.join(cols)}) VALUES ({placeholders})",
        values + [pattern_json, now],
    )
    return True


def _insert_baseline(conn: sqlite3.Connection, rec: dict, now: str) -> bool:
    if not isinstance(rec, dict) or not rec.get("metric_type"):
        return False
    values = [rec.get(f) for f in _BASELINE_FIELDS]
    cols = _safe_cols(list(_BASELINE_FIELDS) + ["imported_at"])
    placeholders = ",".join(["?"] * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO niche_baselines ({','.join(cols)}) VALUES ({placeholders})",
        values + [now],
    )
    return True


def import_niche_signals(
    conn: sqlite3.Connection, path: Union[str, Path]
) -> dict:
    """Importa señales niche desde `path` (y baselines hermanas si existen).

    Returns: {signals_imported, baselines_imported, skipped}.
    Raises: FileNotFoundError si el JSON de señales no existe;
            ValueError si el JSON es inválido.
    """
    signals_path = Path(path)
    if not signals_path.exists():
        raise FileNotFoundError(f"Signals JSON not found: {signals_path}")

    try:
        records = json.loads(signals_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse signals JSON: {e}") from e
    if not isinstance(records, list):
        raise ValueError("Signals JSON must be a list of records")

    now = _now()
    signals_imported = 0
    skipped = 0
    for rec in records:
        try:
            if _insert_signal(conn, rec, now):
                signals_imported += 1
            else:
                skipped += 1
        except Exception as e:  # registro raro: saltar, no abortar
            logger.warning("niche signal skipped: %s", e)
            skipped += 1

    baselines_imported = 0
    bpath = _baselines_path(signals_path)
    if bpath.exists():
        try:
            brecords = json.loads(bpath.read_text(encoding="utf-8"))
            if isinstance(brecords, list):
                for rec in brecords:
                    try:
                        if _insert_baseline(conn, rec, now):
                            baselines_imported += 1
                        else:
                            skipped += 1
                    except Exception as e:
                        logger.warning("niche baseline skipped: %s", e)
                        skipped += 1
        except json.JSONDecodeError as e:
            logger.warning("baselines JSON invalid, skipping: %s", e)

    conn.commit()
    return {
        "signals_imported": signals_imported,
        "baselines_imported": baselines_imported,
        "skipped": skipped,
    }
