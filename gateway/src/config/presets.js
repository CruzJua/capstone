const PRESET_TENANTS = [
    {
        tenant_id: "cinder_and_salt",
        name: "Cinder & Salt Bakery",
        industry: "Artisanal Bakery & Food Service",
        contact_email: "hello@cinderandsalt.com",
        team_name: "Bakery Guest Operations",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Cinder & Salt Bakery. Answer customer questions about allergens, daily bake schedules, wholesale accounts, and catering strictly using the provided context chunks.",
            agent_tone: "Warm & Professional",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "harbor_view",
        name: "Harbor View Veterinary Clinic",
        industry: "Veterinary Medicine & Pet Care",
        contact_email: "care@harborviewvet.com",
        team_name: "Client Care & Triage Team",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Harbor View Veterinary Clinic. Provide accurate, grounded guidance on appointments, post-operative recovery, pharmacy refills, and emergency triage strictly using the provided context chunks.",
            agent_tone: "Empathetic & Clinical",
            temperature: 0.15,
            max_context_chunks: 4,
            similarity_threshold: 0.75,
        },
    },
    {
        tenant_id: "iron_and_oak",
        name: "Iron & Oak Provision Co.",
        industry: "Outdoor Apparel & Heritage Gear",
        contact_email: "support@ironandoak.com",
        team_name: "Outfitter Support Team",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Iron & Oak Provision Co. Answer questions strictly using the provided context chunks.",
            agent_tone: "Rugged & Direct",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "kettle_and_loom",
        name: "Kettle & Loom Cleaning Collective",
        industry: "Eco-Friendly Residential & Commercial Cleaning",
        contact_email: "concierge@kettleandloom.com",
        team_name: "Member Concierge Desk",
        agent_config: {
            system_prompt:
                "You are a customer support agent for Kettle & Loom Cleaning Collective. Answer client inquiries about chemical safety, property access, cancellations, and post-construction remediation strictly using the provided context chunks.",
            agent_tone: "Warm & Professional",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.7,
        },
    },
    {
        tenant_id: "northstar_auto",
        name: "NorthStar Auto Care",
        industry: "Automotive Repair & Fleet Maintenance",
        contact_email: "service@northstarautocare.com",
        team_name: "Service Advisor Desk",
        agent_config: {
            system_prompt:
                "You are a customer support agent for NorthStar Auto Care. Answer questions regarding estimates, warranty coverage, fleet servicing, and seasonal maintenance strictly using the provided context chunks.",
            agent_tone: "Technical & Concise",
            temperature: 0.2,
            max_context_chunks: 4,
            similarity_threshold: 0.72,
        },
    },
];

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
    PRESET_TENANTS,
    PRESET_TENANT_IDS,
    PUBLIC_PRESET_FIXTURES,
    isPresetTenantId,
    getPresetTenantById,
    isValidTenantId,
    isValidDocId,
    slugifyTenantId,
    buildDefaultSystemPrompt,
};

