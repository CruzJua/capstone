"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { fetchTenants } from "@/lib/api";

const TenantContext = createContext(null);

const STORAGE_KEY = "capstone_active_tenant_id";

export function TenantProvider({ children }) {
    const [tenants, setTenants] = useState([]);
    const [activeTenantId, setActiveTenantIdState] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const applyTenantsList = useCallback((list) => {
        setTenants(list);
        if (list.length > 0) {
            const savedId =
                typeof window !== "undefined"
                    ? window.localStorage.getItem(STORAGE_KEY)
                    : null;
            const matchingSaved = list.find((t) => t.tenant_id === savedId);
            const defaultTenant =
                matchingSaved ||
                list.find((t) => t.tenant_id === "iron_and_oak") ||
                list[0];

            setActiveTenantIdState((prev) => {
                if (prev && list.some((t) => t.tenant_id === prev)) {
                    return prev;
                }
                return defaultTenant.tenant_id;
            });
        }
    }, []);

    const refreshTenants = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const list = await fetchTenants();
            applyTenantsList(list);
        } catch (err) {
            setError(err.message || "Unable to connect to Orchestration Gateway.");
        } finally {
            setLoading(false);
        }
    }, [applyTenantsList]);

    useEffect(() => {
        let cancelled = false;

        async function initTenants() {
            try {
                const list = await fetchTenants();
                if (!cancelled) {
                    applyTenantsList(list);
                    setError(null);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err.message || "Unable to connect to Orchestration Gateway.");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        initTenants();
        return () => {
            cancelled = true;
        };
    }, [applyTenantsList]);

    const setActiveTenantId = useCallback((tenantId) => {
        setActiveTenantIdState(tenantId);
        if (typeof window !== "undefined" && tenantId) {
            window.localStorage.setItem(STORAGE_KEY, tenantId);
        }
    }, []);

    const updateTenantInList = useCallback((updatedTenant) => {
        if (!updatedTenant || !updatedTenant.tenant_id) return;
        setTenants((prev) =>
            prev.map((item) =>
                item.tenant_id === updatedTenant.tenant_id ? updatedTenant : item
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
                loading,
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
