import { test } from "node:test";
import assert from "node:assert/strict";
import { originsToText, parseOriginsInput, widgetConfigPayload } from "../src/lib/origins.mjs";

test("parses one origin per line, tolerating commas, spaces, blank lines and trailing slashes", () => {
    assert.deepEqual(
        parseOriginsInput(" https://shop.example.com/ \n\nhttps://www.example.org, http://localhost:8080  "),
        ["https://shop.example.com", "https://www.example.org", "http://localhost:8080"]
    );
});

test("removes duplicates and handles empty input", () => {
    assert.deepEqual(parseOriginsInput("https://a.example.com\nhttps://a.example.com/"), ["https://a.example.com"]);
    assert.deepEqual(parseOriginsInput(""), []);
    assert.deepEqual(parseOriginsInput(undefined), []);
});

test("does not try to validate: wildcards pass through so the gateway can reject them with its own message", () => {
    assert.deepEqual(parseOriginsInput("https://*.example.com"), ["https://*.example.com"]);
});

test("round trips through the textarea", () => {
    const origins = ["https://shop.example.com", "https://www.example.org"];
    assert.deepEqual(parseOriginsInput(originsToText(origins)), origins);
    assert.equal(originsToText(undefined), "");
});

test("the payload is omitted unless the field changed, so an untouched empty box never means 'allow nothing'", () => {
    assert.equal(widgetConfigPayload("", ""), undefined);
    assert.equal(widgetConfigPayload("https://a.example.com/", "https://a.example.com"), undefined);
    assert.deepEqual(widgetConfigPayload("https://a.example.com", ""), { allowed_origins: ["https://a.example.com"] });
    // Clearing a saved list is a real change and is sent as an empty array.
    assert.deepEqual(widgetConfigPayload("", "https://a.example.com"), { allowed_origins: [] });
});
