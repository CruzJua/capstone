import assert from "node:assert/strict";
import test from "node:test";
import { normalizeFollowUp, contactLinks, createConversationScope } from "../src/lib/followUp.js";

test("follow-up is shown only for an explicit availability flag and capability", () => {
    for (const value of [null, {}, { available: true }, { available: true, token: " " },
        { available: false, token: "a" }, { available: "true", token: "a" }]) {
        assert.equal(normalizeFollowUp(value), undefined);
    }
    assert.deepEqual(normalizeFollowUp({ available: true, token: "a", internal: "secret" }), { available: true, token: "a" });
});

test("public links permit contact data and reject script or mail-header injection", () => {
    const safe = normalizeFollowUp({ available: true, token: "a", contact_email: "support@example.test", contact_phone: "+1 (555) 123-4567" });
    assert.deepEqual(contactLinks(safe), { email: "mailto:support%40example.test", phone: "tel:+15551234567" });
    for (const value of ["javascript:alert(1)", 'x\" onclick="alert(1)', "x@example.test\nBcc:bad@example.test"]) {
        assert.deepEqual(contactLinks({ token: "a", contactEmail: value, contactPhone: value }), { email: undefined, phone: undefined });
    }
});

test("new conversation aborts stream and contact submission and ignores late callbacks", async () => {
    const scope = createConversationScope();
    const oldStream = scope.begin();
    const oldSubmit = scope.begin();
    let display = "old";
    const delayed = Promise.resolve().then(() => { if (oldSubmit.isCurrent()) display = "saved old contact"; });
    scope.reset();
    display = "new greeting";
    const fresh = scope.begin();
    await delayed;
    assert.equal(oldStream.signal.aborted, true);
    assert.equal(oldSubmit.signal.aborted, true);
    assert.equal(oldStream.isCurrent(), false);
    assert.equal(display, "new greeting");
    oldSubmit.finish();
    assert.equal(fresh.isCurrent(), true);
    assert.equal(fresh.signal.aborted, false);
    scope.reset();
    assert.equal(fresh.signal.aborted, true);
});

test("stopping one request does not invalidate or abort another request", () => {
    const scope = createConversationScope();
    const stream = scope.begin();
    const contact = scope.begin();
    stream.abort();
    stream.finish();
    assert.equal(stream.signal.aborted, true);
    assert.equal(contact.signal.aborted, false);
    assert.equal(contact.isCurrent(), true);
});


test("phone extensions retain public display and dial using a separate tel extension", () => {
    for (const marker of ["x", "X", "#"]) {
        const display = `+1 (555) 123-4567 ${marker} 123`;
        const metadata = normalizeFollowUp({ available: true, token: "a", contact_phone: display });
        assert.equal(metadata.contactPhone, display);
        assert.equal(contactLinks(metadata).phone, "tel:+15551234567;ext=123");
    }
    const short = normalizeFollowUp({ available: true, token: "a", contact_phone: "1234#567" });
    assert.equal(contactLinks(short).phone, "tel:1234;ext=567");
});

test("phone extensions cannot inject URI parameters or concatenate an extension into the main number", () => {
    for (const phone of ["+1 555 123 4567;ext=123", "+1 555 123 4567 x123;phone-context=evil",
        "+1 555 123 4567 x", "+1 555 123 4567 x123#456", "++1 555 123 4567", "x123",
        "1".repeat(51)]) {
        assert.equal(normalizeFollowUp({ available: true, token: "a", contact_phone: phone }).contactPhone, undefined);
        assert.equal(contactLinks({ token: "a", contactPhone: phone }).phone, undefined);
    }
    const max = normalizeFollowUp({ available: true, token: "a", contact_phone: "1".repeat(45) + " x123" });
    assert.equal(contactLinks(max).phone, `tel:${"1".repeat(45)};ext=123`);
});
