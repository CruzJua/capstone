const express = require("express");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const multer = require("multer");
const { getDocVectorsCollection } = require("../db/mongo");

const router = express.Router();

const PROJECT_ROOT = path.resolve(__dirname, "../../..");
const UPLOAD_STAGING_DIR = "/tmp/uploads";

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
                new Error("Only Markdown (.md) and JSON (.json) files are allowed.")
            );
        }
        cb(null, true);
    },
});

function inferFormat(docId, explicitFormat, sampleText, tenantId) {
    if (explicitFormat === "md" || explicitFormat === "json") {
        return explicitFormat;
    }
    const jsonDiskPath = path.join(PROJECT_ROOT, "data", tenantId, `${docId}.json`);
    if (fs.existsSync(jsonDiskPath)) {
        return "json";
    }
    const mdDiskPath = path.join(PROJECT_ROOT, "data", tenantId, `${docId}.md`);
    if (fs.existsSync(mdDiskPath)) {
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

function runPythonIngestion({ filePath, tenantId, overwrite, docId }) {
    return new Promise((resolve, reject) => {
        const scriptArgs = [
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
        ];

        const child = spawn("uv", scriptArgs, {
            cwd: PROJECT_ROOT,
            env: {
                ...process.env,
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

/**
 * POST /api/documents/upload
 * Receives multipart file (.md or .json), tenant_id, overwrite flag, and optional doc_id.
 */
router.post("/documents/upload", (req, res) => {
    upload.single("file")(req, res, async (uploadErr) => {
        if (uploadErr) {
            return res.status(400).json({
                status: "error",
                error: uploadErr.message || "File upload failed.",
            });
        }

        const tempFilePath = req.file?.path;
        try {
            if (!req.file) {
                return res.status(400).json({
                    status: "error",
                    error: "No file uploaded. Provide a .md or .json file under field 'file'.",
                });
            }

            const tenantId = (req.body?.tenant_id || "").trim();
            if (!tenantId) {
                return res.status(400).json({
                    status: "error",
                    error: "tenant_id is required.",
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

            const summary = await runPythonIngestion({
                filePath: tempFilePath,
                tenantId,
                overwrite,
                docId: targetDocId,
            });

            return res.status(200).json(summary);
        } catch (error) {
            console.error("[POST /api/documents/upload] Error:", error.message);
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
 * Queries doc_vectors grouped by doc_id, returning file_name, format, chunk_count, and latest created_at.
 */
router.get("/tenants/:tenantId/documents", async (req, res) => {
    try {
        const { tenantId } = req.params;
        const docVectors = await getDocVectorsCollection();

        const pipeline = [
            { $match: { tenant_id: tenantId } },
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
                tenantId
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

        res.json(documents);
    } catch (error) {
        console.error(
            "[GET /api/tenants/:tenantId/documents] Error:",
            error.message
        );
        res.status(500).json({
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
        const { tenantId, docId } = req.params;
        const docVectors = await getDocVectorsCollection();

        const chunks = await docVectors
            .find(
                { tenant_id: tenantId, doc_id: docId },
                { projection: { _id: 0, embedding: 0 } }
            )
            .sort({ chunk_index: 1 })
            .toArray();

        if (!chunks || chunks.length === 0) {
            return res.status(404).json({
                error: `Document '${docId}' not found for tenant '${tenantId}'.`,
            });
        }

        const firstChunk = chunks[0];
        const format = inferFormat(
            docId,
            firstChunk.format,
            firstChunk.text,
            tenantId
        );

        let rawText = null;
        // If this document was part of the baseline seed (no explicit format tag from upload),
        // check if the original source file exists on disk; otherwise reconstruct from live chunks.
        if (!firstChunk.format) {
            const diskCandidate = path.join(
                PROJECT_ROOT,
                "data",
                tenantId,
                `${docId}.${format}`
            );
            if (fs.existsSync(diskCandidate)) {
                rawText = await fs.promises.readFile(diskCandidate, "utf-8");
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

        res.json({
            tenant_id: tenantId,
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
        res.status(500).json({
            error: "Failed to load document content.",
        });
    }
});

/**
 * GET /api/tenants/:tenantId/chunks
 * Returns paginated chunks for the tenant (chunk_index, section, snippet, text, char_count, token_estimate).
 */
router.get("/tenants/:tenantId/chunks", async (req, res) => {
    try {
        const { tenantId } = req.params;
        const docIdFilter = (req.query.doc_id || "").trim();
        const searchQuery = (req.query.search || "").trim();
        const page = Math.max(1, parseInt(req.query.page, 10) || 1);
        const limit = Math.min(
            200,
            Math.max(1, parseInt(req.query.limit, 10) || 50)
        );
        const skip = (page - 1) * limit;

        const query = { tenant_id: tenantId };
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

        res.json({
            tenant_id: tenantId,
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
        res.status(500).json({
            error: "Failed to fetch tenant vector chunks.",
        });
    }
});

module.exports = router;

