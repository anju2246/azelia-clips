"""Canonical taxonomies for content niche, language, and country.

Source of truth for:
  - Onboarding dropdowns / searchable selectors (frontend fetches via /api/taxonomy)
  - Normalization when writing creator signals (`_normalize_niche` keeps profile
    values and `ic_signals.category` values in sync so the Ranker's niche-wide
    query actually matches rows)
  - PostgREST filter validation — any niche/language/country coming from a
    user profile is validated against these sets before being interpolated
    into a Supabase REST query
"""

from __future__ import annotations

# ─── Content niches ──────────────────────────────────────────────────────────
# Apple Podcasts top-level categories (2024-2026). `id` is the stable,
# lowercase-underscored value stored in profiles.content_niche and
# ic_signals.category. `label` is what the user sees in the picker.
CONTENT_NICHES: list[dict[str, str]] = [
    {"id": "arts", "label": "Arts"},
    {"id": "business", "label": "Business"},
    {"id": "careers", "label": "Careers"},
    {"id": "comedy", "label": "Comedy"},
    {"id": "education", "label": "Education"},
    {"id": "entrepreneurship", "label": "Entrepreneurship"},
    {"id": "fiction", "label": "Fiction"},
    {"id": "government", "label": "Government"},
    {"id": "health_fitness", "label": "Health & Fitness"},
    {"id": "history", "label": "History"},
    {"id": "kids_family", "label": "Kids & Family"},
    {"id": "leisure", "label": "Leisure"},
    {"id": "music", "label": "Music"},
    {"id": "news", "label": "News"},
    {"id": "religion_spirituality", "label": "Religion & Spirituality"},
    {"id": "science", "label": "Science"},
    {"id": "self_improvement", "label": "Self Improvement"},
    {"id": "society_culture", "label": "Society & Culture"},
    {"id": "sports", "label": "Sports"},
    {"id": "technology", "label": "Technology"},
    {"id": "true_crime", "label": "True Crime"},
    {"id": "tv_film", "label": "TV & Film"},
]

_NICHE_IDS: frozenset[str] = frozenset(n["id"] for n in CONTENT_NICHES)
_NICHE_LABEL_TO_ID: dict[str, str] = {n["label"].lower(): n["id"] for n in CONTENT_NICHES}

# Legacy aliases — maps values used in older onboarding forms (pre-taxonomy)
# to the canonical id. Prevents profiles with legacy free-form values from
# becoming invisible to the Ranker's niche-wide query.
_NICHE_LEGACY_ALIASES: dict[str, str] = {
    "business & entrepreneurship": "entrepreneurship",
    "business and entrepreneurship": "entrepreneurship",
    "business_finance": "business",
    "business & finance": "business",
    "career": "careers",
    "education & science": "education",
    "education and science": "education",
    "gaming": "leisure",
    "lifestyle": "leisure",
    "food": "leisure",
    "hobbies": "leisure",
    "self-help": "self_improvement",
    "self_help": "self_improvement",
    "self-development": "self_improvement",
    "self_development": "self_improvement",
    "personal_development": "self_improvement",
    "personal development": "self_improvement",
    "personal_growth": "self_improvement",
    "personal growth": "self_improvement",
    "philosophy": "society_culture",
    "politics": "news",
    "tech": "technology",
}


def normalize_niche(value: str | None) -> str:
    """Return the canonical niche id for a user-supplied value.

    Accepts the id directly (`business_finance`), a label (`Business & Finance`),
    or a legacy free-form value. Returns empty string if the value is unknown —
    callers use that to fall back to generic heuristics rather than injecting an
    invalid category filter into PostgREST.
    """
    if not value:
        return ""
    candidate = value.strip()
    if candidate in _NICHE_IDS:
        return candidate

    # Try label lookup (case-insensitive).
    lower = candidate.lower()
    by_label = _NICHE_LABEL_TO_ID.get(lower)
    if by_label:
        return by_label

    # Legacy alias lookup.
    alias = _NICHE_LEGACY_ALIASES.get(lower)
    if alias:
        return alias

    # Legacy free-form: normalize to lower+underscore and accept if it matches.
    normalized = (
        lower
        .replace(" & ", "_")
        .replace(" and ", "_")
        .replace(" ", "_")
    )
    if normalized in _NICHE_IDS:
        return normalized

    # Unknown value — return empty so callers know NOT to filter by it.
    return ""


