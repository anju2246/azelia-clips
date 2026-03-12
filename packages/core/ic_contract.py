# IC Signal Contract — Shared Spec
# Source of truth for schema, naming, and calculations between
# PodFinder (podintel_public) and User Telemetry (user_telemetry).
#
# Full spec: See ic_signal_contract.md in project docs
# Both streams MUST produce compatible data for ic_signals.

# ─── Canonical Taxonomies ────────────────────────────────────────────────────

VALID_CATEGORIES = [
    "business",       # Emprendimiento, startups, marketing, finanzas
    "education",      # Aprendizaje, ciencia, divulgación, tutoriales
    "comedy",         # Stand-up, comedia conversacional, humor
    "entertainment",  # Cultura pop, gaming, lifestyle, viajes
    "politics",       # Actualidad, noticias, geopolítica
    "health",         # Salud mental, fitness, bienestar, nutrición
    "tech",           # Tecnología, AI, software, crypto
    "relationships",  # Relaciones, psicología, sexualidad, familia
    "true_crime",     # Crimen real, misterios, investigación
    "sports",         # Deportes, atletas, competencia
    "spirituality",   # Religión, meditación, propósito, filosofía
]

VALID_HOOK_TYPES = [
    "question",
    "surprising_fact",
    "controversial_statement",
    "storytelling",
    "negative_frame",
    "tutorial",
    "weak",
]

VALID_EMOTIONAL_CHARGES = [
    "inspirational",
    "urgent",
    "comedic",
    "outrage",
    "educational",
    "empathetic",
]

VALID_EPISODE_FORMATS = [
    "interview",   # 2 personas (host + invitado)
    "solo",        # Monólogo o narración
    "co_host",     # 2+ hosts fijos
    "panel",       # 3+ participantes
    "narrative",   # Producción editada, storytelling
    "hybrid",      # Mezcla de formatos
]

VALID_DURATION_BUCKETS = [
    "0-15",
    "15-30",
    "30-45",
    "45-60",
]

VALID_METRIC_TYPES = [
    "views",
    "engagement_rate",
    "growth_velocity",
    "retention",          # user_telemetry only
    "completion_rate",    # user_telemetry only
    "impression_ctr",    # user_telemetry only
]

VALID_SATURATION_LEVELS = [
    "emerging",
    "differentiating",
    "baseline",
    "oversaturated",
]


# ─── Formulas ────────────────────────────────────────────────────────────────

def compute_confidence(sample_size: int) -> float:
    """Confidence score based on sample size."""
    if sample_size < 20:
        return 0.2
    elif sample_size < 50:
        return 0.4
    elif sample_size < 100:
        return 0.6
    elif sample_size < 250:
        return 0.8
    else:
        return 0.95


def compute_saturation(adoption_rate: float, performance_premium: float) -> str:
    """Saturation level based on adoption and premium."""
    if adoption_rate < 0.3 and performance_premium > 1.5:
        return "emerging"
    elif adoption_rate >= 0.3 and performance_premium > 1.2:
        return "differentiating"
    elif adoption_rate >= 0.5 and 0.8 <= performance_premium <= 1.2:
        return "baseline"
    elif adoption_rate >= 0.5 and performance_premium < 0.8:
        return "oversaturated"
    return "emerging"


def compute_bayesian_weight(user_sample_size: int) -> tuple:
    """Cascading Bayesian weight between user and podintel data."""
    weight_user = min(1.0, user_sample_size / 100)
    weight_podintel = 1.0 - weight_user
    return weight_user, weight_podintel


# Minimum sample size to write to ic_signals
MIN_SAMPLE_SIZE_FOR_SIGNAL = 5
