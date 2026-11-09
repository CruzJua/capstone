const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { createApp } = require("../src/server");
const { setDatabaseAdapter, resetDatabaseAdapter } = require("../src/db/mongo");
const { setChatBackend } = require("../src/chat/backend");
const { resetChatState } = require("../src/routes/chat");
const {
    buildEscalationTicket,
    buildEscalationTicketId,
    saveEscalationTicket,
} = require("../src/chat/escalation");

const SESSION = "session-0123456789abcdef";
const OTHER_SESSION = "session-fedcba9876543210";
const TICKET_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$/; // the dashboard's own ticket_id rule

function parseSse(text) {
    return text
        .split("\n\n")
        .filter((block) => block.trim() && !block.startsWith(":"))
        .map((block) => ({
            event: block.match(/^event: (.*)$/m)[1],
            data: JSON.parse(block.match(/^data: (.*)$/m)[1]),
        }));
}

const SOURCES = [
    { doc_id: "RETURNS", section: "Window", score: 0.83, text: "SECRET CHUNK TEXT" },
    { doc_id: "SHIPPING", section: "Times", score: 0.71 },
];

function backendFor({ sources = SOURCES, tokens = ["A person ", "will follow up."], done = { action: "escalate", confidence: 0.31, cited_sources: [] } } = {}) {
    return {
        calls: [],
        chat(payload) {
            this.calls.push(payload);
            return (async function* () {
                yield { type: "sources", sources };
                for (const text of tokens) yield { type: "token", text };
                if (done) yield { type: "done", ...done };
            })();
        },
    };
}

