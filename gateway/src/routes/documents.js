const express = require("express");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const multer = require("multer");
const { getDocVectorsCollection } = require("../db/mongo");
const { getAppMode, getActiveDatabaseName } = require("../config/mode");
const {
    isPresetTenantId,
    isValidTenantId,
    isValidDocId,
} = require("../config/presets");
const { authorizeTenantAccess } = require("../middleware/auth");

const router = express.Router();

const PROJECT_ROOT = path.resolve(__dirname, "../../..");
const UPLOAD_STAGING_DIR =
    (process.env.UPLOAD_STAGING_DIR || "").trim() || "/tmp/uploads";

fs.mkdirSync(UPLOAD_STAGING_DIR, { recursive: true });

function sanitizeFilename(filename) {
    return path
        .basename(filename || "document.md")
        .replace(/[^a-zA-Z0-9._-]/g, "_");
}

const storage = multer.diskStorage({
    destination: (req, file, cb) => {
        fs.mkdirSync(UPLOAD_STAGING_DIR, { recursive: true });
        cb(null, UPLOAD_STAGING_DIR);
    },
    filename: (req, file, cb) => {
        const sanitized = sanitizeFilename(file.originalname);
        const uniquePrefix = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        cb(null, `${uniquePrefix}_${sanitized}`);
    },
});

const upload = multer({
    storage,
    limits: {
        fileSize: 10 * 1024 * 1024, // 10 MB limit
    },
    fileFilter: (req, file, cb) => {
        const ext = path.extname(file.originalname || "").toLowerCase();
        if (ext !== ".md" && ext !== ".json") {
            return cb(
                new Error(
                    "Only Markdown (.md) and JSON (.json) files are allowed."
                )
            );
        }
        cb(null, true);
    },
});

/**
 * Resolves a preset source file under data/<tenantId>/<docId>.<ext> ONLY when:
 * 1. APP_MODE === 'preset_training'
 * 2. tenantId is a registered preset tenant
 * 3. tenantId and docId pass strict identifier validation
 * 4. The resolved path stays strictly inside PROJECT_ROOT/data/<tenantId>
 */
function resolveSafePresetSourcePath(tenantId, docId, ext) {
    if (getAppMode(process.env) !== "preset_training") {
        return null;
    }
    if (
        !isValidTenantId(tenantId) ||
        !isPresetTenantId(tenantId) ||
        !isValidDocId(docId)
    ) {
        return null;
    }
    if (ext !== "md" && ext !== "json") {
        return null;
    }

    const baseDataDir = path.resolve(PROJECT_ROOT, "data");
    const tenantDir = path.resolve(baseDataDir, tenantId);
    if (
        !tenantDir.startsWith(baseDataDir + path.sep) ||
        path.dirname(tenantDir) !== baseDataDir
    ) {
        return null;
    }

    const candidatePath = path.resolve(tenantDir, `${docId}.${ext}`);
    if (
        !candidatePath.startsWith(tenantDir + path.sep) ||
        path.dirname(candidatePath) !== tenantDir
    ) {
        return null;
    }

    if (!fs.existsSync(candidatePath)) {
        return null;
    }

    return candidatePath;
}

function inferFormat(docId, explicitFormat, sampleText, tenantId) {
    if (explicitFormat === "md" || explicitFormat === "json") {
        return explicitFormat;
    }

    if (resolveSafePresetSourcePath(tenantId, docId, "json")) {
        return "json";
    }
    if (resolveSafePresetSourcePath(tenantId, docId, "md")) {
        return "md";
    }

    if (
        docId === "faq_support_knowledgebase" ||
        docId.endsWith("_matrix") ||
        docId.endsWith("_specs") ||
        (typeof sampleText === "string" && sampleText.trim().startsWith("{"))
    ) {
        return "json";
    }
    return "md";
}

function defaultPythonIngestionRunner({
    filePath,
    tenantId,
    overwrite,
    docId,
    dbName,
}) {
    return new Promise((resolve, reject) => {
        const pythonExecutable = (process.env.PYTHON_EXECUTABLE || "").trim();
        let command = "uv";
        let scriptArgs = [
            "run",
            "python",
            "-m",
            "scripts.ingest_uploaded_document",
            "--file",
            filePath,
            "--tenant",
            tenantId,
            "--overwrite",
            overwrite ? "true" : "false",
            "--doc-id",
            docId,
            "--db-name",
            dbName,
        ];

        if (pythonExecutable) {
            command = pythonExecutable;
            scriptArgs = scriptArgs.slice(2);
        } else {
            const venvPython = path.resolve(PROJECT_ROOT, ".venv/bin/python");
            if (fs.existsSync(venvPython)) {
                command = venvPython;
                scriptArgs = scriptArgs.slice(2);
            }
        }

        const child = spawn(command, scriptArgs, {
            cwd: PROJECT_ROOT,
            env: {
                ...process.env,
                MONGODB_DB_NAME: dbName,
                HF_HUB_DISABLE_PROGRESS_BARS: "1",
                TOKENIZERS_PARALLELISM: "false",
            },
        });

        let stdout = "";
        let stderr = "";

        child.stdout.on("data", (chunk) => {
            stdout += chunk.toString();
        });

        child.stderr.on("data", (chunk) => {
            stderr += chunk.toString();
        });

        child.on("error", (err) => {
            reject(new Error(`Failed to spawn uv process: ${err.message}`));
        });

        child.on("close", (code) => {
            const lines = stdout
                .split(/\r?\n/)
                .map((line) => line.trim())
                .filter(Boolean);
            const lastLine = lines[lines.length - 1] || "";

            let parsed = null;
            try {
                parsed = JSON.parse(lastLine);
            } catch {
                parsed = null;
            }

            if (code === 0 && parsed && parsed.status === "success") {
                return resolve(parsed);
            }

            if (parsed && parsed.error) {
                const err = new Error(parsed.error);
                err.code = parsed.code || "INGESTION_ERROR";
                err.exitCode = code;
                return reject(err);
            }

            const fallbackMsg =
                stderr.trim() ||
                stdout.trim() ||
                `Python ingestion process exited with code ${code}`;
            const err = new Error(fallbackMsg);
            err.exitCode = code;
            reject(err);
        });
    });
}

