import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import { getSessionId, resetSessionMemory } from "../src/lib/session.js";

function fakeStorage() {
    const map = new Map();
    return {
        getItem: (k) => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => map.set(k, v),
    };
}

beforeEach(() => resetSessionMemory());

test("returns a stable id per tenant", () => {
    const storage = fakeStorage();
    const first = getSessionId("example_tenant", storage);
    assert.ok(first.length >= 8);
    assert.equal(getSessionId("example_tenant", storage), first);
});

test("different tenants get different ids", () => {
    const storage = fakeStorage();
    assert.notEqual(getSessionId("a", storage), getSessionId("b", storage));
});

test("works when storage throws (private mode / blocked storage)", () => {
    const broken = {
        getItem() {
            throw new Error("denied");
        },
        setItem() {
            throw new Error("denied");
        },
    };
    const id = getSessionId("example_tenant", broken);
    assert.equal(getSessionId("example_tenant", broken), id);
});

test("works with no storage at all", () => {
    const id = getSessionId("t", null);
    assert.equal(getSessionId("t", null), id);
});
