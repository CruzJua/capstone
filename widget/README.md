# selfhost-support-widget

An embeddable chat widget for a self-hosted, multi-tenant support gateway. Visitors see only the
assistant's reply. The widget talks to `POST {apiUrl}/api/chat` and nothing else: it never touches a
database and holds no secrets.

## Option 1: script tag

```html
<script src="https://support.example.com/widget.js"
        data-tenant-id="your_tenant"
        data-api-url="https://support.example.com"
        defer></script>
```

The script can come from your gateway (`GET /widget.js`) or from a CDN:

```html
<script src="https://cdn.jsdelivr.net/npm/selfhost-support-widget@0.1.0/dist/widget.js"
        data-tenant-id="your_tenant"
        data-api-url="https://support.example.com"
        defer></script>
```

**`data-api-url` is required when the script is not served by the gateway.** If you leave it out, the
widget uses the origin the script was loaded from, which is only correct for `/widget.js` served by
the gateway itself. Pin an exact version on a CDN.

| Attribute | Required | Default | Notes |
| :--- | :--- | :--- | :--- |
| `data-tenant-id` | yes | | Tenant to chat with. |
| `data-api-url` | when not served by the gateway | script origin | Gateway base URL. |
| `data-title` | no | `Support` | Header text. |
| `data-greeting` | no | `Hi! How can I help you today?` | First message. |
| `data-position` | no | `right` | `left` or `right`. |
| `data-accent-color` | no | built in | Any CSS colour. |

The widget renders in a shadow root, so your page's CSS cannot affect it.

## Option 2: React component

```bash
npm install selfhost-support-widget
```

```jsx
import { ChatWidget } from "selfhost-support-widget";

export default function App() {
    return <ChatWidget apiUrl="https://support.example.com" tenantId="your_tenant" />;
}
```

React 18 or newer is a peer dependency. The component injects its own styles and has no CSS import.
The package also exports `streamChat`, `ChatError` and `getSessionId` for building your own UI, with
TypeScript types included.

## Gateway requirement: allowed origins

The gateway only answers browsers whose origin is in that tenant's `widget_config.allowed_origins`
(exact origins, no wildcards). Otherwise it returns `403 origin_not_allowed`, no matter where the
script was loaded from. Add your site's origin, for example `https://shop.example.com`, to the
tenant before going live.

## Develop

```bash
npm install
npm run mock    # mock gateway on :4100, see API_CONTRACT.md
npm run dev     # dev page on :5173
npm test
npm run build   # dist/widget.js (script tag) and dist/lib/index.js (React import)
```

`API_CONTRACT.md` documents the request and the stream events.

## Publish

```bash
npm pack --dry-run     # check the file list
npm publish            # prepublishOnly runs the tests and the build
```
