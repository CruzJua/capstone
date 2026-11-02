"use client";

import React, {
    createContext,
    useContext,
    useState,
    useEffect,
    useCallback,
} from "react";
import {
    fetchAuthConfig,
    fetchAuthSession,
    loginAdmin,
    signupAdmin,
    demoLoginPreset,
    logoutSession,
    registerUnauthorizedHandler,
} from "@/lib/api";

const AuthContext = createContext(null);

const STORAGE_KEY = "capstone_active_tenant_id";

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [authorizedTenants, setAuthorizedTenants] = useState([]);
    const [appMode, setAppMode] = useState("standard");
    const [demoLoginEnabled, setDemoLoginEnabled] = useState(false);
    const [presetTenants, setPresetTenants] = useState([]);
    const [loading, setLoading] = useState(true);
    const [sessionVersion, setSessionVersion] = useState(0);

    const clearSessionState = useCallback(() => {
        setUser(null);
        setAuthorizedTenants([]);
        setSessionVersion((v) => v + 1);
        if (typeof window !== "undefined") {
            window.localStorage.removeItem(STORAGE_KEY);
        }
    }, []);

    const applyAuthenticatedPayload = useCallback((payload) => {
        const nextUser = payload?.user || null;
        const nextTenants = Array.isArray(payload?.authorized_tenants)
            ? payload.authorized_tenants
            : payload?.tenant
            ? [payload.tenant]
            : [];

        if (payload?.app_mode) {
            setAppMode(payload.app_mode);
        }

        setUser(nextUser);
        setAuthorizedTenants(nextTenants);
        setSessionVersion((v) => v + 1);

        if (typeof window !== "undefined") {
            const primaryId =
                nextUser?.tenant_id || nextTenants[0]?.tenant_id || "";
            if (primaryId) {
                window.localStorage.setItem(STORAGE_KEY, primaryId);
            } else {
                window.localStorage.removeItem(STORAGE_KEY);
            }
        }
    }, []);

    useEffect(() => {
        registerUnauthorizedHandler(() => {
            clearSessionState();
        });
        return () => {
            registerUnauthorizedHandler(null);
        };
    }, [clearSessionState]);

    useEffect(() => {
        let cancelled = false;

        async function bootstrapAuth() {
            await Promise.resolve();
            if (cancelled) return;

            try {
                const config = await fetchAuthConfig().catch(() => ({
                    app_mode: "standard",
                    demo_login_enabled: false,
                    preset_tenants: [],
                }));

                if (!cancelled) {
                    setAppMode(config.app_mode || "standard");
                    setDemoLoginEnabled(Boolean(config.demo_login_enabled));
                    setPresetTenants(
                        Array.isArray(config.preset_tenants)
                            ? config.preset_tenants
                            : []
                    );
                }

                const sessionData = await fetchAuthSession();
                if (!cancelled && sessionData?.authenticated && sessionData?.user) {
                    applyAuthenticatedPayload(sessionData);
                }
            } catch {
                if (!cancelled) {
                    clearSessionState();
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        bootstrapAuth();
        return () => {
            cancelled = true;
        };
    }, [applyAuthenticatedPayload, clearSessionState]);

    const login = useCallback(
        async ({ email, password }) => {
            clearSessionState();
            const payload = await loginAdmin({ email, password });
            applyAuthenticatedPayload(payload);
            return payload;
        },
        [applyAuthenticatedPayload, clearSessionState]
    );

    const signup = useCallback(
        async (signupPayload) => {
            clearSessionState();
            const payload = await signupAdmin(signupPayload);
            applyAuthenticatedPayload(payload);
            return payload;
        },
        [applyAuthenticatedPayload, clearSessionState]
    );

    const demoLogin = useCallback(
        async (presetTenantId) => {
            try {
                const payload = await demoLoginPreset(presetTenantId);
                applyAuthenticatedPayload(payload);
                return payload;
            } catch (err) {
                clearSessionState();
                throw err;
            }
        },
        [applyAuthenticatedPayload, clearSessionState]
    );

    const logout = useCallback(async () => {
        try {
            await logoutSession();
        } catch {
            // Even if server session was already expired, clear local auth state
        } finally {
            clearSessionState();
        }
    }, [clearSessionState]);

    const authenticated = Boolean(user && user.user_id && user.tenant_id);

    return (
        <AuthContext.Provider
            value={{
                user,
                authenticated,
                authorizedTenants,
                appMode,
                demoLoginEnabled,
                presetTenants,
                loading,
                sessionVersion,
                login,
                signup,
                demoLogin,
                logout,
                clearSessionState,
            }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
}

