const express = require("express");
const { getBusinessesCollection } = require("../db/mongo");
const { getAppMode } = require("../config/mode");
const { PRESET_TENANT_IDS, isPresetTenantId } = require("../config/presets");
const { authorizeTenantAccess } = require("../middleware/auth");
const { parseAllowedOrigins } = require("../chat/origins");

const router = express.Router();

function validateAndBuildUpdate(body) {
    const errors = [];
    const setFields = {};

    if (body.name !== undefined) {
        if (typeof body.name !== "string" || !body.name.trim()) {
            errors.push("name must be a non-empty string.");
        } else {
            setFields.name = body.name.trim();
        }
    }

    if (body.contact_email !== undefined) {
        if (
            typeof body.contact_email !== "string" ||
            !body.contact_email.trim()
        ) {
            errors.push("contact_email must be a non-empty string.");
        } else {
            setFields.contact_email = body.contact_email.trim();
        }
    }

    if (body.industry !== undefined) {
        if (typeof body.industry !== "string") {
            errors.push("industry must be a string.");
        } else {
            setFields.industry = body.industry.trim();
        }
    }

    if (body.team_name !== undefined) {
        if (typeof body.team_name !== "string") {
            errors.push("team_name must be a string.");
        } else {
            setFields.team_name = body.team_name.trim();
        }
    }

    if (body.agent_config !== undefined) {
        if (
            typeof body.agent_config !== "object" ||
            body.agent_config === null ||
            Array.isArray(body.agent_config)
        ) {
            errors.push("agent_config must be an object.");
        } else {
            const ac = body.agent_config;

            if (ac.system_prompt !== undefined) {
                if (
                    typeof ac.system_prompt !== "string" ||
                    !ac.system_prompt.trim()
                ) {
                    errors.push(
                        "agent_config.system_prompt must be a non-empty string."
                    );
                } else {
                    setFields["agent_config.system_prompt"] =
                        ac.system_prompt.trim();
                }
            }

            if (ac.agent_tone !== undefined) {
                if (
                    typeof ac.agent_tone !== "string" ||
                    !ac.agent_tone.trim()
                ) {
                    errors.push(
                        "agent_config.agent_tone must be a non-empty string."
                    );
                } else {
                    setFields["agent_config.agent_tone"] = ac.agent_tone.trim();
                }
            }

            if (ac.temperature !== undefined) {
                const temp = Number(ac.temperature);
                if (Number.isNaN(temp) || temp < 0.0 || temp > 1.0) {
                    errors.push(
                        "agent_config.temperature must be a number between 0.0 and 1.0."
                    );
                } else {
                    setFields["agent_config.temperature"] = Number(
                        temp.toFixed(2)
                    );
                }
            }

            if (ac.max_context_chunks !== undefined) {
                const chunks = Number(ac.max_context_chunks);
                if (!Number.isInteger(chunks) || chunks < 1 || chunks > 8) {
                    errors.push(
                        "agent_config.max_context_chunks must be an integer between 1 and 8."
                    );
                } else {
                    setFields["agent_config.max_context_chunks"] = chunks;
                }
            }

            if (ac.similarity_threshold !== undefined) {
                const threshold = Number(ac.similarity_threshold);
                if (
                    Number.isNaN(threshold) ||
                    threshold < 0.5 ||
                    threshold > 0.95
                ) {
                    errors.push(
                        "agent_config.similarity_threshold must be a number between 0.50 and 0.95."
                    );
                } else {
                    setFields["agent_config.similarity_threshold"] = Number(
                        threshold.toFixed(2)
                    );
                }
            }
        }
    }

    if (body.widget_config !== undefined) {
        if (
            typeof body.widget_config !== "object" ||
            body.widget_config === null ||
            Array.isArray(body.widget_config)
        ) {
            errors.push("widget_config must be an object.");
        } else if (body.widget_config.allowed_origins !== undefined) {
            const parsed = parseAllowedOrigins(body.widget_config.allowed_origins);
            if (parsed.error) {
                errors.push(parsed.error);
            } else {
                setFields["widget_config.allowed_origins"] = parsed.origins;
            }
        }
    }

    return { errors, setFields };
}

/**
 * GET /api/tenants
 * Returns ONLY the tenant(s) authorized for the current session.
 * In standard mode, preset tenants are strictly excluded even if old seeded records exist.
 */
router.get("/", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(req, res);
        if (!authorizedTenantId) return;

        const currentMode = getAppMode(process.env);
        const allowedIds = (req.auth.authorizedTenantIds || []).filter((id) =>
            currentMode === "standard"
                ? !isPresetTenantId(id)
                : isPresetTenantId(id)
        );

        if (allowedIds.length === 0) {
            return res.json([]);
        }

        const filter =
            currentMode === "standard"
                ? {
                      tenant_id: {
                          $in: allowedIds,
                          $nin: Array.from(PRESET_TENANT_IDS),
                      },
                  }
                : {
                      tenant_id: {
                          $in: allowedIds,
                      },
                  };

        const businesses = await getBusinessesCollection();
        const tenants = await businesses
            .find(filter, { projection: { _id: 0 } })
            .sort({ name: 1 })
            .toArray();

        const filtered = tenants.filter((t) =>
            currentMode === "standard"
                ? !isPresetTenantId(t.tenant_id)
                : isPresetTenantId(t.tenant_id)
        );

        return res.json(filtered);
    } catch (error) {
        console.error("[GET /api/tenants] Error:", error.message);
        return res.status(500).json({
            error: "Failed to fetch tenants from database.",
        });
    }
});

/**
 * GET /api/tenants/:tenantId/config
 * Returns specific tenant configuration document if and only if authorized for the session.
 */
router.get("/:tenantId/config", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const businesses = await getBusinessesCollection();
        const tenant = await businesses.findOne(
            { tenant_id: authorizedTenantId },
            { projection: { _id: 0 } }
        );

        if (!tenant) {
            return res.status(404).json({
                error: `Tenant '${authorizedTenantId}' not found.`,
            });
        }

        return res.json(tenant);
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/config] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to fetch tenant configuration.",
        });
    }
});

/**
 * PUT /api/tenants/:tenantId/config
 * Validates and updates name, contact_email, industry, team_name, and agent_config using $set.
 */
router.put("/:tenantId/config", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const { errors, setFields } = validateAndBuildUpdate(req.body || {});

        if (errors.length > 0) {
            return res.status(400).json({
                error: "Validation failed.",
                details: errors,
            });
        }

        if (Object.keys(setFields).length === 0) {
            return res.status(400).json({
                error: "No valid configuration fields provided for update.",
            });
        }

        setFields.updated_at = new Date().toISOString();

        const businesses = await getBusinessesCollection();
        const updatedTenant = await businesses.findOneAndUpdate(
            { tenant_id: authorizedTenantId },
            { $set: setFields },
            { returnDocument: "after", projection: { _id: 0 } }
        );

        if (!updatedTenant) {
            return res.status(404).json({
                error: `Tenant '${authorizedTenantId}' not found.`,
            });
        }

        return res.json(updatedTenant);
    } catch (error) {
        console.error(
            "[PUT /api/tenants/:tenantId/config] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to update tenant configuration.",
        });
    }
});

module.exports = router;
