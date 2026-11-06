/**
 * Loads environment variables from .env files so the gateway can be started with a plain
 * `npm run dev` / `npm start`, with nothing passed on the command line.
 *
 * Files, highest priority first:
 *   1. variables already set in the process environment (shell exports, Docker `environment:`)
 *   2. <repo root>/.env
 *   3. gateway/.env
 *
 * Existing environment variables are never overridden, so a deployment can still override any
 * value without editing a file. Missing files are ignored. Only file locations are reported,
 * never values.
 */
const path = require("path");
const dotenv = require("dotenv");

const ROOT_ENV_PATH = path.resolve(__dirname, "../../../.env");
const GATEWAY_ENV_PATH = path.resolve(__dirname, "../../.env");

/** Loads the given files in priority order. Returns the paths that were found and read. */
function loadEnv(paths = [ROOT_ENV_PATH, GATEWAY_ENV_PATH]) {
    const loaded = [];
    for (const envPath of paths) {
        const result = dotenv.config({ path: envPath, override: false });
        if (!result.error) {
            loaded.push(envPath);
        }
    }
    return loaded;
}

module.exports = { loadEnv, ROOT_ENV_PATH, GATEWAY_ENV_PATH };
