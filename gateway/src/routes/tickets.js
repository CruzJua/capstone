const express = require("express");
const { getTicketLogsCollection } = require("../db/mongo");
const { authorizeTenantAccess } = require("../middleware/auth");

const router = express.Router();

const VALID_STATUSES = new Set(["resolved", "pending_review", "flagged"]);
const VALID_ESCALATION_REASONS = new Set([
    "none",
    "docs_require_human",
    "not_in_docs",
]);
const TICKET_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}$/;

function normalizeMessages(rawMessages) {
    if (!Array.isArray(rawMessages)) return [];
    const nowIso = new Date().toISOString();
    return rawMessages
        .filter(
            (msg) =>
                msg && typeof msg.content === "string" && msg.content.trim()
        )
        .map((msg) => ({
            role: String(msg.role || "customer")
                .trim()
                .toLowerCase(),
            content: msg.content.trim(),
            timestamp: msg.timestamp || nowIso,
        }));
}

/**
 * GET /api/tenants/:tenantId/tickets
 * Returns tickets filtered by session-authorized tenant_id and optional status / search query params.
 */
router.get("/tenants/:tenantId/tickets", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const statusFilter = (req.query.status || "").trim().toLowerCase();
        const searchQuery = (req.query.search || "").trim();

        const query = { tenant_id: authorizedTenantId };
        if (statusFilter && statusFilter !== "all") {
            if (!VALID_STATUSES.has(statusFilter)) {
                return res.status(400).json({
                    error: `Invalid status filter '${statusFilter}'. Allowed: resolved, pending_review, flagged.`,
                });
            }
            query.status = statusFilter;
        }

        if (searchQuery) {
            const escaped = searchQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            query.$or = [
                { ticket_id: { $regex: escaped, $options: "i" } },
                { question: { $regex: escaped, $options: "i" } },
                { answer: { $regex: escaped, $options: "i" } },
                { rationale: { $regex: escaped, $options: "i" } },
                { ticket_summary: { $regex: escaped, $options: "i" } },
                { "customer_contact.email": { $regex: escaped, $options: "i" } },
                { "customer_contact.name": { $regex: escaped, $options: "i" } },
                { "messages.content": { $regex: escaped, $options: "i" } },
            ];
        }

        const ticketLogs = await getTicketLogsCollection();
        const tickets = await ticketLogs
            .find(query, { projection: { _id: 0 } })
            .sort({ created_at: -1, ticket_id: 1 })
            .toArray();

        return res.json(tickets);
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/tickets] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to fetch tenant tickets.",
        });
    }
});

/**
 * POST /api/tickets (and POST /api/tenants/:tenantId/tickets)
 * Creates a new ticket log entry scoped to the session-authorized tenant.
 */
async function createTicketHandler(req, res) {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId || null
        );
        if (!authorizedTenantId) return;

        const body = req.body || {};
        const nowIso = new Date().toISOString();
        const normalizedMessages = normalizeMessages(body.messages);
        const lastCustomerTurn = [...normalizedMessages]
            .reverse()
            .find((m) => m.role === "customer" || m.role === "user");
        const lastAgentTurn = [...normalizedMessages]
            .reverse()
            .find((m) => m.role === "agent" || m.role === "assistant");

        const question = (
            body.question ||
            (lastCustomerTurn ? lastCustomerTurn.content : "")
        ).trim();
        const answer = (
            body.answer ||
            (lastAgentTurn ? lastAgentTurn.content : "")
        ).trim();

        if (!question) {
            return res.status(400).json({
                error: "question (or at least one customer message) is required.",
            });
        }

        const prefix =
            authorizedTenantId
                .split("_")
                .map((part) => part[0] || "")
                .join("")
                .toUpperCase() || "TKT";
        const customTicketId = (body.ticket_id || "").trim();
        if (customTicketId && !TICKET_ID_PATTERN.test(customTicketId)) {
            return res.status(400).json({
                error: "Invalid ticket_id format.",
            });
        }
        const ticketId =
            customTicketId ||
            `TKT-${prefix}-${Math.floor(1000 + Math.random() * 9000)}`;

        const rawStatus = String(body.status || "pending_review")
            .trim()
            .toLowerCase();
        const status = VALID_STATUSES.has(rawStatus)
            ? rawStatus
            : "pending_review";

        const rawEscalation = String(body.escalation_reason || "none")
            .trim()
            .toLowerCase();
        const escalationReason = VALID_ESCALATION_REASONS.has(rawEscalation)
            ? rawEscalation
            : "none";

        const contact = body.customer_contact || {};
        const customerContact = {
            name: typeof contact.name === "string" ? contact.name.trim() : "",
            email:
                typeof contact.email === "string" ? contact.email.trim() : "",
        };

        const finalMessages =
            normalizedMessages.length > 0
                ? normalizedMessages
                : [
                      {
                          role: "customer",
                          content: question,
                          timestamp: nowIso,
                      },
                      ...(answer
                          ? [
                                {
                                    role: "agent",
                                    content: answer,
                                    timestamp: nowIso,
                                },
                            ]
                          : []),
                  ];

        const newTicket = {
            ticket_id: ticketId,
            tenant_id: authorizedTenantId,
            question,
            answer,
            rationale:
                typeof body.rationale === "string" ? body.rationale.trim() : "",
            similarity_score: Number(body.similarity_score ?? 0),
            retrieved_chunks: Array.isArray(body.retrieved_chunks)
                ? body.retrieved_chunks
                : [],
            status,
            escalation_reason: escalationReason,
            ticket_summary:
                typeof body.ticket_summary === "string"
                    ? body.ticket_summary.trim()
                    : "",
            customer_contact: customerContact,
            messages: finalMessages,
            admin_notes:
                typeof body.admin_notes === "string"
                    ? body.admin_notes.trim()
                    : "",
            created_at: body.created_at || nowIso,
            updated_at: nowIso,
        };

        const ticketLogs = await getTicketLogsCollection();
        await ticketLogs.insertOne(newTicket);
        const { _id, ...cleanTicket } = newTicket;

        return res.status(201).json(cleanTicket);
    } catch (error) {
        console.error("[POST /api/tickets] Error:", error.message);
        return res.status(500).json({
            error: "Failed to create ticket log.",
        });
    }
}

