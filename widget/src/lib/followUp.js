/** Parse only number punctuation and an optional trailing extension; never URI input. */
function publicPhone(value) {
    if (typeof value !== "string" || value.length > 50) return undefined;
    const display = value.trim();
    const parts = /^(\+?[0-9 ().-]+?)(?:\s*[xX#]\s*(\d+))?$/.exec(display);
    if (!parts || !/\d/.test(parts[1])) return undefined;
    const number = parts[1].replace(/[^+0-9]/g, "");
    return { display, uri: `tel:${number}${parts[2] ? `;ext=${parts[2]}` : ""}` };
}

/** Validate public metadata and build links without accepting HTML or URI schemes. */
export function normalizeFollowUp(value) {
    if (!value || value.available !== true || typeof value.token !== "string" || !value.token.trim()) return undefined;
    const result = { available: true, token: value.token };
    if (typeof value.contact_email === "string" && /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(value.contact_email)) {
        result.contactEmail = value.contact_email;
    }
    const phone = publicPhone(value.contact_phone);
    if (phone) result.contactPhone = phone.display;
    return result;
}

export function contactLinks(followUp) {
    // Revalidate at the point where links are rendered, even for external callers.
    const safe = normalizeFollowUp({ available: true, token: followUp?.token,
        contact_email: followUp?.contactEmail, contact_phone: followUp?.contactPhone });
    return {
        email: safe?.contactEmail ? `mailto:${encodeURIComponent(safe.contactEmail)}` : undefined,
        phone: publicPhone(safe?.contactPhone)?.uri,
    };
}

/** One epoch for stream and form callbacks. Reset invalidates even abort-ignoring clients. */
export function createConversationScope() {
    let epoch = 0;
    const controllers = new Set();
    return {
        begin() {
            const current = epoch;
            const controller = new AbortController();
            controllers.add(controller);
            return { signal: controller.signal, abort: () => controller.abort(),
                isCurrent: () => current === epoch,
                finish: () => controllers.delete(controller) };
        },
        reset() {
            epoch += 1;
            for (const controller of controllers) controller.abort();
            controllers.clear();
        },
    };
}
