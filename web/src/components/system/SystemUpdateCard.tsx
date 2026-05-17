import { useEffect, useRef, useState } from 'react';

/**
 * Self-update card for Settings → Workspace.
 *
 * - GET /api/system/version             — current vs latest on GitHub
 * - POST /api/system/update              — kick off update in background
 * - GET /api/system/update/status        — poll log + phase
 *
 * On a successful update, the server exits with code 42 and the azelia
 * wrapper script (installed by install.sh) re-launches. The user just sees
 * a "Restarting…" message; the page reconnects when the new server is up.
 */

type VersionInfo = {
    current: string;
    current_commit: string | null;
    latest: string | null;
    latest_info: {
        tag_name?: string;
        name?: string;
        body?: string;
        html_url?: string;
        published_at?: string;
    } | null;
    behind: boolean;
    channel: string;
    update_available: boolean;
    update_in_progress: boolean;
};

type UpdateStatus = {
    status: 'idle' | 'starting' | 'fetching' | 'installing' | 'building' | 'restarting' | 'done' | 'error';
    log: string[];
    running: boolean;
};

const PHASE_LABEL: Record<UpdateStatus['status'], string> = {
    idle: 'Idle',
    starting: 'Starting…',
    fetching: 'Downloading latest code…',
    installing: 'Installing dependencies…',
    building: 'Building dashboard…',
    restarting: 'Restarting server…',
    done: 'Update complete ✓',
    error: 'Something went wrong',
};

export function SystemUpdateCard() {
    const [version, setVersion] = useState<VersionInfo | null>(null);
    const [status, setStatus] = useState<UpdateStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [confirming, setConfirming] = useState(false);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const fetchVersion = async () => {
        try {
            const r = await fetch('/api/system/version');
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = (await r.json()) as VersionInfo;
            setVersion(data);
            setError(null);
            if (data.update_in_progress && !pollRef.current) startPolling();
        } catch (e) {
            setError(`Could not check for updates: ${(e as Error).message}`);
        }
    };

    const fetchStatus = async () => {
        try {
            const r = await fetch('/api/system/update/status');
            if (!r.ok) return;
            const data = (await r.json()) as UpdateStatus;
            setStatus(data);
            if (data.status === 'done') {
                stopPolling();
                // Wait a moment for restart, then re-fetch version
                setTimeout(fetchVersion, 4000);
            }
            if (data.status === 'error') {
                stopPolling();
            }
        } catch {
            // server probably restarting — keep polling
        }
    };

    const startPolling = () => {
        if (pollRef.current) return;
        pollRef.current = setInterval(fetchStatus, 1500);
        fetchStatus();
    };

    const stopPolling = () => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    };

    const triggerUpdate = async () => {
        setLoading(true);
        setError(null);
        try {
            const r = await fetch('/api/system/update', { method: 'POST' });
            if (!r.ok) {
                const body = await r.json().catch(() => ({}));
                throw new Error(body.detail || `HTTP ${r.status}`);
            }
            startPolling();
        } catch (e) {
            setError(`Update failed to start: ${(e as Error).message}`);
        } finally {
            setLoading(false);
            setConfirming(false);
        }
    };

    useEffect(() => {
        fetchVersion();
        return stopPolling;
    }, []);

    const phase = status?.status ?? (version?.update_in_progress ? 'starting' : 'idle');
    const isRunning = status?.running || ['starting', 'fetching', 'installing', 'building', 'restarting'].includes(phase);

    return (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-zinc-100">Azelia Clips updates</h3>
                    <p className="mt-1 text-xs text-zinc-400">
                        Version{' '}
                        <span className="font-mono text-zinc-200">v{version?.current ?? '…'}</span>
                        {version?.current_commit && (
                            <span className="text-zinc-500"> · {version.current_commit}</span>
                        )}
                    </p>
                </div>
                <button
                    onClick={fetchVersion}
                    disabled={isRunning}
                    className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-50"
                >
                    Check
                </button>
            </div>

            {error && (
                <div className="mt-3 rounded border border-red-900 bg-red-950/40 p-2 text-xs text-red-300">
                    {error}
                </div>
            )}

            {version && !isRunning && !version.update_available && (
                <div className="mt-3 text-xs text-zinc-500">You're on the latest version.</div>
            )}

            {version?.update_available && !isRunning && !confirming && (
                <div className="mt-4 rounded border border-emerald-900/60 bg-emerald-950/30 p-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="text-xs text-emerald-200">
                            <span className="font-semibold">v{version.latest}</span> is available
                            {version.latest_info?.published_at && (
                                <span className="text-emerald-400/70">
                                    {' · '}
                                    {new Date(version.latest_info.published_at).toLocaleDateString()}
                                </span>
                            )}
                        </div>
                        <button
                            onClick={() => setConfirming(true)}
                            className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500"
                        >
                            Update now
                        </button>
                    </div>
                    {version.latest_info?.body && (
                        <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-xs text-emerald-300/80">
                            {version.latest_info.body.slice(0, 600)}
                        </pre>
                    )}
                    {version.latest_info?.html_url && (
                        <a
                            href={version.latest_info.html_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-2 inline-block text-xs text-emerald-400 underline"
                        >
                            View release on GitHub →
                        </a>
                    )}
                </div>
            )}

            {confirming && (
                <div className="mt-4 rounded border border-amber-900/60 bg-amber-950/30 p-3 text-xs text-amber-200">
                    <p className="font-semibold">Updating will restart the server.</p>
                    <p className="mt-1 text-amber-300/80">
                        Active jobs will be paused. Your clips, transcripts and settings stay safe
                        (they live outside the install folder).
                    </p>
                    <div className="mt-3 flex gap-2">
                        <button
                            onClick={triggerUpdate}
                            disabled={loading}
                            className="rounded bg-emerald-600 px-3 py-1 font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                        >
                            {loading ? 'Starting…' : 'Yes, update now'}
                        </button>
                        <button
                            onClick={() => setConfirming(false)}
                            className="rounded border border-zinc-700 px-3 py-1 text-zinc-300 hover:bg-zinc-800"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            )}

            {isRunning && (
                <div className="mt-4 rounded border border-blue-900/60 bg-blue-950/30 p-3">
                    <div className="flex items-center gap-2 text-xs text-blue-200">
                        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-400" />
                        {PHASE_LABEL[phase as UpdateStatus['status']]}
                    </div>
                    {status?.log && status.log.length > 0 && (
                        <pre className="mt-2 max-h-40 overflow-auto rounded bg-black/40 p-2 font-mono text-[10px] text-blue-300/80">
                            {status.log.slice(-20).join('\n')}
                        </pre>
                    )}
                </div>
            )}

            {phase === 'done' && (
                <div className="mt-4 rounded border border-emerald-900/60 bg-emerald-950/30 p-3 text-xs text-emerald-200">
                    ✓ Update complete. The server is restarting; this page will reconnect in a few
                    seconds.
                </div>
            )}
        </div>
    );
}

export default SystemUpdateCard;
