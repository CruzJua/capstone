/** Scoped, expiring capabilities for an already-persisted conversation ticket. */
const crypto = require("crypto");
const isEmail = require("validator/lib/isEmail");
const { parsePhoneNumberFromString } = require("libphonenumber-js/max");
const { getTicketLogsCollection } = require("../db/mongo");
const { withTimeout, SAVE_TIMEOUT_MS } = require("./escalation");
const processSecret = crypto.randomBytes(32);
const TTL_MS = 24 * 60 * 60 * 1000;
function key() {
    return crypto.createHash("sha256").update(process.env.CHAT_FOLLOW_UP_SECRET || processSecret).digest();
}
function issueToken(tenantId, sessionId, ticketId, now = Date.now()) {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv("aes-256-gcm", key(), iv);
    const body = Buffer.concat([cipher.update(JSON.stringify({ tenantId, sessionId, ticketId, expires: now + TTL_MS }), "utf8"), cipher.final()]);
    return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}
function readToken(token, tenantId, sessionId, now = Date.now()) {
    try {
        if (typeof token !== "string" || token.length > 2048 || !/^[\w-]+$/.test(token)) return null;
        const bytes = Buffer.from(token, "base64url");
        const decipher = crypto.createDecipheriv("aes-256-gcm", key(), bytes.subarray(0, 12));
        decipher.setAuthTag(bytes.subarray(12, 28));
        const claims = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString("utf8"));
        return claims.tenantId === tenantId && claims.sessionId === sessionId && claims.expires > now && typeof claims.ticketId === "string" ? claims : null;
    } catch { return null; }
}
function validEmail(value) {
    return typeof value === "string" && value.length <= 254 && isEmail(value, { allow_utf8_local_part: false });
}
function normalizePhone(value) {
    if (typeof value !== "string" || value.length > 50) return null;
    if (!value.trim()) return "";
    const parts = /^(\+?[0-9 ().-]+?)(?:\s*[xX#]\s*(\d+))?$/.exec(value.trim());
    if (!parts || (parts[2] && parts[2].length > 10)) return null;
    const phone = parsePhoneNumberFromString(parts[1], { extract: false });
    if (!phone?.isValid()) return null;
    return phone.number + (parts[2] ? ` x${parts[2]}` : "");
}
function validPhone(value) {
    return normalizePhone(value) !== null;
}
function businessContact(tenant) {
    const email = typeof tenant.contact_email === "string" ? tenant.contact_email.trim() : "";
    const phone = typeof tenant.contact_phone === "string" ? tenant.contact_phone.trim() : "";
    return { email: validEmail(email) ? email : "", phone: validPhone(phone) ? phone : "" };
}
async function saveContact(claims, contact) {
    return withTimeout((async () => {
        const collection = await getTicketLogsCollection();
        // First submission wins; concurrent/repeated requests cannot overwrite a visitor's details.
        const result = await collection.updateOne(
            { tenant_id: claims.tenantId, ticket_id: claims.ticketId, $or: [
                { "customer_contact.email": "" }, { customer_contact: { $exists: false } },
            ] },
            { $set: { customer_contact: contact, updated_at: new Date().toISOString() } },
            { upsert: false, maxTimeMS: SAVE_TIMEOUT_MS }
        );
        if (!result || result.acknowledged !== true) throw new Error("Contact save was not acknowledged.");
        if (result.matchedCount === 1) return true;
        const existing = await collection.findOne({ tenant_id: claims.tenantId, ticket_id: claims.ticketId }, { projection: { customer_contact: 1 } });
        return Boolean(existing && existing.customer_contact && existing.customer_contact.email === contact.email && existing.customer_contact.name === contact.name);
    })(), SAVE_TIMEOUT_MS);
}
module.exports = { issueToken, readToken, validEmail, validPhone, normalizePhone, businessContact, saveContact, TTL_MS };
