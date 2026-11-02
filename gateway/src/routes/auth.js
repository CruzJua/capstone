const express = require("express");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");
const {
    getBusinessesCollection,
    getAdminUsersCollection,
} = require("../db/mongo");
const { resolveRuntimeConfig, getAppMode } = require("../config/mode");
const {
    PUBLIC_PRESET_FIXTURES,
    isPresetTenantId,
    getPresetTenantById,
    isValidTenantId,
    slugifyTenantId,
    buildDefaultSystemPrompt,
} = require("../config/presets");
const {
    setSessionCookie,
    clearSessionCookie,
    getRawSessionTokenFromRequest,
    createSession,
    revokeSessionByRawToken,
} = require("../middleware/auth");

const publicAuthRouter = express.Router();
const protectedAuthRouter = express.Router();

// Precomputed bcrypt hash for constant-time comparison when user does not exist
const DUMMY_BCRYPT_HASH = bcrypt.hashSync(
    "dummy_unmatched_password_for_timing_safety",
    10
);

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Bounded rate limiter for login attempts
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 8;
const MAX_TRACKED_KEYS = 1000;
const loginAttempts = new Map();

function getRateLimitKey(req, email) {
    const ip =
        req.ip ||
        req.headers["x-forwarded-for"] ||
        req.socket?.remoteAddress ||
        "unknown";
    return `${ip}:${email || "unknown"}`;
}

function checkLoginRateLimit(key) {
    const now = Date.now();
    const record = loginAttempts.get(key);
    if (!record) return { allowed: true };

    if (now - record.firstAttemptAt > LOGIN_WINDOW_MS) {
        loginAttempts.delete(key);
        return { allowed: true };
    }

    if (record.count >= MAX_LOGIN_EMPTS_LIMIT()) {
        return { allowed: false };
    }

    return { allowed: true };
}

function MAX_LOGIN_EMPTS_LIMIT() {
    return Number(process.env.LOGIN_RATE_LIMIT_MAX) || MAX_LOGIN_ATTEMPTS;
}

function recordFailedLoginAttempt(key) {
    const now = Date.now();
    const existing = loginAttempts.get(key);
    if (!existing || now - existing.firstAttemptAt > LOGIN_WINDOW_MS) {
        if (loginAttempts.size >= MAX_TRACKED_KEYS) {
            const oldestKey = loginAttempts.keys().next().value;
            if (oldestKey) loginAttempts.delete(oldestKey);
        }
        loginAttempts.set(key, { count: 1, firstAttemptAt: now });
    } else {
        existing.count += 1;
    }
}

function clearLoginAttempts(key) {
    loginAttempts.delete(key);
}

function resetLoginRateLimiter() {
    loginAttempts.clear();
}

/**
 * GET /api/auth/config
 * Public endpoint exposing only the enabled server mode and public fixture metadata
 * when preset_training is enabled. Never exposes secrets, database names, or user records.
 */
publicAuthRouter.get("/config", (req, res) => {
    try {
        const config = resolveRuntimeConfig(process.env);
        return res.json({
            app_mode: config.appMode,
            demo_login_enabled: config.demoLoginEnabled,
            preset_tenants: config.demoLoginEnabled
                ? PUBLIC_PRESET_FIXTURES
                : [],
        });
    } catch {
        return res.json({
            app_mode: "standard",
            demo_login_enabled: false,
            preset_tenants: [],
        });
    }
});

/**
 * POST /api/auth/signup
 * "Get to Know You" onboarding: validates admin credentials and business profile,
 * creates a unique non-preset tenant and linked admin user, and establishes an HttpOnly session.
 */
