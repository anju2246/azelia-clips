import React, { useState } from 'react';
import { User, Mail, Camera, Shield, HardDrive, Film, BarChart3, Calendar, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';

export const UserProfile: React.FC = () => {
    const [displayName, setDisplayName] = useState('Creator');
    const [email, setEmail] = useState('creator@studio.local');
    const [isEditing, setIsEditing] = useState(false);

    // Mock stats - in production these come from the API
    const stats = {
        episodesProcessed: 12,
        clipsGenerated: 87,
        clipsApproved: 64,
        avgViralityScore: 84.5,
        memberSince: '2026-02-01',
        storageUsed: '2.4 GB',
    };

    const handleSave = () => {
        setIsEditing(false);
        toast.success('Profile updated');
    };

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
                    <div className="w-24 h-24 rounded-full bg-gradient-to-br from-brand-500 to-emerald-600 flex items-center justify-center text-white text-3xl font-bold shadow-xl shadow-brand-500/20">
                        {displayName.charAt(0).toUpperCase()}
                    </div>
                    <button className="absolute bottom-0 right-0 w-8 h-8 bg-zinc-800 border border-zinc-700 rounded-full flex items-center justify-center text-zinc-400 hover:text-white hover:bg-zinc-700 transition-colors opacity-0 group-hover:opacity-100">
                        <Camera className="w-4 h-4" />
                    </button>
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
                            <input
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                className="w-full px-4 py-2 bg-black border border-zinc-800 rounded-xl text-white focus:outline-none focus:border-brand-500 font-mono text-sm"
                                placeholder="Email"
                            />
                            <button onClick={handleSave} className="px-5 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors">
                                Save Changes
                            </button>
                        </div>
                    ) : (
                        <>
                            <h3 className="text-2xl font-bold text-white">{displayName}</h3>
                            <p className="text-zinc-400 flex items-center gap-2 justify-center sm:justify-start mt-1">
                                <Mail className="w-4 h-4" /> {email}
                            </p>
                            <div className="flex items-center gap-2 mt-2 justify-center sm:justify-start">
                                <span className="text-xs px-2 py-0.5 bg-brand-500/10 text-brand-400 rounded-md border border-brand-500/20 font-medium">
                                    Local Engine
                                </span>
                                <span className="text-xs text-zinc-500 flex items-center gap-1">
                                    <Calendar className="w-3 h-3" /> Since {new Date(stats.memberSince).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}
                                </span>
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

            {/* Pipeline Stats */}
            <section className="mb-6">
                <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4 ml-1">Pipeline Activity</h3>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {[
                        { label: "Episodes Processed", value: stats.episodesProcessed, icon: Film, color: "text-blue-400", bg: "bg-blue-500/10" },
                        { label: "Clips Generated", value: stats.clipsGenerated, icon: BarChart3, color: "text-purple-400", bg: "bg-purple-500/10" },
                        { label: "Clips Approved", value: stats.clipsApproved, icon: Shield, color: "text-brand-400", bg: "bg-brand-500/10" },
                        { label: "Avg. Virality", value: stats.avgViralityScore, icon: BarChart3, color: "text-amber-400", bg: "bg-amber-500/10" },
                    ].map(stat => (
                        <div key={stat.label} className="bg-zinc-900/40 border border-white/5 rounded-2xl p-5">
                            <div className={`w-9 h-9 ${stat.bg} rounded-xl flex items-center justify-center mb-3`}>
                                <stat.icon className={`w-4 h-4 ${stat.color}`} />
                            </div>
                            <p className="text-2xl font-bold text-white">{stat.value}</p>
                            <p className="text-xs text-zinc-500 mt-1">{stat.label}</p>
                        </div>
                    ))}
                </div>
            </section>

            {/* Storage */}
            <section className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6 mb-6">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <div className="w-9 h-9 bg-emerald-500/10 rounded-xl flex items-center justify-center">
                            <HardDrive className="w-4 h-4 text-emerald-400" />
                        </div>
                        <div>
                            <h4 className="text-white font-medium">Local Storage</h4>
                            <p className="text-xs text-zinc-500">{stats.storageUsed} used by generated clips</p>
                        </div>
                    </div>
                </div>
                <div className="h-2 w-full bg-black rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-brand-500 to-emerald-500 rounded-full" style={{ width: '24%' }} />
                </div>
                <p className="text-xs text-zinc-500 mt-2">~10 GB available on disk</p>
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
                                <p className="text-xs text-zinc-500">Not connected</p>
                            </div>
                        </div>
                        <a href="/dashboard/intelligence" className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs text-zinc-300 font-medium transition-colors flex items-center gap-1.5">
                            Connect <ExternalLink className="w-3 h-3" />
                        </a>
                    </div>
                    <div className="p-5 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="w-9 h-9 bg-green-500/10 rounded-xl flex items-center justify-center text-green-500 font-bold text-sm">
                                S
                            </div>
                            <div>
                                <p className="text-white font-medium text-sm">Supabase</p>
                                <p className="text-xs text-zinc-500">Not configured</p>
                            </div>
                        </div>
                        <a href="/dashboard/settings" className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs text-zinc-300 font-medium transition-colors flex items-center gap-1.5">
                            Configure <ExternalLink className="w-3 h-3" />
                        </a>
                    </div>
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
