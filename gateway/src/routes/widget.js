/**
 * GET /widget.js: serves the built embeddable chat widget (widget/dist/widget.js).
 *
 * The bundle is read from the widget build output on every request (conditional GETs are answered
 * from the file's ETag / mtime), never copied into the gateway source tree. Build it with
 * `cd widget && npm run build:embed`, or point WIDGET_DIST_PATH at another build.
 *
 * This route is public and static: no cookies, no credentials, and none of the admin CORS policy.
 */
const path = require("path");
const express = require("express");

const DEFAULT_WIDGET_PATH = path.resolve(__dirname, "../../../widget/dist/widget.js");

function getWidgetPath(env = process.env) {
    const custom = String(env.WIDGET_DIST_PATH || "").trim();
    return custom ? path.resolve(custom) : DEFAULT_WIDGET_PATH;
}

const router = express.Router();

router.get("/", (req, res) => {
    res.set({
        "Content-Type": "text/javascript; charset=utf-8",
        "Cache-Control": "public, no-cache",
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "cross-origin",
        // Public static asset, so a wildcard is safe; credentials are never allowed.
        "Access-Control-Allow-Origin": "*",
    });
    res.sendFile(getWidgetPath(process.env), { dotfiles: "allow", cacheControl: false }, (error) => {
        if (!error || res.headersSent) return;
        res.removeHeader("Content-Type");
        res.removeHeader("Cross-Origin-Resource-Policy");
        res.status(404).json({
            error: {
                code: "widget_not_built",
                message: "The chat widget bundle has not been built. Run `npm run build:embed` in widget/.",
            },
        });
    });
});

router.all("/", (req, res) => {
    res.setHeader("Allow", "GET, HEAD");
    res.status(405).json({ error: { code: "method_not_allowed", message: "Use GET /widget.js." } });
});

module.exports = { router, getWidgetPath };