publicAuthRouter.post("/signup", async (req, res) => {
    try {
        const currentMode = getAppMode(process.env);
        if (currentMode !== "standard") {
            return res.status(403).json({
                error: "Standard account signup is disabled in preset_training mode.",
            });
        }

        const body = req.body || {};
        const adminName = String(
            body.admin_name || body.name || body.team_name || ""
        ).trim();
        const email = String(body.email || "")
            .trim()
            .toLowerCase();
        const password = typeof body.password === "string" ? body.password : "";
        const businessName = String(body.business_name || "").trim();
        const industry = String(body.industry || body.sector || "").trim();
        const contactEmail = String(
            body.contact_email || body.support_email || email
        )
            .trim()
            .toLowerCase();
        const agentTone = String(
            body.agent_tone || "Warm & Professional"
        ).trim();

        const errors = [];
        if (adminName.length < 2 || adminName.length > 100) {
            errors.push("admin_name must be between 2 and 100 characters.");
        }
        if (!EMAIL_PATTERN.test(email)) {
            errors.push("A valid administrator email is required.");
        }
        if (password.length < 8 || password.length > 128) {
            errors.push("password must be between 8 and 128 characters.");
        }
        if (businessName.length < 2 || businessName.length > 120) {
            errors.push("business_name must be between 2 and 120 characters.");
        }
        if (industry.length < 2 || industry.length > 120) {
            errors.push("industry must be between 2 and 120 characters.");
        }
        if (!EMAIL_PATTERN.test(contactEmail)) {
            errors.push("A valid support contact_email is required.");
        }

        if (errors.length > 0) {
            return res.status(400).json({
                error: "Validation failed.",
                details: errors,
            });
        }

        const requestedSlugRaw =
            typeof body.tenant_id === "string" && body.tenant_id.trim()
                ? body.tenant_id.trim().toLowerCase()
                : "";
        const derivedBusinessSlug = slugifyTenantId(businessName);

        if (
            (requestedSlugRaw && isPresetTenantId(requestedSlugRaw)) ||
            isPresetTenantId(derivedBusinessSlug)
        ) {
            return res.status(409).json({
                error: "This business identifier is reserved for preset training fixtures.",
            });
        }

        const baseSlug = requestedSlugRaw
            ? slugifyTenantId(requestedSlugRaw)
            : derivedBusinessSlug;

        if (!baseSlug || !isValidTenantId(baseSlug)) {
            return res.status(400).json({
                error: "Could not derive a valid tenant_id from business_name.",
            });
        }

        const adminUsers = await getAdminUsersCollection();
        const businesses = await getBusinessesCollection();

        const existingAdmin = await adminUsers.findOne({ email });
        if (existingAdmin) {
            return res.status(409).json({
                error: "An administrator account with this email already exists.",
            });
        }

        // Resolve a unique tenant_id without attaching to any existing business
        let finalTenantId = baseSlug;
        const existingTenant = await businesses.findOne({
            tenant_id: finalTenantId,
        });
        if (existingTenant) {
            if (requestedSlugRaw) {
                return res.status(409).json({
                    error: `Tenant identifier '${finalTenantId}' is already in use.`,
                });
            }
            // Generate a collision-free unique suffix owned by the server
            let resolvedUnique = null;
            for (let attempt = 0; attempt < 5; attempt++) {
                const suffix = crypto.randomBytes(2).toString("hex");
                const candidate = `${baseSlug.slice(0, 42)}_${suffix}`;
                if (
                    isValidTenantId(candidate) &&
                    !isPresetTenantId(candidate)
                ) {
                    const taken = await businesses.findOne({
                        tenant_id: candidate,
                    });
                    if (!taken) {
                        resolvedUnique = candidate;
                        break;
                    }
                }
            }
            if (!resolvedUnique) {
                return res.status(409).json({
                    error: "Unable to allocate a unique tenant identifier. Please try a different business name.",
                });
            }
            finalTenantId = resolvedUnique;
        }

        const customPrompt =
            typeof body.system_prompt === "string" && body.system_prompt.trim()
                ? body.system_prompt.trim()
                : buildDefaultSystemPrompt({
                      businessName,
                      industry,
                      contactEmail,
                  });

        const nowIso = new Date().toISOString();
        const newTenantDoc = {
            tenant_id: finalTenantId,
            name: businessName,
            industry,
            contact_email: contactEmail,
            team_name: adminName,
            agent_config: {
                system_prompt: customPrompt,
                agent_tone: agentTone || "Warm & Professional",
                temperature: 0.2,
                max_context_chunks: 4,
                similarity_threshold: 0.7,
            },
            created_at: nowIso,
            updated_at: nowIso,
        };

        const passwordHash = await bcrypt.hash(password, 10);
        const userId = `usr_${crypto.randomBytes(8).toString("hex")}`;
        const newUserDoc = {
            user_id: userId,
            name: adminName,
            email,
            password_hash: passwordHash,
            principal_type: "admin",
            tenant_id: finalTenantId,
            created_at: nowIso,
            updated_at: nowIso,
        };

        await businesses.insertOne(newTenantDoc);

        try {
            await adminUsers.insertOne(newUserDoc);
        } catch (userInsertError) {
            // Roll back the newly inserted tenant so an orphan business is never left behind
            await businesses
                .deleteOne({ tenant_id: finalTenantId })
                .catch(() => {});

            if (userInsertError && userInsertError.code === 11000) {
                return res.status(409).json({
                    error: "An administrator account with this email already exists.",
                });
            }
            throw userInsertError;
        }

        // Revoke any prior session cookie before establishing the new session
        const oldToken = getRawSessionTokenFromRequest(req);
        if (oldToken) {
            await revokeSessionByRawToken(oldToken).catch(() => {});
        }

        const { rawToken, ttlMs } = await createSession({
            userId,
            principalType: "admin",
            tenantId: finalTenantId,
            appMode: currentMode,
        });
        setSessionCookie(res, req, rawToken, ttlMs);

        const { _id, ...cleanTenant } = newTenantDoc;

        return res.status(201).json({
            app_mode: currentMode,
            user: {
                user_id: userId,
                name: adminName,
                email,
                principal_type: "admin",
                tenant_id: finalTenantId,
            },
            tenant: cleanTenant,
            authorized_tenants: [cleanTenant],
        });
    } catch (error) {
        if (error && error.code === 11000) {
            return res.status(409).json({
                error: "Account or business identifier already exists.",
            });
        }
        console.error("[POST /api/auth/signup] Error:", error.message);
        return res.status(500).json({
            error: "Failed to complete account registration.",
        });
    }
});

