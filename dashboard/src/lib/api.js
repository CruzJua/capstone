const GATEWAY_BASE_URL =
    process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:4000";

export async function fetchTenants() {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/tenants`, {
        method: "GET",
        headers: {
            "Content-Type": "application/json",
        },
        cache: "no-store",
    });

    if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
            errorBody.error || `Failed to load tenants (HTTP ${response.status})`
        );
    }

    const data = await response.json();
    return Array.isArray(data) ? data : data.tenants || [];
}

export async function fetchTenantConfig(tenantId) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/config`,
        {
            method: "GET",
            headers: {
                "Content-Type": "application/json",
            },
            cache: "no-store",
        }
    );

    if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
            errorBody.error ||
                `Failed to load configuration for ${tenantId} (HTTP ${response.status})`
        );
    }

    return response.json();
}

export async function updateTenantConfig(tenantId, configPayload) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/config`,
        {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(configPayload),
        }
    );

    if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        const detailMsg = Array.isArray(errorBody.details)
            ? errorBody.details.join(" ")
            : "";
        throw new Error(
            [errorBody.error, detailMsg].filter(Boolean).join(" — ") ||
                `Failed to update configuration for ${tenantId} (HTTP ${response.status})`
        );
    }

    return response.json();
}

