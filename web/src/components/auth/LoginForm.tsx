import React, { useState } from 'react';
import { Github, Mail, ArrowRight } from 'lucide-react';
import toast from 'react-hot-toast';

export const LoginForm: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsLoading(true);

        // For MVP Local Mode, we simulate login or just let them through
        // In production, this would call Supabase auth or your FastAPI auth endpoint
        setTimeout(() => {
            toast.success('Successfully authenticated to Local Engine');
            window.location.href = '/dashboard';
            setIsLoading(false);
        }, 800);
    };

    const handleOAuth = (provider: string) => {
        toast('OAuth flow would start here for ' + provider, { icon: '🔄' });
    };

    return (
        <div className="w-full max-w-md mx-auto relative">
            {/* Decorative elements */}
            <div className="absolute -inset-1 bg-gradient-to-r from-brand-500 to-emerald-500 rounded-[2rem] blur-xl opacity-20"></div>

            <div className="bg-zinc-950/80 backdrop-blur-2xl border border-white/10 p-8 rounded-[2rem] shadow-2xl relative">
                <div className="text-center mb-8">
                    <div className="w-16 h-16 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center mx-auto mb-6">
                        <span className="text-3xl font-bold text-brand-400">C</span>
                    </div>
                    <h1 className="text-2xl font-bold text-white mb-2">Welcome Back</h1>
                    <p className="text-zinc-400 text-sm">Sign in to your Intellectual Video Engine.</p>
                </div>

                <form onSubmit={handleLogin} className="space-y-4 mb-6">
                    <div>
                        <label className="block text-xs font-medium text-zinc-400 mb-1.5 ml-1 uppercase tracking-wider">Email Address</label>
                        <div className="relative">
                            <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                                <Mail className="h-4 w-4 text-zinc-500" />
                            </div>
                            <input
                                type="email"
                                value={email}
                                autoComplete="email"
                                onChange={(e) => setEmail(e.target.value)}
                                className="w-full pl-10 pr-4 py-3 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-white transition-all"
                                placeholder="you@creator.com"
                                required
                            />
                        </div>
                    </div>

                    <div>
                        <div className="flex justify-between mb-1.5 ml-1">
                            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider">Password</label>
                            <a href="#" className="text-xs text-brand-400 hover:text-brand-300">Forgot?</a>
                        </div>
                        <input
                            type="password"
                            value={password}
                            autoComplete="current-password"
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full px-4 py-3 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-white transition-all"
                            placeholder="••••••••"
                            required
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-all shadow-lg shadow-brand-500/20 flex items-center justify-center gap-2 mt-2 disabled:opacity-50"
                    >
                        {isLoading ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            <>Sign In <ArrowRight className="w-4 h-4" /></>
                        )}
                    </button>
                </form>

                <div className="relative mb-6">
                    <div className="absolute inset-0 flex items-center">
                        <div className="w-full border-t border-white/5"></div>
                    </div>
                    <div className="relative flex justify-center text-sm">
                        <span className="px-3 bg-zinc-950/80 text-zinc-500">Or continue with</span>
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                    <button
                        onClick={() => handleOAuth('google')}
                        type="button"
                        className="flex items-center justify-center gap-2 py-2.5 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl text-sm font-medium text-white transition-colors"
                    >
                        <svg className="w-4 h-4" viewBox="0 0 24 24">
                            <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                        </svg>
                        Google
                    </button>
                    <button
                        onClick={() => handleOAuth('github')}
                        type="button"
                        className="flex items-center justify-center gap-2 py-2.5 bg-white/5 hover:bg-white/10 border border-white/5 rounded-xl text-sm font-medium text-white transition-colors"
                    >
                        <Github className="w-4 h-4" />
                        GitHub
                    </button>
                </div>
            </div>
        </div>
    );
};
