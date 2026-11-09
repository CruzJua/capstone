import test from "node:test";
import assert from "node:assert/strict";
import { profilePayload, readAssistantPolicy } from "../src/lib/profile.mjs";

const form = {
    name: "Example", industry: "Retail", contact_email: "help@example.com",
    contact_phone: "+1 202 555 0123", team_name: "Support", allowed_origins: "",
    tenant_id: "example", assistant_policy: { version: "1", system_prompt: "Core rules" },
    agent_config: { system_prompt: "Business details", agent_tone: "Warm", temperature: "0.2",
        max_context_chunks: "4", similarity_threshold: "0.7", assistant_policy: "Injected" },
};

test("save keeps business customization and public phone but excludes server-owned policy", () => {
    const payload = profilePayload(form, form);
    assert.equal(payload.contact_phone, "+12025550123");
    assert.equal(payload.agent_config.system_prompt, "Business details");
    assert.equal(payload.agent_config.temperature, 0.2);
    assert.equal("assistant_policy" in payload, false);
    assert.equal("assistant_policy" in payload.agent_config, false);
    assert.equal("tenant_id" in payload, false);
    assert.equal("widget_config" in payload, false);
});

test("phone can be removed without changing untouched origin fallback", () => {
    const payload = profilePayload({ ...form, contact_phone: "" }, form);
    assert.equal(payload.contact_phone, "");
    assert.equal("widget_config" in payload, false);
});

test("policy display uses the actual gateway policy and handles older gateways", () => {
    assert.deepEqual(readAssistantPolicy(form), form.assistant_policy);
    assert.equal(readAssistantPolicy({}), null);
    assert.equal(readAssistantPolicy({ assistant_policy: { version: "1" } }), null);
});
