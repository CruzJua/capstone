import assert from "node:assert/strict";
import test from "node:test";
import { createSseParser } from "../src/lib/sse.js";

function collect() {
    const events = [];
    const parser = createSseParser((e) => events.push(e));
    return { events, parser };
}

test("parses a complete event", () => {
    const { events, parser } = collect();
    parser.push('event: token\ndata: {"text":"hi"}\n\n');
    assert.deepEqual(events, [{ event: "token", data: '{"text":"hi"}' }]);
});

test("handles chunks split mid-line and mid-event", () => {
    const { events, parser } = collect();
    const wire = 'event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {}\n\n';
    for (const ch of wire) {
        parser.push(ch);
    }
    assert.deepEqual(events.map((e) => e.event), ["token", "done"]);
});

test("handles CRLF, including a split between \\r and \\n", () => {
    const { events, parser } = collect();
    parser.push("event: token\r");
    parser.push("\ndata: x\r\n\r");
    parser.push("\n");
    assert.deepEqual(events, [{ event: "token", data: "x" }]);
});

test("joins multi-line data and defaults the event name to message", () => {
    const { events, parser } = collect();
    parser.push("data: one\ndata: two\n\n");
    assert.deepEqual(events, [{ event: "message", data: "one\ntwo" }]);
});

test("ignores comment heartbeats and unknown fields", () => {
    const { events, parser } = collect();
    parser.push(": ping\nid: 5\nretry: 100\nevent: done\ndata: {}\n\n");
    assert.deepEqual(events, [{ event: "done", data: "{}" }]);
});

test("does not dispatch an unterminated event", () => {
    const { events, parser } = collect();
    parser.push("event: token\ndata: partial");
    parser.flush();
    assert.deepEqual(events, []);
});