let activeIngestionRunner = defaultPythonIngestionRunner;

function setIngestionRunner(runner) {
    activeIngestionRunner = runner || defaultPythonIngestionRunner;
}

function resetIngestionRunner() {
    activeIngestionRunner = defaultPythonIngestionRunner;
}

/**
 * POST /api/documents/upload
 * Authenticates session and pre-validates any query/header tenant selector BEFORE multipart parsing.
 * After multipart parsing, verifies any body tenant_id against the session tenant, cleans up temp files
 * on rejection, and passes the session-authorized tenantId and active database name to the worker.
 */
router.post("/documents/upload", (req, res) => {
    // Pre-multipart authorization check (session + any query/header selector)
    const preAuthTenant = authorizeTenantAccess(req, res);
    if (!preAuthTenant) {
        return;
    }

    upload.single("file")(req, res, async (uploadErr) => {
        if (uploadErr) {
            return res.status(400).json({
                status: "error",
                error: uploadErr.message || "File upload failed.",
            });
        }

        const tempFilePath = req.file?.path;
        try {
            // Post-multipart authorization check (validates body.tenant_id if provided)
            const authorizedTenantId = authorizeTenantAccess(req, res);
            if (!authorizedTenantId) {
                return;
            }

            if (!req.file) {
                return res.status(400).json({
                    status: "error",
                    error: "No file uploaded. Provide a .md or .json file under field 'file'.",
                });
            }

            const rawOverwrite = req.body?.overwrite;
            const overwrite =
                rawOverwrite === undefined
                    ? true
                    : String(rawOverwrite).toLowerCase() === "true" ||
                      String(rawOverwrite) === "1";

            const originalStem = path.parse(req.file.originalname).name;
            const targetDocId = (req.body?.doc_id || originalStem || "document")
                .trim()
                .replace(/\.(md|json)$/i, "");

            if (!isValidDocId(targetDocId)) {
                return res.status(400).json({
                    status: "error",
                    error: "Invalid doc_id format.",
                });
            }

            const activeDbName = getActiveDatabaseName(process.env);
            const summary = await activeIngestionRunner({
                filePath: tempFilePath,
                tenantId: authorizedTenantId,
                overwrite,
                docId: targetDocId,
                dbName: activeDbName,
            });

            return res.status(200).json(summary);
        } catch (error) {
            console.error(
                "[POST /api/documents/upload] Error:",
                error.message
            );
            const statusCode = error.code === "DOCUMENT_EXISTS" ? 409 : 400;
            return res.status(statusCode).json({
                status: "error",
                code: error.code || "INGESTION_ERROR",
                error: error.message || "Failed to ingest uploaded document.",
            });
        } finally {
            if (tempFilePath) {
                await fs.promises.unlink(tempFilePath).catch(() => {});
            }
        }
    });
});

/**
 * GET /api/tenants/:tenantId/documents
 * Queries doc_vectors grouped by doc_id for the session-authorized tenant.
 */
router.get("/tenants/:tenantId/documents", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const docVectors = await getDocVectorsCollection();

        const pipeline = [
            { $match: { tenant_id: authorizedTenantId } },
            { $sort: { chunk_index: 1 } },
            {
                $group: {
                    _id: "$doc_id",
                    chunk_count: { $sum: 1 },
                    created_at: { $max: "$created_at" },
                    format: { $first: "$format" },
                    sample_text: { $first: "$text" },
                    total_chars: {
                        $sum: { $strLenCP: { $ifNull: ["$text", ""] } },
                    },
                },
            },
            { $sort: { _id: 1 } },
        ];

        const grouped = await docVectors.aggregate(pipeline).toArray();

        const documents = grouped.map((item) => {
            const docId = item._id;
            const format = inferFormat(
                docId,
                item.format,
                item.sample_text,
                authorizedTenantId
            );
            return {
                doc_id: docId,
                file_name: `${docId}.${format}`,
                format,
                chunk_count: item.chunk_count,
                total_chars: item.total_chars || 0,
                created_at: item.created_at || null,
            };
        });

        return res.json(documents);
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/documents] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to fetch tenant documents.",
        });
    }
});

