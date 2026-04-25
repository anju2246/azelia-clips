// Taxonomy client — fetches the canonical niche / language / country lists
// from the backend so every form stays in sync with server-side validation.

export interface TaxonomyItem { id: string; label: string }

export interface TaxonomyBundle {
    niches: TaxonomyItem[];
    languages: TaxonomyItem[];
    countries: TaxonomyItem[];
}

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

let _cached: TaxonomyBundle | null = null;
let _inflight: Promise<TaxonomyBundle> | null = null;

export async function fetchTaxonomy(): Promise<TaxonomyBundle> {
    if (_cached) return _cached;
    if (_inflight) return _inflight;
    _inflight = (async () => {
        try {
            const res = await fetch(`${API_BASE}/taxonomy`);
            if (!res.ok) throw new Error(`taxonomy fetch failed: ${res.status}`);
            const data = await res.json();
            const bundle: TaxonomyBundle = {
                niches: data.niches || [],
                languages: data.languages || [],
                countries: data.countries || [],
            };
            _cached = bundle;
            return bundle;
        } finally {
            _inflight = null;
        }
    })();
    return _inflight;
}

export function resetTaxonomyCache() {
    _cached = null;
}