describe("human escalation tickets", () => {
    let server;
    let baseUrl;
    let tickets;
    let updateCalls;
    let saveDelayMs;
    let saveError;
    const savedEnv = { ...process.env };

    beforeEach(async () => {
        process.env.APP_MODE = "standard";
        process.env.MONGODB_DB_NAME = "escalation_test_db";
        delete process.env.MONGODB_TRAINING_DB_NAME;
        delete process.env.WIDGET_DEFAULT_ALLOWED_ORIGINS;
        process.env.CHAT_RATE_LIMIT_PER_IP = "1000";
        process.env.CHAT_RATE_LIMIT_PER_SESSION = "1000";
        process.env.CHAT_HEARTBEAT_MS = "60000";
        resetChatState();

        tickets = [];
        updateCalls = 0;
        saveDelayMs = 0;
        saveError = null;
        const businesses = [{ tenant_id: "tenant_a" }, { tenant_id: "tenant_b" }];

        setDatabaseAdapter({
            collection: (name) => ({
                findOne: async (query) =>
                    name === "businesses" && typeof query.tenant_id === "string"
                        ? structuredClone(businesses.find((b) => b.tenant_id === query.tenant_id) || null)
                        : null,
                // Faithful enough to MongoDB for an upsert: $set and $setOnInsert may not touch the same field.
                updateOne: async (filter, update, options = {}) => {
                    assert.equal(name, "ticket_logs", "the chat route may only write escalation tickets");
                    updateCalls += 1;
                    if (saveDelayMs) await new Promise((resolve) => setTimeout(resolve, saveDelayMs));
                    if (saveError) throw saveError;
                    const overlap = Object.keys(update.$set || {}).filter((key) => key in (update.$setOnInsert || {}));
                    assert.deepEqual(overlap, [], "$set and $setOnInsert must not overlap");
                    let doc = tickets.find((t) => t.tenant_id === filter.tenant_id && t.ticket_id === filter.ticket_id);
                    if (!doc) {
                        assert.ok(options.upsert, "an unmatched update must be an upsert");
                        doc = structuredClone(update.$setOnInsert || {});
                        tickets.push(doc);
                    }
                    Object.assign(doc, structuredClone(update.$set || {}));
                    return { acknowledged: true };
                },
            }),
        });

        server = createApp().listen(0);
        await new Promise((resolve) => server.once("listening", resolve));
        baseUrl = `http://127.0.0.1:${server.address().port}`;
    });

    afterEach(async () => {
        server.closeAllConnections?.();
        await new Promise((resolve) => server.close(resolve));
        setChatBackend(null);
        resetDatabaseAdapter();
        for (const key of Object.keys(process.env)) {
            if (!(key in savedEnv)) delete process.env[key];
        }
        Object.assign(process.env, savedEnv);
    });

    const ask = (message, { tenant = "tenant_a", session = SESSION, accept = "text/event-stream", signal } = {}) =>
        fetch(`${baseUrl}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: accept },
            body: JSON.stringify({ tenant_id: tenant, message, session_id: session }),
            signal,
        });

    describe("what the visitor sees", () => {
        test("an escalated stream exposes only a scoped follow-up capability", async () => {
            setChatBackend(backendFor());
            const text = await (await ask("I want a refund for a broken item")).text();
            const events = parseSse(text);
            assert.deepEqual(events.map((event) => event.event), ["token", "token", "done"]);
            assert.equal(events[2].data.follow_up.available, true);
            assert.equal(typeof events[2].data.follow_up.token, "string");
            for (const leaked of ["escalat", "action", "confidence", "ticket", "human", "sources", "RETURNS", "SECRET CHUNK", "review"]) {
                assert.ok(!text.toLowerCase().includes(leaked.toLowerCase()), `must not reveal '${leaked}'`);
            }
        });

        test("an escalated JSON reply exposes follow-up metadata", async () => {
            setChatBackend(backendFor());
            const body = await (await ask("refund please", { accept: "application/json" })).json();
            assert.deepEqual(Object.keys(body).sort(), ["answer", "follow_up", "session_id"]);
            assert.equal(body.answer, "A person will follow up.");
        });

        test("done waits until the escalation ticket is persisted", async () => {
            setChatBackend(backendFor());
            saveDelayMs = 400;
            const response = await ask("refund please");
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let seen = "";
            while (!seen.includes("event: done")) {
                const { value, done } = await reader.read();
                assert.ok(!done, "stream ended before done");
                seen += decoder.decode(value, { stream: true });
            }
            assert.equal(tickets.length, 1, "follow-up is available only after persistence");
            await reader.cancel().catch(() => {});
            for (let i = 0; i < 100 && tickets.length === 0; i += 1) await new Promise((r) => setTimeout(r, 20));
            assert.equal(tickets.length, 1, "the ticket is still saved after the visitor has disconnected");
        });
    });

    describe("the saved ticket", () => {
        test("is a pending_review ticket in the dashboard's schema with the full conversation", async () => {
            setChatBackend(backendFor());
            await (await ask("I want a refund for a broken item")).text();
            assert.equal(tickets.length, 1);
            const ticket = tickets[0];
            assert.match(ticket.ticket_id, /^TKT-CHAT-[0-9A-F]{12}$/);
            assert.match(ticket.ticket_id, TICKET_ID_PATTERN);
            assert.equal(ticket.tenant_id, "tenant_a");
            assert.equal(ticket.status, "pending_review");
            assert.equal(ticket.escalation_reason, "docs_require_human");
            assert.equal(ticket.question, "I want a refund for a broken item");
            assert.equal(ticket.answer, "A person will follow up.");
            assert.deepEqual(
                ticket.messages.map(({ role, content }) => ({ role, content })),
                [
                    { role: "customer", content: "I want a refund for a broken item" },
                    { role: "agent", content: "A person will follow up." },
                ]
            );
            for (const message of ticket.messages) assert.ok(!Number.isNaN(Date.parse(message.timestamp)));
            assert.deepEqual(ticket.customer_contact, { name: "", email: "" });
            assert.equal(ticket.admin_notes, "");
            assert.equal(ticket.channel, "widget");
            assert.equal(ticket.confidence, 0.31);
            assert.deepEqual(ticket.cited_sources, []);
            assert.match(ticket.ticket_summary, /confidence 0\.31/);
            assert.match(ticket.ticket_summary, /I want a refund/);
            assert.ok(!Number.isNaN(Date.parse(ticket.created_at)));
            assert.ok(!Number.isNaN(Date.parse(ticket.updated_at)));
        });

        test("gives the reviewer the retrieved documents (id, section, score) but never chunk text", async () => {
            setChatBackend(backendFor());
            await (await ask("refund please")).text();
            const ticket = tickets[0];
            assert.deepEqual(ticket.retrieved_chunks, [
                { doc_id: "RETURNS", section: "Window", score: 0.83 },
                { doc_id: "SHIPPING", section: "Times", score: 0.71 },
            ]);
            assert.equal(ticket.similarity_score, 0.83);
            assert.ok(!JSON.stringify(ticket).includes("SECRET CHUNK TEXT"));
        });

        test("records the model's cited sources for the reviewer", async () => {
            setChatBackend(backendFor({ done: { action: "escalate", confidence: 0.5, cited_sources: ["RETURNS", 42, "SHIPPING"] } }));
            await (await ask("refund please")).text();
            assert.deepEqual(tickets[0].cited_sources, ["RETURNS", "SHIPPING"]);
        });

        test("no relevant documents -> escalation_reason not_in_docs", async () => {
            setChatBackend(backendFor({ sources: [] }));
            await (await ask("what is the meaning of life")).text();
            assert.equal(tickets[0].escalation_reason, "not_in_docs");
            assert.deepEqual(tickets[0].retrieved_chunks, []);
            assert.equal(tickets[0].similarity_score, 0);
            assert.match(tickets[0].ticket_summary, /No relevant documentation/);
        });

        test("JSON mode saves the ticket too", async () => {
            setChatBackend(backendFor());
            await (await ask("refund please", { accept: "application/json" })).json();
            assert.equal(tickets.length, 1);
            assert.equal(tickets[0].status, "pending_review");
        });

        test("never stores the visitor's raw session id", async () => {
            setChatBackend(backendFor());
            await (await ask("refund please")).text();
            assert.ok(!JSON.stringify(tickets).includes(SESSION));
        });

        test("an escalation without reply text is still saved", async () => {
            setChatBackend(backendFor({ tokens: [] }));
            await (await ask("refund please")).text();
            assert.equal(tickets.length, 1);
            assert.match(tickets[0].answer, /escalated without a reply/);
        });
    });

    describe("when a ticket is NOT created", () => {
        test("ordinary answered questions", async () => {
            setChatBackend(backendFor({ done: { action: "answer", confidence: 0.9, cited_sources: ["RETURNS"] } }));
            await (await ask("what is the return window")).text();
            setChatBackend(backendFor({ done: {} }));
            await (await ask("and shipping?")).text();
            assert.equal(tickets.length, 0);
            assert.equal(updateCalls, 0, "nothing is written to the database for normal conversations");
        });

        test("a failed or interrupted reply", async () => {
            setChatBackend({
                chat: () =>
                    (async function* () {
                        yield { type: "sources", sources: SOURCES };
                        yield { type: "token", text: "Par" };
                        yield { type: "error", code: "generation_failed", message: "x" };
                    })(),
            });
            await (await ask("refund please")).text();
            setChatBackend({
                chat: () =>
                    (async function* () {
                        yield { type: "sources", sources: SOURCES };
                        yield { type: "token", text: "Par" };
                    })(),
            });
            await (await ask("refund please")).text();
            assert.equal(tickets.length, 0);
        });

        test("a visitor who disconnects before the reply finishes", async () => {
            setChatBackend({
                chat: (payload, { signal }) =>
                    (async function* () {
                        yield { type: "sources", sources: SOURCES };
                        yield { type: "token", text: "Hello " };
                        await new Promise((resolve) => signal.addEventListener("abort", resolve));
                    })(),
            });
            const controller = new AbortController();
            const response = await ask("refund please", { signal: controller.signal });
            const reader = response.body.getReader();
            await reader.read();
            controller.abort();
            await reader.cancel().catch(() => {});
            await new Promise((resolve) => setTimeout(resolve, 100));
            assert.equal(tickets.length, 0);
        });
    });

    describe("one ticket per conversation", () => {
        test("a second escalation in the same conversation updates the same ticket", async () => {
            setChatBackend(backendFor());
            await (await ask("first problem")).text();
            const firstCreated = tickets[0].created_at;
            await new Promise((resolve) => setTimeout(resolve, 5));
            await (await ask("second problem")).text();
            assert.equal(tickets.length, 1);
            assert.equal(tickets[0].created_at, firstCreated);
            assert.ok(tickets[0].updated_at >= firstCreated);
            assert.deepEqual(
                tickets[0].messages.map((m) => m.content),
                ["first problem", "A person will follow up.", "second problem", "A person will follow up."]
            );
            assert.equal(tickets[0].question, "second problem");
        });

        test("earlier answered turns are part of the transcript the reviewer sees", async () => {
            setChatBackend(backendFor({ done: { action: "answer", confidence: 0.9, cited_sources: [] }, tokens: ["Thirty days."] }));
            await (await ask("what is the return window")).text();
            setChatBackend(backendFor());
            await (await ask("my item arrived broken")).text();
            assert.equal(tickets.length, 1);
            assert.deepEqual(
                tickets[0].messages.map((m) => m.content),
                ["what is the return window", "Thirty days.", "my item arrived broken", "A person will follow up."]
            );
        });

        test("a new escalation re-opens a resolved ticket and keeps what an admin added", async () => {
            setChatBackend(backendFor());
            await (await ask("first problem")).text();
            Object.assign(tickets[0], {
                status: "resolved",
                admin_notes: "Called the customer",
                customer_contact: { name: "Pat", email: "pat@example.com" },
            });
            await (await ask("it happened again")).text();
            assert.equal(tickets.length, 1);
            assert.equal(tickets[0].status, "pending_review");
            assert.equal(tickets[0].admin_notes, "Called the customer");
            assert.deepEqual(tickets[0].customer_contact, { name: "Pat", email: "pat@example.com" });
        });

        test("different conversations get different tickets", async () => {
            setChatBackend(backendFor());
            await (await ask("problem one", { session: SESSION })).text();
            await (await ask("problem two", { session: OTHER_SESSION })).text();
            assert.equal(tickets.length, 2);
            assert.notEqual(tickets[0].ticket_id, tickets[1].ticket_id);
        });
    });

    describe("tenant isolation", () => {
        test("the same session id under two tenants produces two separate tickets with separate transcripts", async () => {
            setChatBackend(backendFor());
            await (await ask("tenant A private complaint", { tenant: "tenant_a" })).text();
            await (await ask("tenant B private complaint", { tenant: "tenant_b" })).text();
            assert.equal(tickets.length, 2);
            const byTenant = Object.fromEntries(tickets.map((t) => [t.tenant_id, t]));
            assert.notEqual(byTenant.tenant_a.ticket_id, byTenant.tenant_b.ticket_id);
            assert.ok(!JSON.stringify(byTenant.tenant_a).includes("tenant B private"));
            assert.ok(!JSON.stringify(byTenant.tenant_b).includes("tenant A private"));
        });

        test("the ticket is filed under the validated tenant, never one supplied separately", async () => {
            setChatBackend(backendFor());
            await (await ask("complaint", { tenant: "tenant_b" })).text();
            assert.equal(tickets[0].tenant_id, "tenant_b");
        });
    });

    describe("failure handling", () => {
        test("a failed ticket save never breaks the visitor's reply or their conversation", async () => {
            const backend = backendFor();
            setChatBackend(backend);
            saveError = new Error("database unavailable: secret-host");
            const originalError = console.error;
            const logged = [];
            console.error = (...args) => logged.push(args.join(" "));
            try {
                const events = parseSse(await (await ask("refund please")).text());
                assert.deepEqual(events.map((event) => event.event), ["token", "token", "token", "done"]);
                assert.match(events[2].data.text, /email follow-up form is temporarily unavailable/);
                assert.deepEqual(events[3].data, {});
                await (await ask("hello again")).text();
            } finally {
                console.error = originalError;
            }
            assert.equal(tickets.length, 0);
            assert.equal(backend.calls[1].history[0].content, "refund please");
            assert.match(backend.calls[1].history[1].content, /A person will follow up[.]\n\nThe email follow-up form is temporarily unavailable/);
            assert.ok(logged.some((line) => /Could not save escalation ticket/.test(line)));
            assert.ok(!logged.join(" ").includes("secret-host"), "driver error text must not be logged");
        });

        test("saveEscalationTicket gives up when the database hangs", async () => {
            setDatabaseAdapter({ collection: () => ({ updateOne: () => new Promise(() => {}) }) });
            const ticket = buildEscalationTicket({
                tenantId: "tenant_a",
                sessionId: SESSION,
                message: "q",
                answer: "a",
                done: { action: "escalate" },
                sources: [],
                transcript: [],
            });
            await assert.rejects(saveEscalationTicket(ticket, { timeoutMs: 30 }), /timed out/);
        });
    });

    describe("ticket construction", () => {
        const base = { tenantId: "tenant_a", sessionId: SESSION, message: "q", answer: "a", sources: [], transcript: [] };

        test("ids are deterministic, dashboard-valid, and differ by tenant and session", () => {
            const id = buildEscalationTicketId("tenant_a", SESSION);
            assert.equal(id, buildEscalationTicketId("tenant_a", SESSION));
            assert.match(id, TICKET_ID_PATTERN);
            assert.notEqual(id, buildEscalationTicketId("tenant_b", SESSION));
            assert.notEqual(id, buildEscalationTicketId("tenant_a", OTHER_SESSION));
        });

        test("odd model output is normalized instead of stored blindly", () => {
            const ticket = buildEscalationTicket({
                ...base,
                done: { action: "escalate", confidence: "high", cited_sources: "RETURNS" },
            });
            assert.equal(ticket.confidence, null);
            assert.deepEqual(ticket.cited_sources, []);
            assert.doesNotMatch(ticket.ticket_summary, /confidence/);
            const clamped = buildEscalationTicket({ ...base, done: { action: "escalate", confidence: 7 } });
            assert.equal(clamped.confidence, 1);
        });

        test("long questions are truncated in the digest but kept whole in the transcript", () => {
            const message = "x".repeat(1500);
            const ticket = buildEscalationTicket({ ...base, message, done: { action: "escalate" } });
            assert.ok(ticket.ticket_summary.length < 400);
            assert.equal(ticket.question, message);
            assert.equal(ticket.messages[0].content, message);
        });
    });
});
