import test from "node:test";
import assert from "node:assert/strict";
import { normalizeContactPhone, splitContactPhone, validateContactFields } from "../src/lib/contactValidation.mjs";
import { profilePayload } from "../src/lib/profile.mjs";

const valid = { contact_email: "support@example.com", contact_phone: "" };

test("email validation rejects malformed addresses and header injection", () => {
    for (const email of ["", "no-at-sign", "a..b@example.com", "a@localhost", "a@example.com\r\nBcc: x@example.com", "x".repeat(255) + "@example.com"]) {
        assert.ok(validateContactFields({ ...valid, contact_email: email }).contact_email, email);
    }
    assert.deepEqual(validateContactFields({ ...valid, contact_email: " support+sales@example.co.uk " }), {});
});

test("international numbers are validated by country rules, normalized, and retain extensions", () => {
    assert.equal(normalizeContactPhone("+1 (202) 555-0123"), "+12025550123");
    assert.equal(normalizeContactPhone("+44 20 7946 0018", "123"), "+442079460018 x123");
    assert.deepEqual(splitContactPhone("+44 20 7946 0018 #123"), { number: "+44 20 7946 0018", extension: "123" });
    for (const phone of ["123", "2025550123", "+15551234567", "+1202", "Call +12025550123", "javascript:alert(1)"]) {
        assert.equal(normalizeContactPhone(phone), null, phone);
    }
    assert.equal(normalizeContactPhone("+12025550123", "12x"), null);
    assert.equal(normalizeContactPhone("+12025550123", "1".repeat(11)), null);
});

test("optional phone can be cleared but extension alone cannot be saved", () => {
    assert.deepEqual(validateContactFields(valid), {});
    assert.equal(normalizeContactPhone(""), "");
    assert.ok(validateContactFields({ ...valid, contact_phone_extension: "123" }).contact_phone);
});

test("save rejects invalid contact even when caller bypasses native form validation", () => {
    assert.throws(() => profilePayload({ ...valid, contact_email: "bad" }, {}), /valid email/);
    assert.throws(() => profilePayload({ ...valid, contact_phone: "123" }, {}), /valid phone/);
});
