import React, { useState, useEffect } from 'react';
import { Lock, ArrowRight, CheckCircle2 } from 'lucide-react';
import toast, { Toaster } from 'react-hot-toast';
import { supabase } from '../../lib/supabase';

export const ResetPasswordForm: React.FC = () => {
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isDone, setIsDone] = useState(false);
    const [sessionReady, setSessionReady] = useState(false);

    useEffect(() => {
        // Supabase auto-detects the recovery token from the URL hash
        // and establishes a session. We wait for that to complete.
        const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
            if (event === 'PASSWORD_RECOVERY') {
                setSessionReady(true);
            }
        });

        // Also check if session already exists (user refreshed the page)
        supabase.auth.getSession().then(({ data }) => {
            if (data?.session) setSessionReady(true);
        });

        return () => subscription.unsubscribe();
    }, []);

    const handleReset = async (e: React.FormEvent) => {
        e.preventDefault();

        if (password.length < 6) {
            toast.error('Password must be at least 6 characters.');
            return;
        }

        if (password !== confirmPassword) {
            toast.error('Passwords do not match.');
            return;
        }

        setIsLoading(true);
        try {
            const { error } = await supabase.auth.updateUser({ password });
            if (error) throw error;

            setIsDone(true);
            toast.success('Password updated successfully!', { icon: '🔑' });

            setTimeout(() => {
                window.location.replace('/dashboard');
            }, 2000);
        } catch (err: any) {
            toast.error(err.message || 'Failed to update password.');
        } finally {
            setIsLoading(false);
        }
    };

    if (isDone) {
        return (
            <div className="w-full max-w-md mx-auto text-center">
                <Toaster position="top-center" />
                <div className="bg-zinc-950/80 backdrop-blur-2xl border border-white/10 p-8 rounded-[2rem] shadow-2xl">
                    <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-4" />
                    <h1 className="text-2xl font-bold text-white mb-2">Password Updated</h1>
                    <p className="text-zinc-400 text-sm">Redirecting to dashboard...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="w-full max-w-md mx-auto relative">
            <Toaster position="top-center" />
            <div className="absolute -inset-1 bg-gradient-to-r from-brand-500 to-emerald-500 rounded-[2rem] blur-xl opacity-20"></div>

            <div className="bg-zinc-950/80 backdrop-blur-2xl border border-white/10 p-8 rounded-[2rem] shadow-2xl relative">
                <div className="text-center mb-8">
                    <div className="w-16 h-16 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center mx-auto mb-6">
                        <Lock className="w-7 h-7 text-brand-400" />
                    </div>
                    <h1 className="text-2xl font-bold text-white mb-2">Set New Password</h1>
                    <p className="text-zinc-400 text-sm">
                        Enter your new password below.
                    </p>
                </div>

                {!sessionReady ? (
                    <div className="text-center py-8">
                        <div className="w-8 h-8 border-2 border-zinc-700 border-t-brand-500 rounded-full animate-spin mx-auto mb-4"></div>
                        <p className="text-zinc-400 text-sm">Verifying reset token...</p>
                    </div>
                ) : (
                    <form onSubmit={handleReset} className="space-y-4">
                        <div>
                            <label className="block text-xs font-medium text-zinc-400 mb-1.5 ml-1 uppercase tracking-wider">New Password</label>
                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                className="w-full px-4 py-3 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-white transition-all"
                                placeholder="••••••••"
                                minLength={6}
                                required
                                autoFocus
                            />
                            <p className="text-xs text-zinc-600 mt-1 ml-1">Minimum 6 characters</p>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-zinc-400 mb-1.5 ml-1 uppercase tracking-wider">Confirm Password</label>
                            <input
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                className="w-full px-4 py-3 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 text-white transition-all"
                                placeholder="••••••••"
                                minLength={6}
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
                                <>
                                    Update Password <ArrowRight className="w-4 h-4" />
                                </>
                            )}
                        </button>
                    </form>
                )}

                <div className="text-center mt-6">
                    <a href="/login" className="text-sm text-zinc-500 hover:text-white transition-colors">
                        ← Back to Login
                    </a>
                </div>
            </div>
        </div>
    );
};
