"use client";

import React, {
    createContext,
    useContext,
    useState,
    useEffect,
    useCallback,
} from "react";
import { fetchTenants } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const TenantContext = createContext(null);

function getStorageKey(appMode) {
    return appMode === "preset_training"
        ? "capstone_demo_active_tenant_id"
        : "capstone_active_tenant_id";
}

export function TenantProvider({ children }) {
    const {
        authenticated,
        user,
        authorizedTenants,
        appMode,
        demoLoginEnabled,
        presetTenants,
        loading: authLoading,
        sessionVersion,
        demoLogin,
    } = useAuth();

    const [tenants, setTenants] = useState([]);
    const [activeTenantId, setActiveTenantIdState] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const userTenantId = user?.tenant_id || "";

    const applyAuthorizedTenantsList = useCallback(
        (list, primaryUserTenantId = "") => {
            const safeList = Array.isArray(list) ? list : [];
            setTenants(safeList);
            const storageKey = getStorageKey(appMode);

            if (safeList.length === 0) {
                setActiveTenantIdState("");
                if (typeof window !== "undefined") {
                    window.localStorage.removeItem(storageKey);
                }
                return;
            }

            const savedId =
                typeof window !== "undefined"
                    ? window.localStorage.getItem(storageKey)
                    : null;

            const matchingSaved = safeList.find((t) => t.tenant_id === savedId);
            const matchingUserPrimary = safeList.find(
                (t) => t.tenant_id === primaryUserTenantId
            );
            const selected =
                matchingUserPrimary || matchingSaved || safeList[0];

            setActiveTenantIdState(selected.tenant_id);
            if (typeof window !== "undefined") {
                window.localStorage.setItem(storageKey, selected.tenant_id);
            }
        },
        [appMode]
    );

    const refreshTenants = useCallback(async () => {
        if (!authenticated) {
            setTenants([]);
            setActiveTenantIdState("");
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const list = await fetchTenants();
            applyAuthorizedTenantsList(list, userTenantId);
        } catch (err) {
            setError(
                err.message || "Unable to load authorized tenant from Gateway."
            );
        } finally {
            setLoading(false);
        }
    }, [authenticated, userTenantId, applyAuthorizedTenantsList]);

    useEffect(() => {
        if (authLoading) return;
        let cancelled = false;

        async function syncTenantsWithSession() {
            await Promise.resolve();
            if (cancelled) return;

            if (!authenticated) {
                setTenants([]);
                setActiveTenantIdState("");
                setError(null);
                setLoading(false);
                return;
            }

            // Immediately apply session-supplied authorized tenants if present, then verify with GET /api/tenants
            if (authorizedTenants && authorizedTenants.length > 0) {
                applyAuthorizedTenantsList(authorizedTenants, userTenantId);
            }

            setLoading(true);
            setError(null);
            try {
                const list = await fetchTenants();
                if (!cancelled) {
                    applyAuthorizedTenantsList(list, userTenantId);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(
                        err.message ||
                            "Unable to load authorized tenant from Gateway."
                    );
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        syncTenantsWithSession();
        return () => {
            cancelled = true;
        };
    }, [
        authLoading,
        authenticated,
        sessionVersion,
        userTenantId,
        authorizedTenants,
        applyAuthorizedTenantsList,
    ]);

    const setActiveTenantId = useCallback(
        async (requestedTenantId) => {
            if (!requestedTenantId) return;

            // Check if already in authorized tenants list
            const isAuthorized = tenants.some(
                (t) => t.tenant_id === requestedTenantId
            );

            if (isAuthorized) {
                setActiveTenantIdState(requestedTenantId);
                if (typeof window !== "undefined") {
                    window.localStorage.setItem(
                        getStorageKey(appMode),
                        requestedTenantId
                    );
                }
                return;
            }

            // In preset_training mode, switching to another preset calls demo-login
            // to revoke the old session and issue a session for the new preset fixture.
            if (
                appMode === "preset_training" &&
                demoLoginEnabled &&
                presetTenants.some((p) => p.tenant_id === requestedTenantId)
            ) {
                setLoading(true);
                setError(null);
                try {
                    await demoLogin(requestedTenantId);
                } catch (err) {
                    setError(
                        err.message || "Failed to switch preset training tenant."
                    );
                } finally {
                    setLoading(false);
                }
            }
        },
        [tenants, appMode, demoLoginEnabled, presetTenants, demoLogin]
    );

    const updateTenantInList = useCallback((updatedTenant) => {
        if (!updatedTenant || !updatedTenant.tenant_id) return;
        setTenants((prev) =>
            prev.map((item) =>
                item.tenant_id === updatedTenant.tenant_id
                    ? updatedTenant
                    : item
            )
        );
    }, []);

    const activeTenant =
        tenants.find((t) => t.tenant_id === activeTenantId) || null;

    return (
        <TenantContext.Provider
            value={{
                tenants,
                activeTenantId,
                activeTenant,
                setActiveTenantId,
                updateTenantInList,
                refreshTenants,
                loading: authLoading || loading,
                error,
            }}
        >
            {children}
        </TenantContext.Provider>
    );
}

export function useTenant() {
    const context = useContext(TenantContext);
    if (!context) {
        throw new Error("useTenant must be used within a TenantProvider");
    }
    return context;
}
