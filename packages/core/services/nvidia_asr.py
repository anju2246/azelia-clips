"""Transcripción local de respaldo para los Shorts del propio canal.

YouTube captions siguen siendo el primer intento. Si no hay subtítulos, este
módulo corre NVIDIA Parakeet TDT 0.6B v3 (`nvidia/parakeet-tdt-0.6b-v3`) en
Linux mediante el runtime ONNX `nemo-parakeet-tdt-0.6b-v3` (int8).

Ese es el modelo de NVIDIA que llega a transcribir aquí: 25 idiomas europeos,
español incluido, ~640 MB, y corre en CPU sin Apple Silicon. Canary 1B v2
también es de NVIDIA y cubre español, pero la ficha pide unos 6 GB solo para
cargar el modelo; en una máquina Linux sin GPU no es el que corre.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Identidad del checkpoint de NVIDIA. El nombre ONNX es el export que onnx-asr
# carga en Linux (CPU). No es un port MLX.
NVIDIA_MODEL_ID = "nvidia/parakeet-tdt-0.6b-v3"
ONNX_MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
# int8 es la cuantización que cargó y transcribió en CPU Linux sin GPU NVIDIA.
DEFAULT_QUANTIZATION = "int8"

_lock = threading.Lock()
_model = None


def transcribe_wav(path: str) -> Optional[str]:
    """Transcribe un WAV PCM. Devuelve el texto o None si el modelo no dijo nada."""
    text = _get_model().recognize(path)
    if not isinstance(text, str):
        text = getattr(text, "text", "") or ""
    text = text.strip()
    return text or None


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            import onnx_asr
        except ImportError as e:
            raise RuntimeError(
                "Falta el runtime de NVIDIA Parakeet. Instala con: "
                "pip install 'azelia-clips[asr-nvidia]'"
            ) from e
        logger.info(
            "Cargando %s vía %s (%s) para transcribir en Linux",
            NVIDIA_MODEL_ID,
            ONNX_MODEL_NAME,
            DEFAULT_QUANTIZATION,
        )
        _model = onnx_asr.load_model(
            ONNX_MODEL_NAME,
            providers=["CPUExecutionProvider"],
            quantization=DEFAULT_QUANTIZATION,
        )
        return _model