/**
 * POST /api/auth/login
 * Authenticates standard administrator credentials against admin_users.
 * Never accepts caller-supplied tenant_id as proof of membership and never discloses whether an email exists.
 */
publicAuthRouter.post("/login", async (req, res) => {
    try {
        const currentMode = getAppMode(process.env);
        if (currentMode !== "standard") {
            return res.status(403).json({
                error: "Standard password login is disabled in preset_training mode. Use Quick Demo Login.",
            });
        }

        const body = req.body || {};
        const email = String(body.email || "")
            .trim()
            .toLowerCase();
        const password = typeof body.password === "string" ? body.password : "";

        if (!email || !password) {
            return res.status(400).json({
                error: "Email and password are required.",
            });
        }

        const rateKey = getRateLimitKey(req, email);
        const rateStatus = checkLoginRateLimit(rateKey);
        if (!rateStatus.allowed) {
            return res.status(429).json({
                error: "Too many failed login attempts. Please wait before trying again.",
            });
        }

        const adminUsers = await getAdminUsersCollection();
        const userDoc = await adminUsers.findOne({ email });

        const hashToCompare =
            userDoc && typeof userDoc.password_hash === "string"
                ? userDoc.password_hash
                : DUMMY_BCRYPT_HASH;

        const passwordMatches = await bcrypt.compare(password, hashToCompare);

        if (
            !userDoc ||
            !passwordMatches ||
            userDoc.principal_type !== "admin" ||
            !userDoc.tenant_id ||
            isPresetTenantId(userDoc.tenant_id)
        ) {
            recordFailedLoginAttempt(rateKey);
            return res.status(401).json({
                error: "Invalid email or password.",
            });
        }

        const businesses = await getBusinessesCollection();
        const tenantDoc = await businesses.findOne(
            { tenant_id: userDoc.tenant_id },
            { projection: { _id: 0 } }
        );

        if (!tenantDoc || isPresetTenantId(tenantDoc.tenant_id)) {
            recordFailedLoginAttempt(rateKey);
            return res.status(401).json({
                error: "Invalid email or password.",
            });
        }

        clearLoginAttempts(rateKey);

        const oldToken = getRawSessionTokenFromRequest(req);
        if (oldToken) {
            await revokeSessionByRawToken(oldToken).catch(() => {});
        }

        const { rawToken, ttlMs } = await createSession({
            userId: userDoc.user_id,
            principalType: "admin",
            tenantId: userDoc.tenant_id,
            appMode: currentMode,
        });
        setSessionCookie(res, req, rawToken, ttlMs);

        return res.status(200).json({
            app_mode: currentMode,
            user: {
                user_id: userDoc.user_id,
                name: userDoc.name,
                email: userDoc.email,
                principal_type: "admin",
                tenant_id: userDoc.tenant_id,
            },
            tenant: tenantDoc,
            authorized_tenants: [tenantDoc],
        });
    } catch (error) {
        console.error("[POST /api/auth/login] Error:", error.message);
        return res.status(500).json({
            error: "Login failed.",
        });
    }
});

/**
 * POST /api/auth/demo-login
 * Available ONLY in APP_MODE=preset_training.
 * Issues a normal expiring, revocable session for a server-defined demo principal
 * scoped strictly to the requested preset tenant. Revokes any previous session.
 */
