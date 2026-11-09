const { test, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { setChatBackend } = require("../src/chat/backend");
const { resetChatState } = require("../src/routes/chat");
const { issueToken, readToken, TTL_MS } = require("../src/chat/followUp");
const SESSION = "session-0123456789abcdef";
let server, url, tickets, failSave, calls;
const savedEnv = { ...process.env };
beforeEach(async () => {
    process.env.APP_MODE = "standard";
    process.env.CHAT_RATE_LIMIT_PER_IP = "1000";
    process.env.CHAT_RATE_LIMIT_PER_SESSION = "1000";
    tickets = []; failSave = false; calls = [];
    resetChatState();
    setDatabaseAdapter({ collection: (name) => ({
        findOne: async (query) => name === "businesses" ?
            ["tenant_a", "tenant_b"].includes(query.tenant_id) ? { tenant_id: query.tenant_id, contact_email: "support@example.com", contact_phone: "+1 202 555 0123", widget_config: { allowed_origins: ["https://shop.example"] } } : null :
            tickets.find(t => t.tenant_id === query.tenant_id && t.ticket_id === query.ticket_id),
        updateOne: async (filter, update, options) => {
            if (failSave) throw new Error("mock database unavailable");
            let ticket = tickets.find(t => t.tenant_id === filter.tenant_id && t.ticket_id === filter.ticket_id);
            if (options.upsert) {
                if (!ticket) { ticket = structuredClone(update.$setOnInsert); tickets.push(ticket); }
                Object.assign(ticket, structuredClone(update.$set));
                return { acknowledged: true, matchedCount: 1 };
            }
            if (!ticket || ticket.customer_contact.email) return { acknowledged: true, matchedCount: 0 };
            Object.assign(ticket, structuredClone(update.$set));
            calls.push(update);
            return { acknowledged: true, matchedCount: 1 };
        },
    }) });
    setChatBackend({ chat(payload) { calls.push(payload); return (async function* () {
        yield { type: "token", text: "Please request email follow-up." };
        yield { type: "done", action: "escalate" };
    })(); } });
    server = createApp().listen(0); await new Promise(r => server.once("listening", r));
    url = `http://127.0.0.1:${server.address().port}`;
});
afterEach(async () => {
    server.closeAllConnections(); await new Promise(r => server.close(r));
    resetDatabaseAdapter(); setChatBackend(null);
    for (const key of Object.keys(process.env)) if (!(key in savedEnv)) delete process.env[key];
    Object.assign(process.env, savedEnv);
});
const post = (path, body, origin = "https://shop.example") => fetch(url + path, { method: "POST", headers: { "Content-Type": "application/json", Origin: origin }, body: JSON.stringify(body) });
async function ask() {
    return (await post("/api/chat", { tenant_id: "tenant_a", session_id: SESSION, message: "Need help" })).json();
}
const form = token => ({ tenant_id: "tenant_a", session_id: SESSION, follow_up_token: token, name: "Visitor", email: "visitor@example.com" });
test("persisted escalation accepts contact, preserves transcript/admin notes, and retries idempotently", async () => {
    const body = await ask();
    assert.deepEqual(calls[0].business_contact, { email: "support@example.com", phone: "+1 202 555 0123" });
    assert.equal(body.follow_up.contact_phone, "+1 202 555 0123");
    tickets[0].admin_notes = "Keep this";
    const messages = structuredClone(tickets[0].messages);
    for (let i = 0; i < 2; i++) {
        const response = await post("/api/chat/contact", form(body.follow_up.token));
        assert.equal(response.status, 200); assert.deepEqual(await response.json(), { status: "saved" });
    }
    assert.equal(tickets.length, 1);
    assert.deepEqual(tickets[0].customer_contact, { name: "Visitor", email: "visitor@example.com" });
    assert.deepEqual(tickets[0].messages, messages); assert.equal(tickets[0].admin_notes, "Keep this");
    const changed = await post("/api/chat/contact", { ...form(body.follow_up.token), email: "different@example.com" });
    assert.equal(changed.status, 409);
});
test("tokens cannot be forged, expired, or replayed across tenant/session boundaries", async () => {
    const body = await ask();
    const token = body.follow_up.token;
    assert.equal(readToken(token, "tenant_b", SESSION), null);
    assert.equal(readToken(token, "tenant_a", "session-other-012345"), null);
    assert.equal(readToken(token, "tenant_a", SESSION, Date.now() + TTL_MS + 1000), null);
    assert.equal(readToken(token.slice(0, -8) + "abcdefgh", "tenant_a", SESSION), null);
    for (const fields of [{ follow_up_token: "forged" }, { tenant_id: "tenant_b" }, { session_id: "session-other-012345" }, { follow_up_token: issueToken("tenant_a", SESSION, tickets[0].ticket_id, Date.now() - TTL_MS - 100) }]) {
        assert.equal((await post("/api/chat/contact", { ...form(token), ...fields })).status, 403);
    }
    assert.equal(tickets[0].customer_contact.email, "");
});
test("contact endpoint enforces origin, validation, existing tenant and rate limit", async () => {
    const { follow_up } = await ask(); const payload = form(follow_up.token);
    assert.equal((await post("/api/chat/contact", payload, "https://evil.example")).status, 403);
    for (const email of ["bad", "a..b@example.com", "a@localhost", "a@example.com\r\nBcc: x@example.com", "a".repeat(255) + "@example.com"]) {
        assert.equal((await post("/api/chat/contact", { ...payload, email })).status, 400, email);
    }
    assert.equal((await post("/api/chat/contact", { ...payload, name: "x".repeat(101) })).status, 400);
    assert.equal((await post("/api/chat/contact", { ...payload, tenant_id: "unknown_tenant" })).status, 404);
    process.env.CHAT_RATE_LIMIT_PER_SESSION = "1"; resetChatState();
    assert.equal((await post("/api/chat/contact", payload)).status, 200);
    assert.equal((await post("/api/chat/contact", payload)).status, 429);
});
test("ticket-save failure omits follow-up and contact-save failure never confirms success", async () => {
    failSave = true;
    const failed = await ask();
    assert.equal(failed.follow_up, undefined);
    assert.match(failed.answer, /email follow-up form is temporarily unavailable/);
    const response = await fetch(url + "/api/chat", { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://shop.example", Accept: "text/event-stream" }, body: JSON.stringify({ tenant_id: "tenant_a", session_id: SESSION, message: "Again" }) });
    const events = (await response.text()).split("\n\n").filter(block => block.startsWith("event:")).map(block => ({ event: block.match(/^event: (.*)$/m)[1], data: JSON.parse(block.match(/^data: (.*)$/m)[1]) }));
    assert.match(events.filter(e => e.event === "token").map(e => e.data.text).join(""), /email follow-up form is temporarily unavailable/);
    assert.deepEqual(events.at(-1), { event: "done", data: {} });
    assert.match(calls[1].history.at(-1).content, /email follow-up form is temporarily unavailable/);
    failSave = false; const body = await ask(); failSave = true;
    assert.equal((await post("/api/chat/contact", form(body.follow_up.token))).status, 503);
});
