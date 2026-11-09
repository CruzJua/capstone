/**
 * What a visitor reads when something goes wrong.
 *
 * The gateway's error codes are stable; its message text is for developers and is never shown as is.
 * Every message here is specific enough to act on and says nothing about servers, databases or
 * models. `retryable` decides whether the widget offers a Retry button: resending the same text
 * only helps when the problem can go away by itself.
 */

const SERVICE_UNAVAILABLE = "The support assistant is temporarily unavailable. Please try again shortly.";
const GENERIC = "Something went wrong. Please try again.";

const BY_CODE = {
    network_error: {
        message: "We couldn't reach the support service. Please check your connection and try again.",
        retryable: true,
    },
    timeout: { message: "The assistant took too long to respond. Please try again.", retryable: true },
    stream_interrupted: {
        message: "The connection was interrupted before the reply finished. Please try again.",
        retryable: true,
    },
    generation_failed: { message: "The assistant ran into a problem. Please try again.", retryable: true },
    stream_error: { message: "The assistant ran into a problem. Please try again.", retryable: true },
    service_unavailable: { message: SERVICE_UNAVAILABLE, retryable: true },
    message_too_long: {
        message: "That message is too long. Please shorten it (2000 characters at most) and send it again.",
        retryable: false,
    },
    invalid_request: { message: "That message couldn't be sent. Please edit it and try again.", retryable: false },
    unknown_tenant: { message: "The support chat isn't available on this site.", retryable: false },
    origin_not_allowed: { message: "The support chat isn't available on this site.", retryable: false },
};

function describe(error) {
    const code = error && error.code;
    if (code === "rate_limited") {
        const seconds = Number(error.retryAfterSec);
        const wait =
            Number.isFinite(seconds) && seconds > 0
                ? seconds > 90
                    ? `${Math.ceil(seconds / 60)} minutes`
                    : `${Math.ceil(seconds)} seconds`
                : "a moment";
        return { message: `You're sending messages too quickly. Please wait ${wait} and try again.`, retryable: true };
    }
    if (code && BY_CODE[code]) {
        return BY_CODE[code];
    }
    const status = Number(error && error.status);
    if (status >= 500) {
        return { message: SERVICE_UNAVAILABLE, retryable: true };
    }
    if (status >= 400) {
        return { message: GENERIC, retryable: false };
    }
    return { message: GENERIC, retryable: true };
}

/** Safe, visitor-facing text for any failure. */
export function visitorMessage(error) {
    return describe(error).message;
}

/** Whether resending the same message can succeed. */
export function isRetryable(error) {
    return describe(error).retryable;
}