publicAuthRouter.post("/demo-login", async (req, res) => {
    try {
        let runtimeConfig;
        try {
            runtimeConfig = resolveRuntimeConfig(process.env);
        } catch {
            return res.status(403).json({
                error: "Demo login is disabled due to server mode configuration.",
            });
        }

        if (
            runtimeConfig.appMode !== "preset_training" ||
            !runtimeConfig.demoLoginEnabled
        ) {
            return res.status(403).json({
                error: "Demo login is only permitted when APP_MODE='preset_training'.",
            });
        }

        const body = req.body || {};
        if (
            body.email !== undefined ||
            body.password !== undefined ||
            body.user_id !== undefined
        ) {
            return res.status(400).json({
                error: "Demo login accepts only a preset tenant_id and never impersonates admin users.",
            });
        }

        const requestedTenantId = String(body.tenant_id || "")
            .trim()
            .toLowerCase();
        if (!requestedTenantId) {
            return res.status(400).json({
                error: "Preset tenant_id is required.",
            });
        }

        if (
            !isValidTenantId(requestedTenantId) ||
            !isPresetTenantId(requestedTenantId)
        ) {
            return res.status(403).json({
                error: `Tenant '${requestedTenantId}' is not a valid preset training tenant.`,
            });
        }

        const oldToken = getRawSessionTokenFromRequest(req);
        if (oldToken) {
            await revokeSessionByRawToken(oldToken).catch(() => {});
        }

        const businesses = await getBusinessesCollection();
        let tenantDoc = await businesses.findOne(
            { tenant_id: requestedTenantId },
            { projection: { _id: 0 } }
        );

        if (!tenantDoc) {
            const presetTemplate = getPresetTenantById(requestedTenantId);
            const nowIso = new Date().toISOString();
            tenantDoc = {
                ...presetTemplate,
                updated_at: nowIso,
            };
            await businesses.updateOne(
                { tenant_id: requestedTenantId },
                { $setOnInsert: tenantDoc },
                { upsert: true }
            );
        }

        const demoUserId = `demo:${requestedTenantId}`;
        const { rawToken, ttlMs } = await createSession({
            userId: demoUserId,
            principalType: "demo_preset",
            tenantId: requestedTenantId,
            appMode: "preset_training",
        });
        setSessionCookie(res, req, rawToken, ttlMs);

        return res.status(200).json({
            app_mode: "preset_training",
            user: {
                user_id: demoUserId,
                name: `${tenantDoc.name} (Demo Admin)`,
                email: null,
                principal_type: "demo_preset",
                tenant_id: requestedTenantId,
            },
            tenant: tenantDoc,
            authorized_tenants: [tenantDoc],
        });
    } catch (error) {
        console.error("[POST /api/auth/demo-login] Error:", error.message);
        return res.status(500).json({
            error: "Failed to establish demo training session.",
        });
    }
});

/**
 * GET /api/auth/session
 * Requires valid session (protectedAuthRouter). Returns current user profile and authorized tenant.
 */
protectedAuthRouter.get("/session", async (req, res) => {
    try {
        const { tenantId, appMode, user } = req.auth;
        const businesses = await getBusinessesCollection();
        const tenantDoc = await businesses.findOne(
            { tenant_id: tenantId },
            { projection: { _id: 0 } }
        );

        if (!tenantDoc) {
            clearSessionCookie(res, req);
            return res.status(401).json({
                error: "Authorized tenant record no longer exists.",
            });
        }

        return res.json({
            authenticated: true,
            app_mode: appMode,
            user,
            tenant: tenantDoc,
            authorized_tenants: [tenantDoc],
        });
    } catch (error) {
        console.error("[GET /api/auth/session] Error:", error.message);
        return res.status(500).json({
            error: "Failed to load active session.",
        });
    }
});

/**
 * POST /api/auth/logout
 * Requires valid session (protectedAuthRouter). Revokes session in DB and clears cookie.
 */
protectedAuthRouter.post("/logout", async (req, res) => {
    try {
        const rawToken = getRawSessionTokenFromRequest(req);
        if (rawToken) {
            await revokeSessionByRawToken(rawToken);
        }
        clearSessionCookie(res, req);
        return res.json({
            status: "logged_out",
        });
    } catch (error) {
        console.error("[POST /api/auth/logout] Error:", error.message);
        return res.status(500).json({
            error: "Failed to log out.",
        });
    }
});

module.exports = {
    publicAuthRouter,
    protectedAuthRouter,
    resetLoginRateLimiter,
};

