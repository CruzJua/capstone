const fs = require("fs");
const path = require("path");

const MANIFEST_PATH = path.resolve(
    __dirname,
    "../../../data/fixtures/demo_manifest.json"
);

function loadDemoFixtureManifest() {
    const raw = fs.readFileSync(MANIFEST_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    if (
        !parsed ||
        typeof parsed !== "object" ||
        !Array.isArray(parsed.preset_tenants) ||
        !Array.isArray(parsed.sample_tickets)
    ) {
        throw new Error(
            `Invalid demo fixture manifest at ${MANIFEST_PATH}: expected preset_tenants[] and sample_tickets[].`
        );
    }
    return parsed;
}

const DEMO_FIXTURE_MANIFEST = loadDemoFixtureManifest();

const PRESET_TENANTS = DEMO_FIXTURE_MANIFEST.preset_tenants.map((tenant) => ({
    tenant_id: tenant.tenant_id,
    name: tenant.name,
    industry: tenant.industry,
    contact_email: tenant.contact_email,
    team_name: tenant.team_name,
    agent_config: { ...tenant.agent_config },
    source_dir: tenant.source_dir,
    source_documents: Array.isArray(tenant.source_documents)
        ? [...tenant.source_documents]
        : [],
}));

const SAMPLE_TICKETS = DEMO_FIXTURE_MANIFEST.sample_tickets.map((ticket) => ({
    ...ticket,
}));

const PRESET_TENANT_IDS = new Set(
    PRESET_TENANTS.map((tenant) => tenant.tenant_id)
);

const PUBLIC_PRESET_FIXTURES = PRESET_TENANTS.map((tenant) => ({
    tenant_id: tenant.tenant_id,
    name: tenant.name,
    industry: tenant.industry,
}));

function isPresetTenantId(tenantId) {
    if (typeof tenantId !== "string") return false;
    return PRESET_TENANT_IDS.has(tenantId.trim().toLowerCase());
}

function getPresetTenantById(tenantId) {
    if (typeof tenantId !== "string") return null;
    const normalized = tenantId.trim().toLowerCase();
    return (
        PRESET_TENANTS.find((tenant) => tenant.tenant_id === normalized) || null
    );
}

const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{1,62}$/;
const DOC_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._ -]{0,120}$/;

function isValidTenantId(tenantId) {
    if (typeof tenantId !== "string") return false;
    const trimmed = tenantId.trim();
    if (!TENANT_ID_PATTERN.test(trimmed)) return false;
    if (trimmed.includes("..")) return false;
    return true;
}

function isValidDocId(docId) {
    if (typeof docId !== "string") return false;
    const trimmed = docId.trim();
    if (!DOC_ID_PATTERN.test(trimmed)) return false;
    if (
        trimmed.includes("..") ||
        trimmed.includes("/") ||
        trimmed.includes("\\") ||
        trimmed.includes("$")
    ) {
        return false;
    }
    return true;
}

function slugifyTenantId(businessName) {
    if (typeof businessName !== "string") return "";
    return businessName
        .trim()
        .toLowerCase()
        .replace(/&/g, " and ")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "")
        .replace(/_+/g, "_")
        .slice(0, 48);
}

function buildDefaultSystemPrompt({
    businessName,
    industry,
    contactEmail,
}) {
    const cleanName = (businessName || "our business").trim();
    const cleanIndustry = (industry || "").trim();
    const cleanEmail = (contactEmail || "").trim();
    const sectorPhrase = cleanIndustry ? ` (${cleanIndustry})` : "";
    const escalationPhrase = cleanEmail
        ? ` If the answer is not verified by the provided context, state that clearly and offer to escalate the inquiry to ${cleanEmail}.`
        : " If the answer is not verified by the provided context, state that clearly and offer to escalate the inquiry to a human support specialist.";

    return `You are a customer support agent for ${cleanName}${sectorPhrase}. Answer customer questions strictly using the provided context chunks.${escalationPhrase}`;
}

module.exports = {
    MANIFEST_PATH,
    DEMO_FIXTURE_MANIFEST,
    PRESET_TENANTS,
    SAMPLE_TICKETS,
    PRESET_TENANT_IDS,
    PUBLIC_PRESET_FIXTURES,
    loadDemoFixtureManifest,
    isPresetTenantId,
    getPresetTenantById,
    isValidTenantId,
    isValidDocId,
    slugifyTenantId,
    buildDefaultSystemPrompt,
};
