import React from 'react';
import { Search, Bell, User } from 'lucide-react';

export const Header: React.FC = () => {
    return (
        <header className="h-16 border-b border-zinc-800/50 bg-black/40 backdrop-blur-xl sticky top-0 z-30 flex items-center justify-between px-6">
            <div className="flex items-center gap-4 flex-1">
                {/* Search Bar */}
                <div className="relative w-full max-w-md hidden sm:block">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Search className="h-4 w-4 text-zinc-500" />
                    </div>
                    <input
                        type="text"
                        className="block w-full pl-10 pr-3 py-2 border border-zinc-800 rounded-xl leading-5 bg-zinc-900/50 text-zinc-300 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500 focus:border-brand-500 sm:text-sm transition-all duration-200"
                        placeholder="Search episodes (Local Intelligence)..."
                    />
                </div>
            </div>

            <div className="flex items-center gap-4">
                {/* Notifications */}
                <button className="p-2 rounded-full text-zinc-400 hover:text-zinc-100 hover:bg-white/5 transition-colors relative">
                    <Bell className="h-5 w-5" />
                    <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-brand-500 border border-black"></span>
                </button>

                {/* User Profile */}
                <div className="flex items-center gap-3 pl-4 border-l border-zinc-800/50">
                    <div className="text-right hidden md:block">
                        <p className="text-sm font-medium text-zinc-200 leading-tight">Creator</p>
                        <p className="text-xs text-zinc-500">Local Environment</p>
                    </div>
                    <button className="h-8 w-8 rounded-full bg-zinc-800 flex items-center justify-center border border-zinc-700 overflow-hidden hover:border-brand-500 transition-colors">
                        <User className="h-4 w-4 text-zinc-400" />
                    </button>
                </div>
            </div>
        </header>
    );
};