/**
 * GET /api/tenants/:tenantId/documents/:docId
 * Returns raw document text and ordered chunks for DocumentViewerModal.
 */
router.get("/tenants/:tenantId/documents/:docId", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const { docId } = req.params;
        if (!isValidDocId(docId)) {
            return res.status(400).json({
                error: "Invalid document identifier.",
            });
        }

        const docVectors = await getDocVectorsCollection();

        const chunks = await docVectors
            .find(
                { tenant_id: authorizedTenantId, doc_id: docId },
                { projection: { _id: 0, embedding: 0 } }
            )
            .sort({ chunk_index: 1 })
            .toArray();

        if (!chunks || chunks.length === 0) {
            return res.status(404).json({
                error: `Document '${docId}' not found for tenant '${authorizedTenantId}'.`,
            });
        }

        const firstChunk = chunks[0];
        const format = inferFormat(
            docId,
            firstChunk.format,
            firstChunk.text,
            authorizedTenantId
        );

        let rawText = null;
        if (!firstChunk.format) {
            const safeDiskPath = resolveSafePresetSourcePath(
                authorizedTenantId,
                docId,
                format
            );
            if (safeDiskPath) {
                rawText = await fs.promises.readFile(safeDiskPath, "utf-8");
            }
        }

        if (!rawText) {
            if (format === "md") {
                const parts = [];
                let lastSection = null;
                for (const chunk of chunks) {
                    const sec = chunk.section || "Overview";
                    if (sec !== lastSection) {
                        parts.push(`## ${sec}\n\n${chunk.text}`);
                        lastSection = sec;
                    } else {
                        parts.push(chunk.text);
                    }
                }
                rawText = parts.join("\n\n");
            } else {
                rawText = chunks.map((c) => c.text).join("\n\n");
            }
        }

        return res.json({
            tenant_id: authorizedTenantId,
            doc_id: docId,
            file_name: `${docId}.${format}`,
            format,
            chunk_count: chunks.length,
            created_at: chunks[chunks.length - 1]?.created_at || null,
            raw_text: rawText,
            chunks,
        });
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/documents/:docId] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to load document content.",
        });
    }
});

/**
 * GET /api/tenants/:tenantId/chunks
 * Returns paginated chunks for the session-authorized tenant.
 */
router.get("/tenants/:tenantId/chunks", async (req, res) => {
    try {
        const authorizedTenantId = authorizeTenantAccess(
            req,
            res,
            req.params.tenantId
        );
        if (!authorizedTenantId) return;

        const docIdFilter = (req.query.doc_id || "").trim();
        if (docIdFilter && !isValidDocId(docIdFilter)) {
            return res.status(400).json({
                error: "Invalid doc_id filter.",
            });
        }

        const searchQuery = (req.query.search || "").trim();
        const page = Math.max(1, parseInt(req.query.page, 10) || 1);
        const limit = Math.min(
            200,
            Math.max(1, parseInt(req.query.limit, 10) || 50)
        );
        const skip = (page - 1) * limit;

        const query = { tenant_id: authorizedTenantId };
        if (docIdFilter) {
            query.doc_id = docIdFilter;
        }
        if (searchQuery) {
            const escaped = searchQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            query.$or = [
                { text: { $regex: escaped, $options: "i" } },
                { section: { $regex: escaped, $options: "i" } },
                { doc_id: { $regex: escaped, $options: "i" } },
            ];
        }

        const docVectors = await getDocVectorsCollection();
        const [total, rawChunks] = await Promise.all([
            docVectors.countDocuments(query),
            docVectors
                .find(query, { projection: { _id: 0, embedding: 0 } })
                .sort({ doc_id: 1, chunk_index: 1 })
                .skip(skip)
                .limit(limit)
                .toArray(),
        ]);

        const chunks = rawChunks.map((chunk) => {
            const text = chunk.text || "";
            const charCount = text.length;
            const words = text.trim() ? text.trim().split(/\s+/).length : 0;
            const tokenEstimate = Math.max(1, Math.ceil(words * 1.3));
            const snippet =
                text.length > 160 ? `${text.slice(0, 160).trim()}...` : text;

            return {
                tenant_id: chunk.tenant_id,
                doc_id: chunk.doc_id,
                chunk_index: chunk.chunk_index,
                section: chunk.section || "Overview",
                snippet,
                text,
                char_count: charCount,
                word_count: words,
                token_estimate: tokenEstimate,
                created_at: chunk.created_at || null,
            };
        });

        return res.json({
            tenant_id: authorizedTenantId,
            chunks,
            total,
            page,
            limit,
            total_pages: Math.max(1, Math.ceil(total / limit)),
        });
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/chunks] Error:",
            error.message
        );
        return res.status(500).json({
            error: "Failed to fetch tenant vector chunks.",
        });
    }
});

module.exports = router;
module.exports.setIngestionRunner = setIngestionRunner;
module.exports.resetIngestionRunner = resetIngestionRunner;
module.exports.resolveSafePresetSourcePath = resolveSafePresetSourcePath;
