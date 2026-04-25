"""Public taxonomy endpoints.

Serves the canonical lists of podcast niches, languages, and countries for
the onboarding selectors. Unauthenticated — these are catalogue data, not
user-specific. Kept as a single source of truth so the frontend never drifts
from the backend's normalization rules.
"""

from fastapi import APIRouter

from packages.core.taxonomy import CONTENT_NICHES, LANGUAGES, COUNTRIES

router = APIRouter()


@router.get("/taxonomy/niches")
def list_niches():
    return {"items": CONTENT_NICHES}


@router.get("/taxonomy/languages")
def list_languages():
    return {"items": LANGUAGES}


@router.get("/taxonomy/countries")
def list_countries():
    return {"items": COUNTRIES}


@router.get("/taxonomy")
def list_all():
    """Convenience: pull all three lists in one round-trip for onboarding."""
    return {
        "niches": CONTENT_NICHES,
        "languages": LANGUAGES,
        "countries": COUNTRIES,
    }