def is_valid_niche(value: str | None) -> bool:
    return bool(value) and value in _NICHE_IDS


# Cold-start fallback chain for the IC Cascade. When a user's niche has zero
# `ic_signals` rows yet, the Ranker borrows from the parent anchor so the
# day-one experience isn't just generic heuristics. Once the niche has its
# own data, the primary query starts returning rows and the fallback never
# fires.
#
# Anchors (no fallback — they're the densest pools and accept inflows):
#   business, education, society_culture, leisure
# Everything else funnels into one of those four. Don't add fallbacks that
# go in reverse (`business → careers` would distort signal).
_NICHE_PARENT_FALLBACK: dict[str, str] = {
    # → business
    "careers": "business",
    "entrepreneurship": "business",
    # → education
    "self_improvement": "education",
    "history": "education",
    "science": "education",
    "technology": "education",
    # → society_culture
    "arts": "society_culture",
    "fiction": "society_culture",
    "government": "society_culture",
    "news": "society_culture",
    "religion_spirituality": "society_culture",
    "health_fitness": "society_culture",
    # → leisure
    "comedy": "leisure",
    "kids_family": "leisure",
    "music": "leisure",
    "sports": "leisure",
    "true_crime": "leisure",
    "tv_film": "leisure",
}


def fallback_niche(value: str | None) -> str | None:
    """Return the parent niche to consult if `value` has no IC signals yet.

    Returns None when no fallback is registered or the input is invalid.
    Callers should treat fallback hints as lower-confidence than primary ones.
    """
    if not value or value not in _NICHE_IDS:
        return None
    return _NICHE_PARENT_FALLBACK.get(value)


# ─── Languages (ISO 639-1, most common ~60) ──────────────────────────────────
LANGUAGES: list[dict[str, str]] = [
    {"id": "ar", "label": "Arabic"},
    {"id": "bg", "label": "Bulgarian"},
    {"id": "bn", "label": "Bengali"},
    {"id": "ca", "label": "Catalan"},
    {"id": "cs", "label": "Czech"},
    {"id": "da", "label": "Danish"},
    {"id": "de", "label": "German"},
    {"id": "el", "label": "Greek"},
    {"id": "en", "label": "English"},
    {"id": "es", "label": "Spanish"},
    {"id": "et", "label": "Estonian"},
    {"id": "eu", "label": "Basque"},
    {"id": "fa", "label": "Persian"},
    {"id": "fi", "label": "Finnish"},
    {"id": "fr", "label": "French"},
    {"id": "gl", "label": "Galician"},
    {"id": "gu", "label": "Gujarati"},
    {"id": "he", "label": "Hebrew"},
    {"id": "hi", "label": "Hindi"},
    {"id": "hr", "label": "Croatian"},
    {"id": "hu", "label": "Hungarian"},
    {"id": "id", "label": "Indonesian"},
    {"id": "is", "label": "Icelandic"},
    {"id": "it", "label": "Italian"},
    {"id": "ja", "label": "Japanese"},
    {"id": "ka", "label": "Georgian"},
    {"id": "kk", "label": "Kazakh"},
    {"id": "km", "label": "Khmer"},
    {"id": "kn", "label": "Kannada"},
    {"id": "ko", "label": "Korean"},
    {"id": "lt", "label": "Lithuanian"},
    {"id": "lv", "label": "Latvian"},
    {"id": "ml", "label": "Malayalam"},
    {"id": "mr", "label": "Marathi"},
    {"id": "ms", "label": "Malay"},
    {"id": "my", "label": "Burmese"},
    {"id": "nb", "label": "Norwegian Bokmål"},
    {"id": "ne", "label": "Nepali"},
    {"id": "nl", "label": "Dutch"},
    {"id": "pa", "label": "Punjabi"},
    {"id": "pl", "label": "Polish"},
    {"id": "pt", "label": "Portuguese"},
    {"id": "ro", "label": "Romanian"},
    {"id": "ru", "label": "Russian"},
    {"id": "si", "label": "Sinhala"},
    {"id": "sk", "label": "Slovak"},
    {"id": "sl", "label": "Slovenian"},
    {"id": "sq", "label": "Albanian"},
    {"id": "sr", "label": "Serbian"},
    {"id": "sv", "label": "Swedish"},
    {"id": "sw", "label": "Swahili"},
    {"id": "ta", "label": "Tamil"},
    {"id": "te", "label": "Telugu"},
    {"id": "th", "label": "Thai"},
    {"id": "tl", "label": "Tagalog"},
    {"id": "tr", "label": "Turkish"},
    {"id": "uk", "label": "Ukrainian"},
    {"id": "ur", "label": "Urdu"},
    {"id": "vi", "label": "Vietnamese"},
    {"id": "zh", "label": "Chinese"},
]

