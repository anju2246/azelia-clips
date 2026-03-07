import React, { useState } from 'react';
import { Home, Film, LineChart, Settings, Bell, User, LogOut, BellOff } from 'lucide-react';
import { signOut } from '../../lib/supabase';

interface SidebarProps {
    currentPath: string;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentPath }) => {
    const [showNotifs, setShowNotifs] = useState(false);

    // Group 1: Core tool features (the "engine")
    const toolLinks = [
        { href: "/dashboard", label: "Dashboard", icon: Home },
        { href: "/dashboard/review", label: "Review Clips", icon: Film },
        { href: "/dashboard/intelligence", label: "Intelligence", icon: LineChart },
    ];

    // Group 2: System/config
    const systemLinks = [
        { href: "/dashboard/settings", label: "Settings", icon: Settings },
    ];

    const isActive = (href: string) =>
        href === "/dashboard"
            ? currentPath === "/dashboard" || currentPath === "/dashboard/"
            : currentPath.startsWith(href);

    const NavIcon = ({ href, label, icon: Icon }: { href: string; label: string; icon: React.ElementType }) => {
        const active = isActive(href);
        return (
            <a
                href={href}
                title={label}
                className={`
          group relative w-11 h-11 flex items-center justify-center rounded-2xl transition-all duration-200
          ${active
                        ? 'bg-brand-500 text-white shadow-lg shadow-brand-500/30'
                        : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/5'
                    }
        `}
            >
                <Icon className="w-5 h-5" strokeWidth={active ? 2.2 : 1.8} />
                {/* Tooltip */}
                <span className="absolute left-full ml-3 px-2.5 py-1 bg-zinc-800 text-white text-xs font-medium rounded-lg opacity-0 pointer-events-none group-hover:opacity-100 whitespace-nowrap transition-opacity shadow-xl border border-white/10 z-50">
                    {label}
                </span>
            </a>
        );
    };

    return (
        <aside className="w-[72px] border-r border-white/[0.06] bg-black/30 backdrop-blur-2xl hidden md:flex flex-col items-center py-5 relative z-20">

            {/* Brand Logo */}
            <a href="/dashboard" className="mb-8">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center hover:scale-105 transition-transform overflow-hidden shadow-lg shadow-brand-500/20">
                    <img src="/favicon.svg" alt="Azelia Logo" className="w-full h-full object-contain" />
                </div>
            </a>

            {/* Group 1: Core Tool Features */}
            <div className="bg-white/[0.04] rounded-2xl p-1.5 flex flex-col items-center gap-1">
                {toolLinks.map(link => (
                    <NavIcon key={link.href} {...link} />
                ))}
            </div>

            {/* Divider */}
            <div className="w-6 h-px bg-white/[0.06] my-4" />

            {/* Group 2: Settings + Notifications */}
            <div className="bg-white/[0.04] rounded-2xl p-1.5 flex flex-col items-center gap-1 relative">
                <button
                    title="Notifications"
                    onClick={() => setShowNotifs(!showNotifs)}
                    className={`group relative w-11 h-11 flex items-center justify-center rounded-2xl transition-colors ${showNotifs ? 'bg-white/10 text-zinc-200' : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/5'}`}
                >
                    <Bell className="w-5 h-5" strokeWidth={1.8} />
                </button>

                {/* Notification Popover */}
                {showNotifs && (
                    <div className="absolute left-full ml-3 bottom-0 w-72 bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl z-50 overflow-hidden">
                        <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
                            <span className="text-sm font-semibold text-white">Notifications</span>
                            <button onClick={() => setShowNotifs(false)} className="text-zinc-500 hover:text-zinc-300 text-xs">Close</button>
                        </div>
                        <div className="p-6 flex flex-col items-center text-center">
                            <BellOff className="w-8 h-8 text-zinc-600 mb-2" />
                            <p className="text-sm text-zinc-400">No notifications yet</p>
                            <p className="text-xs text-zinc-600 mt-1">Job completions and alerts will appear here.</p>
                        </div>
                    </div>
                )}

                {systemLinks.map(link => (
                    <NavIcon key={link.href} {...link} />
                ))}
            </div>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Group 3: User Profile + Logout */}
            <div className="bg-white/[0.04] rounded-2xl p-1.5 flex flex-col items-center gap-1 mb-2">
                <a
                    href="/dashboard/profile"
                    title="Profile"
                    className={`group relative w-11 h-11 flex items-center justify-center rounded-2xl transition-all duration-200 ${currentPath.startsWith('/dashboard/profile')
                        ? 'bg-brand-500 text-white shadow-lg shadow-brand-500/30'
                        : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/5'
                        }`}
                >
                    <User className="w-5 h-5" strokeWidth={1.8} />
                    <span className="absolute left-full ml-3 px-2.5 py-1 bg-zinc-800 text-white text-xs font-medium rounded-lg opacity-0 pointer-events-none group-hover:opacity-100 whitespace-nowrap transition-opacity shadow-xl border border-white/10 z-50">
                        Profile
                    </span>
                </a>
                <button
                    onClick={async () => {
                        try {
                            await signOut();
                        } catch (e) {
                            console.error('Logout failed:', e);
                        } finally {
                            window.location.href = '/login';
                        }
                    }}
                    title="Logout"
                    className="group relative w-11 h-11 flex items-center justify-center rounded-2xl text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-all duration-200"
                >
                    <LogOut className="w-5 h-5" strokeWidth={1.8} />
                    <span className="absolute left-full ml-3 px-2.5 py-1 bg-zinc-800 text-white text-xs font-medium rounded-lg opacity-0 pointer-events-none group-hover:opacity-100 whitespace-nowrap transition-opacity shadow-xl border border-white/10 z-50">
                        Log Out
                    </span>
                </button>
            </div>
        </aside>
    );
};
