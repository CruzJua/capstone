const { test, describe, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { loadEnv, ROOT_ENV_PATH, GATEWAY_ENV_PATH } = require("../src/config/env");
const { getChatConfig } = require("../src/chat/config");

const SERVER_PATH = path.resolve(__dirname, "../src/server.js");
const PROBE_KEYS = ["ENVTEST_ONE", "ENVTEST_TWO", "ENVTEST_QUOTED", "ENVTEST_SHELL", "ENVTEST_CWD"];
const CHAT_KEYS = ["CHAT_BACKEND_URL", "CHAT_BACKEND_TOKEN", "CHAT_RATE_LIMIT_PER_IP", "WIDGET_DEFAULT_ALLOWED_ORIGINS"];

describe("environment file loading", () => {
    let tmpDir;
    const saved = {};

    beforeEach(() => {
        tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "gateway-env-"));
        for (const key of [...PROBE_KEYS, ...CHAT_KEYS]) {
            saved[key] = process.env[key];
            delete process.env[key];
        }
    });

    afterEach(() => {
        fs.rmSync(tmpDir, { recursive: true, force: true });
        for (const [key, value] of Object.entries(saved)) {
            if (value === undefined) delete process.env[key];
            else process.env[key] = value;
        }
    });

    const write = (name, contents) => {
        const file = path.join(tmpDir, name);
        fs.writeFileSync(file, contents);
        return file;
    };

    test("reads values, comments and quotes from a .env file and reports the file that was used", () => {
        const file = write("a.env", '# comment\nENVTEST_ONE=1\nENVTEST_QUOTED="two words"\n\n# another comment\n');
        assert.deepEqual(loadEnv([file]), [file]);
        assert.equal(process.env.ENVTEST_ONE, "1");
        assert.equal(process.env.ENVTEST_QUOTED, "two words");
    });

    test("never overrides a variable that is already set (shell and Docker win)", () => {
        process.env.ENVTEST_SHELL = "from-shell";
        loadEnv([write("a.env", "ENVTEST_SHELL=from-file\n")]);
        assert.equal(process.env.ENVTEST_SHELL, "from-shell");
    });

    test("earlier files take priority over later ones", () => {
        const first = write("first.env", "ENVTEST_ONE=first\n");
        const second = write("second.env", "ENVTEST_ONE=second\nENVTEST_TWO=only-second\n");
        loadEnv([first, second]);
        assert.equal(process.env.ENVTEST_ONE, "first");
        assert.equal(process.env.ENVTEST_TWO, "only-second");
    });

    test("missing files are ignored without throwing", () => {
        const present = write("a.env", "ENVTEST_ONE=1\n");
        const loaded = loadEnv([path.join(tmpDir, "missing.env"), present]);
        assert.deepEqual(loaded, [present]);
        assert.deepEqual(loadEnv([path.join(tmpDir, "nope.env")]), []);
    });

    test("the default search order is the repository root .env, then gateway/.env", () => {
        assert.equal(ROOT_ENV_PATH, path.resolve(__dirname, "../../.env"));
        assert.equal(GATEWAY_ENV_PATH, path.resolve(__dirname, "../.env"));
    });

    test("chat and widget settings come from a .env file, with no shell exports", () => {
        loadEnv([
            write(
                "chat.env",
                [
                    "CHAT_BACKEND_URL=http://chat.internal:9100/",
                    "CHAT_BACKEND_TOKEN=file-secret",
                    "CHAT_RATE_LIMIT_PER_IP=7",
                    "WIDGET_DEFAULT_ALLOWED_ORIGINS=https://a.example.com, https://b.example.com",
                ].join("\n")
            ),
        ]);
        const config = getChatConfig(process.env);
        assert.equal(config.backendUrl, "http://chat.internal:9100");
        assert.equal(config.backendToken, "file-secret");
        assert.equal(config.rateLimitPerIp, 7);
        assert.deepEqual(config.defaultAllowedOrigins, ["https://a.example.com", "https://b.example.com"]);
    });

    describe("importing the server in a fresh process", () => {
        const probe = (cwd, extraEnv = {}) => {
            const env = { ...process.env, ...extraEnv };
            for (const key of PROBE_KEYS) if (!(key in extraEnv)) delete env[key];
            const result = spawnSync(
                process.execPath,
                [
                    "-e",
                    `require(${JSON.stringify(SERVER_PATH)});
                     console.log(JSON.stringify({ cwd: process.env.ENVTEST_CWD, shell: process.env.ENVTEST_SHELL }));`,
                ],
                { cwd, env, encoding: "utf-8", timeout: 30000 }
            );
            assert.equal(result.status, 0, result.stderr);
            return JSON.parse(result.stdout.trim().split("\n").pop());
        };

        test("picks up a .env in the working directory with nothing passed on the command line", () => {
            write(".env", "ENVTEST_CWD=from-dotenv\n");
            assert.equal(probe(tmpDir).cwd, "from-dotenv");
        });

        test("a variable exported in the shell still beats the .env file", () => {
            write(".env", "ENVTEST_SHELL=from-dotenv\n");
            assert.equal(probe(tmpDir, { ENVTEST_SHELL: "from-shell" }).shell, "from-shell");
        });
    });
});
