/**
 * In-memory sliding-window rate limiter with a bounded number of tracked keys.
 * Limits are passed per call so they can come from environment variables read at request time.
 * State is per process; run a shared store in front of multiple gateway replicas.
 */
class SlidingWindowLimiter {
    constructor({ maxKeys = 10000 } = {}) {
        this.maxKeys = maxKeys;
        this.hits = new Map();
    }

    /** Records one hit for `key`. Returns { allowed, retryAfterSec }. */
    hit(key, limit, windowMs, now = Date.now()) {
        const windowStart = now - windowMs;
        const recent = (this.hits.get(key) || []).filter((timestamp) => timestamp > windowStart);

        if (recent.length >= limit) {
            this.hits.set(key, recent);
            const retryAfterMs = recent[0] + windowMs - now;
            return { allowed: false, retryAfterSec: Math.max(1, Math.ceil(retryAfterMs / 1000)) };
        }

        recent.push(now);
        if (!this.hits.has(key) && this.hits.size >= this.maxKeys) {
            this.evict(windowStart);
        }
        this.hits.set(key, recent);
        return { allowed: true, retryAfterSec: 0 };
    }

    evict(windowStart) {
        for (const [key, timestamps] of this.hits) {
            if (timestamps.length === 0 || timestamps[timestamps.length - 1] <= windowStart) {
                this.hits.delete(key);
            }
        }
        if (this.hits.size >= this.maxKeys) {
            const oldestKey = this.hits.keys().next().value;
            if (oldestKey !== undefined) this.hits.delete(oldestKey);
        }
    }

    reset() {
        this.hits.clear();
    }
}

module.exports = { SlidingWindowLimiter };
