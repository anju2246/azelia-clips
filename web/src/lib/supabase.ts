import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.PUBLIC_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
    console.warn('Missing Supabase environment variables. Auth features will be disabled.');
}

console.log('🔌 Connecting to Supabase Project:', supabaseUrl);

export const supabase = createClient(
    supabaseUrl || '',
    supabaseAnonKey || ''
);

export async function getSession() {
    const { data } = await supabase.auth.getSession();
    return data.session;
}

export async function getUser() {
    const { data } = await supabase.auth.getUser();
    return data.user;
}

export async function signInWithGoogle() {
    const redirectUrl = window.location.origin + '/settings'; // Redirect back to settings or dashboard
    const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
            redirectTo: redirectUrl,
        },
    });
    if (error) throw error;
    return data;
}

export async function signInWithEmail(email: string) {
    const redirectUrl = window.location.origin + '/settings';
    const { data, error } = await supabase.auth.signInWithOtp({
        email,
        options: {
            emailRedirectTo: redirectUrl,
        },
    });
    if (error) throw error;
    return data;
}

export async function signOut() {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
}

export async function getProfile(userId: string) {
    const { data, error } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', userId)
        .single();

    if (error) {
        console.error('Error fetching profile:', error);
        return null;
    }

    return data;
}
