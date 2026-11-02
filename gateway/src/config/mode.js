const VALID_APP_MODES = new Set(["standard", "preset_training"]);

function validateAppMode(rawMode) {
    if (rawMode === undefined || rawMode === null) {
        return "standard";
    }
    const trimmed = String(rawMode).trim();
    if (trimmed === "") {
        return "standard";
    }
    if (!VALID_APP_MODES.has(trimmed)) {
        const err = new Error(
            `Invalid APP_MODE '${rawMode}'. Allowed values are 'standard' (default) or 'preset_training'.`
        );
        err.code = "INVALID_APP_MODE";
        throw err;
    }
    return trimmed;
}

function resolveRuntimeConfig(env = process.env) {
    const appMode = validateAppMode(env.APP_MODE);

    const rawStandardDb = env.MONGODB_DB_NAME;
    const standardDbName =
        rawStandardDb === undefined || rawStandardDb === null
            ? "rag_knowledge_base"
            : String(rawStandardDb).trim();

    if (!standardDbName) {
        const err = new Error(
            "MONGODB_DB_NAME must be a non-empty database name."
        );
        err.code = "INVALID_DB_CONFIG";
        throw err;
    }

    const trainingDbName =
        env.MONGODB_TRAINING_DB_NAME !== undefined &&
        env.MONGODB_TRAINING_DB_NAME !== null
            ? String(env.MONGODB_TRAINING_DB_NAME).trim()
            : "";

    if (trainingDbName && trainingDbName === standardDbName) {
        const err = new Error(
            `MONGODB_TRAINING_DB_NAME ('${trainingDbName}') must be distinct from standard MONGODB_DB_NAME ('${standardDbName}').`
        );
        err.code = "INVALID_DB_CONFIG";
        throw err;
    }

    if (appMode === "preset_training") {
        if (!trainingDbName) {
            const err = new Error(
                "APP_MODE='preset_training' requires an explicit MONGODB_TRAINING_DB_NAME distinct from MONGODB_DB_NAME."
            );
            err.code = "MISSING_TRAINING_DB_CONFIG";
            throw err;
        }

        return {
            appMode: "preset_training",
            activeDbName: trainingDbName,
            standardDbName,
            trainingDbName,
            demoLoginEnabled: true,
        };
    }

    return {
        appMode: "standard",
        activeDbName: standardDbName,
        standardDbName,
        trainingDbName: trainingDbName || null,
        demoLoginEnabled: false,
    };
}

function getAppMode(env = process.env) {
    return resolveRuntimeConfig(env).appMode;
}

function getActiveDatabaseName(env = process.env) {
    return resolveRuntimeConfig(env).activeDbName;
}

module.exports = {
    VALID_APP_MODES,
    validateAppMode,
    resolveRuntimeConfig,
    getAppMode,
    getActiveDatabaseName,
};

