import React, { useState, useEffect } from 'react';
import { User, Mail, Camera, Shield, HardDrive, Film, BarChart3, Calendar, ExternalLink, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { supabase } from '../../lib/supabase';

export const UserProfile: React.FC = () => {
    const [user, setUser] = useState<any>(null);
    const [displayName, setDisplayName] = useState('');
    const [isEditing, setIsEditing] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [ytStatus, setYtStatus] = useState<{ connected: boolean; channel_name: string | null }>({ connected: false, channel_name: null });

    useEffect(() => {
        loadUser();
    }, []);

    const loadUser = async () => {
        try {
            const { data: { user } } = await supabase.auth.getUser();
            if (user) {
                setUser(user);
                setDisplayName(
                    user.user_metadata?.full_name ||
                    user.user_metadata?.name ||
                    user.email?.split('@')[0] ||
                    'Creator'
                );
            }
        } catch (e) {
            console.error('Failed to load user', e);
        } finally {
            setIsLoading(false);
        }

        // Check YouTube status
        try {
            const { data } = await supabase.auth.getSession();
            const token = data?.session?.access_token;
            if (token) {
                const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
                const res = await fetch(`${API_BASE}/analytics/youtube/status`, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                if (res.ok) {
                    const status = await res.json();
                    setYtStatus({ connected: status.connected, channel_name: status.channel_name });
                }
            }
        } catch (e) { /* silently fail */ }
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            const { error } = await supabase.auth.updateUser({
                data: { full_name: displayName }
            });
            if (error) throw error;
            setIsEditing(false);
            toast.success('Profile updated');
        } catch (err: any) {
            toast.error(err.message || 'Failed to update profile');
        } finally {
            setIsSaving(false);
        }
    };

    const email = user?.email || '';
    const avatarUrl = user?.user_metadata?.avatar_url;
    const provider = user?.app_metadata?.provider || 'email';
    const createdAt = user?.created_at;

    // Determine auth providers linked
    const identities = user?.identities || [];
    const providers = identities.map((i: any) => i.provider).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);

    if (isLoading) {
        return (
            <div className="flex justify-center items-center py-20">
                <Loader2 className="w-8 h-8 text-brand-500 animate-spin" />
            </div>
        );
    }

    return (
        <div className="max-w-3xl mx-auto pb-12">
            <div className="mb-10">
                <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
                    Your Profile
                </h2>
                <p className="text-zinc-500 mt-2">Manage your account and view your pipeline activity.</p>
            </div>

            {/* Avatar + Name Card */}
            <section className="bg-zinc-900/40 border border-white/5 rounded-2xl p-8 mb-6 flex flex-col sm:flex-row items-center gap-6">
                <div className="relative group">
                    {avatarUrl ? (
                        <img
                            src={avatarUrl}
                            alt={displayName}
                            className="w-24 h-24 rounded-full object-cover shadow-xl shadow-brand-500/20 border-2 border-zinc-800"
                        />
                    ) : (
                        <div className="w-24 h-24 rounded-full bg-gradient-to-br from-brand-500 to-emerald-600 flex items-center justify-center text-white text-3xl font-bold shadow-xl shadow-brand-500/20">
                            {displayName.charAt(0).toUpperCase()}
                        </div>
                    )}
                </div>
                <div className="flex-1 text-center sm:text-left">
                    {isEditing ? (
                        <div className="space-y-3 max-w-sm">
                            <input
                                type="text"
                                value={displayName}
                                onChange={(e) => setDisplayName(e.target.value)}
                                className="w-full px-4 py-2 bg-black border border-zinc-800 rounded-xl text-white focus:outline-none focus:border-brand-500"
                                placeholder="Display Name"
                            />
                            <div className="flex gap-2">
                                <button
                                    onClick={handleSave}
                                    disabled={isSaving}
                                    className="px-5 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
                                >
                                    {isSaving ? 'Saving...' : 'Save Changes'}
                                </button>
                                <button
                                    onClick={() => setIsEditing(false)}
                                    className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm text-zinc-300 transition-colors"
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    ) : (
                        <>
                            <h3 className="text-2xl font-bold text-white">{displayName}</h3>
                            <p className="text-zinc-400 flex items-center gap-2 justify-center sm:justify-start mt-1">
                                <Mail className="w-4 h-4" /> {email}
                            </p>
                            <div className="flex items-center gap-2 mt-2 justify-center sm:justify-start flex-wrap">
                                {providers.map((p: string) => (
                                    <span key={p} className="text-xs px-2 py-0.5 bg-brand-500/10 text-brand-400 rounded-md border border-brand-500/20 font-medium capitalize">
                                        {p}
                                    </span>
                                ))}
                                {createdAt && (
                                    <span className="text-xs text-zinc-500 flex items-center gap-1">
                                        <Calendar className="w-3 h-3" /> Since {new Date(createdAt).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}
                                    </span>
                                )}
                            </div>
                            <button
                                onClick={() => setIsEditing(true)}
                                className="mt-4 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm text-zinc-300 transition-colors"
                            >
                                Edit Profile
                            </button>
                        </>
                    )}
                </div>
            </section>

            {/* Pipeline Stats — placeholder until real data exists */}
            <section className="mb-6">
                <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4 ml-1">Pipeline Activity</h3>
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-8 text-center">
                    <Film className="w-10 h-10 text-zinc-700 mx-auto mb-3" />
                    <p className="text-zinc-400 text-sm">Pipeline stats will appear here once you process your first episode.</p>
                    <a href="/dashboard" className="inline-block mt-4 text-brand-400 text-sm hover:text-brand-300 transition-colors">
                        Go to Dashboard →
                    </a>
                </div>
            </section>

            {/* Connected Accounts */}
            <section className="mb-6">
                <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4 ml-1">Connected Accounts</h3>
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl divide-y divide-white/5">
                    <div className="p-5 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="w-9 h-9 bg-red-500/10 rounded-xl flex items-center justify-center">
                                <svg className="w-5 h-5 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" /></svg>
                            </div>
                            <div>
                                <p className="text-white font-medium text-sm">YouTube</p>
                                {ytStatus.connected ? (
                                    <p className="text-xs text-green-400">Connected — {ytStatus.channel_name}</p>
                                ) : (
                                    <p className="text-xs text-zinc-500">Not connected</p>
                                )}
                            </div>
                        </div>
                        {ytStatus.connected ? (
                            <span className="text-xs text-zinc-500">via OAuth</span>
                        ) : (
                            <a href="/dashboard/intelligence" className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs text-zinc-300 font-medium transition-colors flex items-center gap-1.5">
                                Connect <ExternalLink className="w-3 h-3" />
                            </a>
                        )}
                    </div>
                    {providers.includes('github') && (
                        <div className="p-5 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 bg-white/5 rounded-xl flex items-center justify-center">
                                    <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
                                </div>
                                <div>
                                    <p className="text-white font-medium text-sm">GitHub</p>
                                    <p className="text-xs text-green-400">Connected</p>
                                </div>
                            </div>
                            <span className="text-xs text-zinc-500">via OAuth</span>
                        </div>
                    )}
                    {providers.includes('google') && (
                        <div className="p-5 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 bg-white/5 rounded-xl flex items-center justify-center">
                                    <svg className="w-4 h-4" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" /><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" /><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" /><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" /></svg>
                                </div>
                                <div>
                                    <p className="text-white font-medium text-sm">Google</p>
                                    <p className="text-xs text-green-400">Connected</p>
                                </div>
                            </div>
                            <span className="text-xs text-zinc-500">via OAuth</span>
                        </div>
                    )}
                </div>
            </section>

            {/* Danger Zone */}
            <section>
                <h3 className="text-sm font-medium text-red-400/60 uppercase tracking-widest mb-4 ml-1">Danger Zone</h3>
                <div className="bg-zinc-900/40 border border-red-500/10 rounded-2xl p-5 flex items-center justify-between">
                    <div>
                        <p className="text-white font-medium text-sm">Clear All Generated Data</p>
                        <p className="text-xs text-zinc-500">Removes all clips, jobs, and intelligence data. This cannot be undone.</p>
                    </div>
                    <button className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 rounded-xl text-xs text-red-400 font-medium transition-colors whitespace-nowrap">
                        Clear Data
                    </button>
                </div>
            </section>
        </div>
    );
};