router.post("/tickets", createTicketHandler);
router.post("/tenants/:tenantId/tickets", createTicketHandler);

/**
 * PATCH /api/tickets/:ticketId
 * Updates status, admin_notes, customer_contact, escalation_reason,
 * ticket_summary, or messages for a ticket scoped strictly by BOTH ticket_id
 * and the session-authorized tenant_id.
 */
router.patch("/tickets/:ticketId", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(req, res);
        if (!authorizedTenantId) return;

        const { ticketId } = req.params;
        if (!ticketId || !TICKET_ID_PATTERN.test(ticketId)) {
            return res.status(400).json({
                error: "Invalid ticket identifier.",
            });
        }

        const body = req.body || {};
        const setFields = {};
        const pushFields = {};
        const nowIso = new Date().toISOString();

        if (body.status !== undefined) {
            const normalizedStatus = String(body.status).trim().toLowerCase();
            if (!VALID_STATUSES.has(normalizedStatus)) {
                return res.status(400).json({
                    error: "status must be one of: resolved, pending_review, flagged.",
                });
            }
            setFields.status = normalizedStatus;
        }

        if (body.admin_notes !== undefined) {
            if (typeof body.admin_notes !== "string") {
                return res.status(400).json({
                    error: "admin_notes must be a string.",
                });
            }
            setFields.admin_notes = body.admin_notes.trim();
        }

        if (body.customer_contact !== undefined) {
            if (
                typeof body.customer_contact !== "object" ||
                body.customer_contact === null
            ) {
                return res.status(400).json({
                    error: "customer_contact must be an object with name and/or email.",
                });
            }
            setFields.customer_contact = {
                name:
                    typeof body.customer_contact.name === "string"
                        ? body.customer_contact.name.trim()
                        : "",
                email:
                    typeof body.customer_contact.email === "string"
                        ? body.customer_contact.email.trim()
                        : "",
            };
        }

        if (body.escalation_reason !== undefined) {
            const normalizedReason = String(body.escalation_reason)
                .trim()
                .toLowerCase();
            if (!VALID_ESCALATION_REASONS.has(normalizedReason)) {
                return res.status(400).json({
                    error: "escalation_reason must be one of: none, docs_require_human, not_in_docs.",
                });
            }
            setFields.escalation_reason = normalizedReason;
        }

        if (body.ticket_summary !== undefined) {
            if (typeof body.ticket_summary !== "string") {
                return res.status(400).json({
                    error: "ticket_summary must be a string.",
                });
            }
            setFields.ticket_summary = body.ticket_summary.trim();
        }

        if (body.messages !== undefined) {
            if (!Array.isArray(body.messages)) {
                return res.status(400).json({
                    error: "messages must be an array of { role, content, timestamp }.",
                });
            }
            setFields.messages = normalizeMessages(body.messages);
        }

        if (
            body.append_message &&
            typeof body.append_message === "object" &&
            typeof body.append_message.content === "string" &&
            body.append_message.content.trim() &&
            setFields.messages === undefined
        ) {
            pushFields.messages = {
                role: String(body.append_message.role || "customer")
                    .trim()
                    .toLowerCase(),
                content: body.append_message.content.trim(),
                timestamp: body.append_message.timestamp || nowIso,
            };
        }

        if (
            Object.keys(setFields).length === 0 &&
            Object.keys(pushFields).length === 0
        ) {
            return res.status(400).json({
                error: "Provide status, admin_notes, customer_contact, escalation_reason, ticket_summary, or messages to update.",
            });
        }

        setFields.updated_at = nowIso;

        const updateDoc = { $set: setFields };
        if (Object.keys(pushFields).length > 0) {
            updateDoc.$push = pushFields;
        }

        const ticketLogs = await getTicketLogsCollection();
        const updatedTicket = await ticketLogs.findOneAndUpdate(
            {
                ticket_id: ticketId,
                tenant_id: authorizedTenantId,
            },
            updateDoc,
            { returnDocument: "after", projection: { _id: 0 } }
        );

        if (!updatedTicket) {
            return res.status(404).json({
                error: `Ticket '${ticketId}' not found.`,
            });
        }

        return res.json(updatedTicket);
    } catch (error) {
        console.error("[PATCH /api/tickets/:ticketId] Error:", error.message);
        return res.status(500).json({
            error: "Failed to update ticket.",
        });
    }
});

module.exports = router;
