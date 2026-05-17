/**
 * Local-first MVP stub.
 *
 * The real Supabase client was removed when we cut the central backend.
 * This shim returns dummy session/user data so existing components that
 * imported from `lib/supabase` don't break while we finish migrating them.
 *
 * Goal for v0.1.0 frontend cleanup: remove every `getSession()` /
 * `getUser()` call site so we can delete this file too. Until then,
 * components see a stable "local owner" session.
 */

const LOCAL_USER = {
    id: 'local',
    email: 'local@azelia',
    user_metadata: { name: 'Local User' },
    app_metadata: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
};

const LOCAL_SESSION = {
    user: LOCAL_USER,
    access_token: 'local',
    refresh_token: 'local',
    expires_in: 3600,
    expires_at: Date.now() / 1000 + 3600,
    token_type: 'bearer',
};

export const supabase = {
    auth: {
        getSession: async () => ({ data: { session: LOCAL_SESSION }, error: null }),
        getUser: async () => ({ data: { user: LOCAL_USER }, error: null }),
        onAuthStateChange: (_cb: unknown) => ({
            data: { subscription: { unsubscribe: () => {} } },
        }),
        signInWithPassword: async () => ({
            data: { user: LOCAL_USER, session: LOCAL_SESSION },
            error: null,
        }),
        signUp: async () => ({
            data: { user: LOCAL_USER, session: LOCAL_SESSION },
            error: null,
        }),
        signOut: async () => ({ error: null }),
        signInWithOAuth: async () => ({ data: { url: '/' }, error: null }),
        resetPasswordForEmail: async () => ({ data: {}, error: null }),
        updateUser: async () => ({ data: { user: LOCAL_USER }, error: null }),
    },
};

export const signOut = async () => {
    await supabase.auth.signOut();
    // In local mode there is nothing to redirect from — let the caller handle UX.
};
