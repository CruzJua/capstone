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

export async function fetchTenantDocuments(tenantId) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/documents`,
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
                `Failed to load documents for ${tenantId} (HTTP ${response.status})`
        );
    }

    const data = await response.json();
    return Array.isArray(data) ? data : data.documents || [];
}

export async function fetchTenantDocumentDetail(tenantId, docId) {
    if (!tenantId || !docId) {
        throw new Error("tenantId and docId are required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/documents/${encodeURIComponent(docId)}`,
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
                `Failed to load document '${docId}' (HTTP ${response.status})`
        );
    }

    return response.json();
}

export async function fetchTenantChunks(
    tenantId,
    { page = 1, limit = 50, docId = "", search = "" } = {}
) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("limit", String(limit));
    if (docId) params.set("doc_id", docId);
    if (search) params.set("search", search);

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/chunks?${params.toString()}`,
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
                `Failed to load chunks for ${tenantId} (HTTP ${response.status})`
        );
    }

    return response.json();
}

export async function uploadTenantDocument({
    file,
    tenantId,
    overwrite = true,
    docId = "",
}) {
    if (!file) {
        throw new Error("A file (.md or .json) is required.");
    }
    if (!tenantId) {
        throw new Error("tenantId is required.");
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("tenant_id", tenantId);
    formData.append("overwrite", overwrite ? "true" : "false");
    if (docId) {
        formData.append("doc_id", docId);
    }

    const response = await fetch(`${GATEWAY_BASE_URL}/api/documents/upload`, {
        method: "POST",
        body: formData,
    });

    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.status === "error") {
        throw new Error(
            body.error || `Document upload failed (HTTP ${response.status})`
        );
    }

    return body;
}
