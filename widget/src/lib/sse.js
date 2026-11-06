/**
 * Incremental parser for a `text/event-stream` body.
 *
 * Feed it decoded text chunks with `push()`; it calls `onEvent({ event, data })`
 * once per complete event. Chunk boundaries may fall anywhere, including in the
 * middle of a line or between "\r" and "\n".
 */
export function createSseParser(onEvent) {
    let buffer = "";
    let eventName = "message";
    let dataLines = [];

    function dispatch() {
        if (dataLines.length > 0) {
            onEvent({ event: eventName, data: dataLines.join("\n") });
        }
        eventName = "message";
        dataLines = [];
    }

    function handleLine(line) {
        if (line === "") {
            dispatch();
            return;
        }
        if (line.startsWith(":")) {
            return; // comment / heartbeat
        }
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let value = colon === -1 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) {
            value = value.slice(1);
        }
        if (field === "event") {
            eventName = value;
        } else if (field === "data") {
            dataLines.push(value);
        }
    }

    return {
        push(chunk) {
            buffer += chunk;
            let lineEnd;
            while ((lineEnd = buffer.search(/\r\n|\n|\r/)) !== -1) {
                const isCrlf = buffer.startsWith("\r\n", lineEnd);
                // A lone trailing "\r" may be the first half of "\r\n": wait for more input.
                if (!isCrlf && buffer[lineEnd] === "\r" && lineEnd === buffer.length - 1) {
                    return;
                }
                const line = buffer.slice(0, lineEnd);
                buffer = buffer.slice(lineEnd + (isCrlf ? 2 : 1));
                handleLine(line);
            }
        },
        /** Call when the stream ends; dispatches nothing that was not terminated by a blank line. */
        flush() {
            buffer = "";
            eventName = "message";
            dataLines = [];
        },
    };
}