_LANGUAGE_IDS: frozenset[str] = frozenset(lang["id"] for lang in LANGUAGES)


def normalize_language(value: str | None) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    if v in _LANGUAGE_IDS:
        return v
    # Allow locale forms like "es-MX" → "es"
    head = v.split("-", 1)[0]
    if head in _LANGUAGE_IDS:
        return head
    return ""


def is_valid_language(value: str | None) -> bool:
    return bool(value) and value in _LANGUAGE_IDS


# Lookup: ISO code → human label used in prompts (e.g. "Respond in Spanish").
_LANGUAGE_ID_TO_LABEL: dict[str, str] = {lang["id"]: lang["label"] for lang in LANGUAGES}


def language_label(code: str | None, fallback: str = "English") -> str:
    """Return the human-readable label for an ISO-639-1 code.

    Used by the prompt layer to interpolate a natural-language instruction
    like `Respond in Spanish.` — Claude responds better to "Spanish" than to
    "es". Accepts locale forms ("es-MX") and unknown codes gracefully:
    unknown → fallback (default "English") so the pipeline never ships an
    empty or broken instruction to the LLM.
    """
    norm = normalize_language(code)
    if not norm:
        return fallback
    return _LANGUAGE_ID_TO_LABEL.get(norm, fallback)


# ─── Countries (ISO 3166-1 alpha-2, full list) ───────────────────────────────
# Stored as id (two-letter code) so profiles.region is always comparable.
COUNTRIES: list[dict[str, str]] = [
    {"id": "AF", "label": "Afghanistan"}, {"id": "AL", "label": "Albania"},
    {"id": "DZ", "label": "Algeria"}, {"id": "AD", "label": "Andorra"},
    {"id": "AO", "label": "Angola"}, {"id": "AG", "label": "Antigua and Barbuda"},
    {"id": "AR", "label": "Argentina"}, {"id": "AM", "label": "Armenia"},
    {"id": "AU", "label": "Australia"}, {"id": "AT", "label": "Austria"},
    {"id": "AZ", "label": "Azerbaijan"}, {"id": "BS", "label": "Bahamas"},
    {"id": "BH", "label": "Bahrain"}, {"id": "BD", "label": "Bangladesh"},
    {"id": "BB", "label": "Barbados"}, {"id": "BY", "label": "Belarus"},
    {"id": "BE", "label": "Belgium"}, {"id": "BZ", "label": "Belize"},
    {"id": "BJ", "label": "Benin"}, {"id": "BT", "label": "Bhutan"},
    {"id": "BO", "label": "Bolivia"}, {"id": "BA", "label": "Bosnia and Herzegovina"},
    {"id": "BW", "label": "Botswana"}, {"id": "BR", "label": "Brazil"},
    {"id": "BN", "label": "Brunei"}, {"id": "BG", "label": "Bulgaria"},
    {"id": "BF", "label": "Burkina Faso"}, {"id": "BI", "label": "Burundi"},
    {"id": "KH", "label": "Cambodia"}, {"id": "CM", "label": "Cameroon"},
    {"id": "CA", "label": "Canada"}, {"id": "CV", "label": "Cape Verde"},
    {"id": "CF", "label": "Central African Republic"}, {"id": "TD", "label": "Chad"},
    {"id": "CL", "label": "Chile"}, {"id": "CN", "label": "China"},
    {"id": "CO", "label": "Colombia"}, {"id": "KM", "label": "Comoros"},
    {"id": "CG", "label": "Congo"}, {"id": "CD", "label": "Congo (DRC)"},
    {"id": "CR", "label": "Costa Rica"}, {"id": "HR", "label": "Croatia"},
    {"id": "CU", "label": "Cuba"}, {"id": "CY", "label": "Cyprus"},
    {"id": "CZ", "label": "Czech Republic"}, {"id": "DK", "label": "Denmark"},
    {"id": "DJ", "label": "Djibouti"}, {"id": "DM", "label": "Dominica"},
    {"id": "DO", "label": "Dominican Republic"}, {"id": "EC", "label": "Ecuador"},
    {"id": "EG", "label": "Egypt"}, {"id": "SV", "label": "El Salvador"},
    {"id": "GQ", "label": "Equatorial Guinea"}, {"id": "ER", "label": "Eritrea"},
    {"id": "EE", "label": "Estonia"}, {"id": "SZ", "label": "Eswatini"},
    {"id": "ET", "label": "Ethiopia"}, {"id": "FJ", "label": "Fiji"},
    {"id": "FI", "label": "Finland"}, {"id": "FR", "label": "France"},
    {"id": "GA", "label": "Gabon"}, {"id": "GM", "label": "Gambia"},
    {"id": "GE", "label": "Georgia"}, {"id": "DE", "label": "Germany"},
    {"id": "GH", "label": "Ghana"}, {"id": "GR", "label": "Greece"},
    {"id": "GD", "label": "Grenada"}, {"id": "GT", "label": "Guatemala"},
    {"id": "GN", "label": "Guinea"}, {"id": "GW", "label": "Guinea-Bissau"},
    {"id": "GY", "label": "Guyana"}, {"id": "HT", "label": "Haiti"},
    {"id": "HN", "label": "Honduras"}, {"id": "HK", "label": "Hong Kong"},
    {"id": "HU", "label": "Hungary"}, {"id": "IS", "label": "Iceland"},
    {"id": "IN", "label": "India"}, {"id": "ID", "label": "Indonesia"},
    {"id": "IR", "label": "Iran"}, {"id": "IQ", "label": "Iraq"},
    {"id": "IE", "label": "Ireland"}, {"id": "IL", "label": "Israel"},
    {"id": "IT", "label": "Italy"}, {"id": "CI", "label": "Ivory Coast"},
    {"id": "JM", "label": "Jamaica"}, {"id": "JP", "label": "Japan"},
    {"id": "JO", "label": "Jordan"}, {"id": "KZ", "label": "Kazakhstan"},
    {"id": "KE", "label": "Kenya"}, {"id": "KI", "label": "Kiribati"},
    {"id": "KW", "label": "Kuwait"}, {"id": "KG", "label": "Kyrgyzstan"},
    {"id": "LA", "label": "Laos"}, {"id": "LV", "label": "Latvia"},
    {"id": "LB", "label": "Lebanon"}, {"id": "LS", "label": "Lesotho"},
    {"id": "LR", "label": "Liberia"}, {"id": "LY", "label": "Libya"},
    {"id": "LI", "label": "Liechtenstein"}, {"id": "LT", "label": "Lithuania"},
    {"id": "LU", "label": "Luxembourg"}, {"id": "MO", "label": "Macao"},
    {"id": "MG", "label": "Madagascar"}, {"id": "MW", "label": "Malawi"},
    {"id": "MY", "label": "Malaysia"}, {"id": "MV", "label": "Maldives"},
    {"id": "ML", "label": "Mali"}, {"id": "MT", "label": "Malta"},
    {"id": "MH", "label": "Marshall Islands"}, {"id": "MR", "label": "Mauritania"},
    {"id": "MU", "label": "Mauritius"}, {"id": "MX", "label": "Mexico"},
    {"id": "FM", "label": "Micronesia"}, {"id": "MD", "label": "Moldova"},
    {"id": "MC", "label": "Monaco"}, {"id": "MN", "label": "Mongolia"},
    {"id": "ME", "label": "Montenegro"}, {"id": "MA", "label": "Morocco"},
    {"id": "MZ", "label": "Mozambique"}, {"id": "MM", "label": "Myanmar"},
    {"id": "NA", "label": "Namibia"}, {"id": "NR", "label": "Nauru"},
    {"id": "NP", "label": "Nepal"}, {"id": "NL", "label": "Netherlands"},
    {"id": "NZ", "label": "New Zealand"}, {"id": "NI", "label": "Nicaragua"},
    {"id": "NE", "label": "Niger"}, {"id": "NG", "label": "Nigeria"},
    {"id": "KP", "label": "North Korea"}, {"id": "MK", "label": "North Macedonia"},
    {"id": "NO", "label": "Norway"}, {"id": "OM", "label": "Oman"},
    {"id": "PK", "label": "Pakistan"}, {"id": "PW", "label": "Palau"},
    {"id": "PS", "label": "Palestine"}, {"id": "PA", "label": "Panama"},
    {"id": "PG", "label": "Papua New Guinea"}, {"id": "PY", "label": "Paraguay"},
    {"id": "PE", "label": "Peru"}, {"id": "PH", "label": "Philippines"},
    {"id": "PL", "label": "Poland"}, {"id": "PT", "label": "Portugal"},
    {"id": "PR", "label": "Puerto Rico"}, {"id": "QA", "label": "Qatar"},
    {"id": "RO", "label": "Romania"}, {"id": "RU", "label": "Russia"},
    {"id": "RW", "label": "Rwanda"}, {"id": "KN", "label": "Saint Kitts and Nevis"},
    {"id": "LC", "label": "Saint Lucia"}, {"id": "VC", "label": "Saint Vincent"},
    {"id": "WS", "label": "Samoa"}, {"id": "SM", "label": "San Marino"},
    {"id": "ST", "label": "São Tomé and Príncipe"}, {"id": "SA", "label": "Saudi Arabia"},
    {"id": "SN", "label": "Senegal"}, {"id": "RS", "label": "Serbia"},
    {"id": "SC", "label": "Seychelles"}, {"id": "SL", "label": "Sierra Leone"},
    {"id": "SG", "label": "Singapore"}, {"id": "SK", "label": "Slovakia"},
    {"id": "SI", "label": "Slovenia"}, {"id": "SB", "label": "Solomon Islands"},
    {"id": "SO", "label": "Somalia"}, {"id": "ZA", "label": "South Africa"},
    {"id": "KR", "label": "South Korea"}, {"id": "SS", "label": "South Sudan"},
    {"id": "ES", "label": "Spain"}, {"id": "LK", "label": "Sri Lanka"},
    {"id": "SD", "label": "Sudan"}, {"id": "SR", "label": "Suriname"},
    {"id": "SE", "label": "Sweden"}, {"id": "CH", "label": "Switzerland"},
    {"id": "SY", "label": "Syria"}, {"id": "TW", "label": "Taiwan"},
    {"id": "TJ", "label": "Tajikistan"}, {"id": "TZ", "label": "Tanzania"},
    {"id": "TH", "label": "Thailand"}, {"id": "TL", "label": "Timor-Leste"},
    {"id": "TG", "label": "Togo"}, {"id": "TO", "label": "Tonga"},
    {"id": "TT", "label": "Trinidad and Tobago"}, {"id": "TN", "label": "Tunisia"},
    {"id": "TR", "label": "Turkey"}, {"id": "TM", "label": "Turkmenistan"},
    {"id": "TV", "label": "Tuvalu"}, {"id": "UG", "label": "Uganda"},
    {"id": "UA", "label": "Ukraine"}, {"id": "AE", "label": "United Arab Emirates"},
    {"id": "GB", "label": "United Kingdom"}, {"id": "US", "label": "United States"},
    {"id": "UY", "label": "Uruguay"}, {"id": "UZ", "label": "Uzbekistan"},
    {"id": "VU", "label": "Vanuatu"}, {"id": "VA", "label": "Vatican City"},
    {"id": "VE", "label": "Venezuela"}, {"id": "VN", "label": "Vietnam"},
    {"id": "YE", "label": "Yemen"}, {"id": "ZM", "label": "Zambia"},
    {"id": "ZW", "label": "Zimbabwe"},
]

_COUNTRY_IDS: frozenset[str] = frozenset(c["id"] for c in COUNTRIES)


def normalize_country(value: str | None) -> str:
    """Accept ISO alpha-2 code, label, or legacy free-form. Return id or ''."""
    if not value:
        return ""
    v = value.strip()
    if v.upper() in _COUNTRY_IDS:
        return v.upper()
    for c in COUNTRIES:
        if c["label"].lower() == v.lower():
            return c["id"]
    return ""


def is_valid_country(value: str | None) -> bool:
    return bool(value) and value in _COUNTRY_IDS
