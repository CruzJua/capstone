const GATEWAY_BASE_URL =
    process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:4000";

let unauthorizedHandler = null;

export function registerUnauthorizedHandler(handler) {
    unauthorizedHandler = typeof handler === "function" ? handler : null;
}

function notifyUnauthorized() {
    if (unauthorizedHandler) {
        try {
            unauthorizedHandler();
        } catch {
            // Ignore handler errors
        }
    }
}

function buildHeaders(extraHeaders = {}) {
    return {
        "X-Requested-With": "XMLHttpRequest",
        ...extraHeaders,
    };
}

async function handleApiResponse(response, fallbackErrorMessage, { suppressUnauthorizedRedirect = false } = {}) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        if (response.status === 401 && !suppressUnauthorizedRedirect) {
            notifyUnauthorized();
        }
        const detailMsg = Array.isArray(body.details)
            ? body.details.join(" ")
            : "";
        const message =
            [body.error, detailMsg].filter(Boolean).join(" — ") ||
            `${fallbackErrorMessage} (HTTP ${response.status})`;
        const error = new Error(message);
        error.status = response.status;
        error.code = body.code || null;
        throw error;
    }
    return body;
}

export async function fetchAuthConfig() {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/config`, {
        method: "GET",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        cache: "no-store",
    });

    return handleApiResponse(
        response,
        "Failed to load authentication configuration",
        { suppressUnauthorizedRedirect: true }
    );
}

export async function fetchAuthSession() {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/session`, {
        method: "GET",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        cache: "no-store",
    });

    return handleApiResponse(response, "No active session", {
        suppressUnauthorizedRedirect: true,
    });
}

export async function loginAdmin({ email, password }) {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        body: JSON.stringify({ email, password }),
    });

    return handleApiResponse(response, "Login failed", {
        suppressUnauthorizedRedirect: true,
    });
}

export async function signupAdmin(payload) {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/signup`, {
        method: "POST",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        body: JSON.stringify(payload),
    });

    return handleApiResponse(response, "Account registration failed", {
        suppressUnauthorizedRedirect: true,
    });
}

export async function demoLoginPreset(tenantId) {
    if (!tenantId) {
        throw new Error("Preset tenant_id is required");
    }

    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/demo-login`, {
        method: "POST",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        body: JSON.stringify({ tenant_id: tenantId }),
    });

    return handleApiResponse(response, "Demo login failed", {
        suppressUnauthorizedRedirect: true,
    });
}

export async function logoutSession() {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/auth/logout`, {
        method: "POST",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
    });

    return handleApiResponse(response, "Logout failed", {
        suppressUnauthorizedRedirect: true,
    });
}

export async function fetchTenants() {
    const response = await fetch(`${GATEWAY_BASE_URL}/api/tenants`, {
        method: "GET",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        cache: "no-store",
    });

    const data = await handleApiResponse(response, "Failed to load tenants");
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
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            cache: "no-store",
        }
    );

    return handleApiResponse(
        response,
        `Failed to load configuration for ${tenantId}`
    );
}

export async function updateTenantConfig(tenantId, configPayload) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/config`,
        {
            method: "PUT",
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            body: JSON.stringify(configPayload),
        }
    );

    return handleApiResponse(
        response,
        `Failed to update configuration for ${tenantId}`
    );
}

export async function fetchTenantDocuments(tenantId) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/documents`,
        {
            method: "GET",
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            cache: "no-store",
        }
    );

    const data = await handleApiResponse(
        response,
        `Failed to load documents for ${tenantId}`
    );
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
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            cache: "no-store",
        }
    );

    return handleApiResponse(response, `Failed to load document '${docId}'`);
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
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            cache: "no-store",
        }
    );

    return handleApiResponse(
        response,
        `Failed to load chunks for ${tenantId}`
    );
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
        headers: buildHeaders(),
        credentials: "include",
        body: formData,
    });

    return handleApiResponse(response, "Document upload failed");
}

export async function fetchTenantTickets(
    tenantId,
    { status = "all", search = "" } = {}
) {
    if (!tenantId) {
        throw new Error("tenantId is required");
    }

    const params = new URLSearchParams();
    if (status && status !== "all") {
        params.set("status", status);
    }
    if (search && search.trim()) {
        params.set("search", search.trim());
    }

    const queryString = params.toString();
    const url = `${GATEWAY_BASE_URL}/api/tenants/${encodeURIComponent(tenantId)}/tickets${
        queryString ? `?${queryString}` : ""
    }`;

    const response = await fetch(url, {
        method: "GET",
        headers: buildHeaders({
            "Content-Type": "application/json",
        }),
        credentials: "include",
        cache: "no-store",
    });

    const data = await handleApiResponse(
        response,
        `Failed to load tickets for ${tenantId}`
    );
    return Array.isArray(data) ? data : data.tickets || [];
}

export async function updateTicketStatus(ticketId, payload = {}) {
    if (!ticketId) {
        throw new Error("ticketId is required");
    }

    const response = await fetch(
        `${GATEWAY_BASE_URL}/api/tickets/${encodeURIComponent(ticketId)}`,
        {
            method: "PATCH",
            headers: buildHeaders({
                "Content-Type": "application/json",
            }),
            credentials: "include",
            body: JSON.stringify(payload),
        }
    );

    return handleApiResponse(response, `Failed to update ticket ${ticketId}`);
}
