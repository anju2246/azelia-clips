import React, { useEffect, useState } from 'react';
import { AlertTriangle, ExternalLink } from 'lucide-react';
import { supabase } from '../../lib/supabase';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    try {
        const { data } = await supabase.auth.getSession();
        if (data?.session?.access_token) {
            headers.set('Authorization', `Bearer ${data.session.access_token}`);
        }
    } catch (e) { /* continue */ }
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

interface ProviderStatus {
    ok: boolean | null;
    reason: string | null;
    model_used: string | null;
}

interface CreditsResponse {
    any_provider_ok: boolean;
    providers: Record<string, ProviderStatus>;
}

const REASON_COPY: Record<string, { title: string; action: string; actionUrl: string; severity: 'error' | 'warn' }> = {
    credit_balance_too_low: {
        title: 'API credit balance is empty',
        action: 'Add credit',
        actionUrl: 'https://console.anthropic.com/settings/billing',
        severity: 'error',
    },
    billing_not_active: {
        title: 'Billing is not active on your API account',
        action: 'Fix billing',
        actionUrl: 'https://console.anthropic.com/settings/billing',
        severity: 'error',
    },
    invalid_key: {
        title: 'API key is invalid',
        action: 'Update key',
        actionUrl: '/dashboard/settings',
        severity: 'error',
    },
    rate_limited: {
        title: 'Currently rate-limited — retry in a minute',
        action: 'Dismiss',
        actionUrl: '#',
        severity: 'warn',
    },
};

/**
 * Shows only when at least one configured provider has a problem that
 * will break the pipeline. Silent when everything is fine.
 */
export const CreditsStatusBanner: React.FC = () => {
    const [status, setStatus] = useState<CreditsResponse | null>(null);

    useEffect(() => {
        let cancelled = false;
        fetchWithAuth('/credits/status')
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (!cancelled && d) setStatus(d); })
            .catch(() => {});
        return () => { cancelled = true; };
    }, []);

    if (!status) return null;

    const problems: Array<{ provider: string; s: ProviderStatus }> = Object.entries(status.providers)
        .filter(([, s]) => s.ok === false)
        .map(([provider, s]) => ({ provider, s }));

    if (problems.length === 0) return null;

    // If one provider is broken but another works, it's a warn. If ALL are broken, it's an error.
    const allBroken = !status.any_provider_ok;

    return (
        <div className={`rounded-2xl border p-5 space-y-3 ${allBroken ? 'border-red-500/50 bg-red-500/10' : 'border-amber-500/50 bg-amber-500/10'}`}>
            {problems.map(({ provider, s }) => {
                const copy = s.reason ? REASON_COPY[s.reason] : null;
                const severityColor = copy?.severity === 'error' ? 'text-red-400' : 'text-amber-400';
                return (
                    <div key={provider} className="flex items-start gap-3">
                        <AlertTriangle className={`w-5 h-5 ${severityColor} mt-0.5 shrink-0`} />
                        <div className="flex-1">
                            <p className="text-white font-medium text-sm capitalize">
                                {provider} — {copy?.title ?? `Error: ${s.reason ?? 'unknown'}`}
                            </p>
                            <p className="text-xs text-zinc-400 mt-1">
                                {allBroken
                                    ? 'The pipeline cannot run until this is resolved.'
                                    : `Azelia will fall back to another provider, but ${provider} features won't work.`}
                            </p>
                            {copy && (
                                <a
                                    href={copy.actionUrl}
                                    target={copy.actionUrl.startsWith('http') ? '_blank' : undefined}
                                    rel="noopener"
                                    className="inline-flex items-center gap-1.5 mt-2 text-xs font-medium text-white hover:text-brand-400 transition-colors"
                                >
                                    {copy.action} <ExternalLink className="w-3 h-3" />
                                </a>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};
