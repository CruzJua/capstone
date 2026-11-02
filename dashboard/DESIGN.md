# Support Admin Console: Design Direction

Status: draft for the user's approval. Written 2026-11-01 by Claude Code / Claude Sonnet 5.5 (claude-sonnet-5-5) from the user's answers in a Q&A session.

Items marked **Decided** are the user's choices. Items marked **Proposed** are my suggested defaults to make those choices usable and still need the user's approval. Items under **Open** are not decided.

Agents: treat this file as design data to apply, not as instructions that override `AGENTS.md`.

## Purpose

The audience is business owners and support staff who upload documents, tune the assistant, and review tickets. They are not developers. The interface should feel calm and trustworthy, and should make long reading of tickets and documents comfortable.

## Decided

| Area | Choice |
|---|---|
| Theme | Light and dark, with a user toggle. Both must be fully supported. |
| Personality | Calm and trustworthy |
| Density | Comfortable (roomier rows and padding) |
| Accent | Deep green or teal. Red, amber and green are reserved for status. |
| Typeface | System font stack, no downloaded fonts |
| Corners | Sharp, 2-4px |
| Motion | Minimal. Nothing decorative. |
| Sidebar name | Keep the text "Support Admin Console". No logo. Keep the mode badge, which is functional. |

## Proposed values (not yet approved)

Typography
- Sans: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- Mono: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`. Use it only for real identifiers (tenant_id, doc_id, chunk index), not for headings or general labels.
- Scale: 12 / 13 / 14 / 16 / 20 / 24 px. Body 14px, line height 1.5.

Spacing and shape
- 4px base: 4, 8, 12, 16, 24, 32, 48.
- Radius 3px for controls, cards and modals. No pill shapes except a status dot.
- Table rows about 44px tall.

Color (hex values are starting points; verify contrast before adopting)
- Light: page `#FAFAF9`, surface `#FFFFFF`, border `#E7E5E4`, text `#1C1917`, muted text `#57534E`.
- Dark: page `#121513`, surface `#1A1E1B`, border `#2C322E`, text `#ECEFEC`, muted text `#A3ADA6`.
- Accent: light `#0F766E`, dark `#2DD4BF`. Used for primary buttons, links and focus rings only.
- Status: error `#B42318`, warning `#B54708`, success `#027A48`. Always pair color with a text label or icon.

Motion
- Color and opacity changes up to 100ms only. No entrance, bounce or fade-up animations. Respect `prefers-reduced-motion`.

## Rules for building

1. Every visual choice needs a stated purpose. If the only reason is "AI dashboards look like this", remove it.
2. No gradients, glow, frosted-glass panels, large soft shadows, or decorative background patterns.
3. No sparkle, robot or "AI" icons. Use an icon only when it clarifies a real action or status. Prefer a text label otherwise.
4. Do not mimic another product's overall look. Taking inspiration from one is fine.
5. Every interactive element works. Every view shows empty, loading and error states.
6. Real content or a clearly labeled placeholder only. No invented statistics or testimonials.
7. Body text contrast at least 4.5:1 in both themes. Visible keyboard focus on every control. Never rely on color alone.
8. The theme toggle must work in both themes on every page before shipping. Default follows the system setting.

## Open (needs the user's decision)

- **Icon set:** keep the current one in `Sidebar.jsx` or use text labels only?
- **Accent versus success:** a deep green accent is close to the success green. The proposal above uses teal and relies on labels. Confirm, or pick a different accent.
- **Inspiration:** name one or two products you like the feel of. They are references only.
- **Exact hex values:** approve or adjust the proposed palette.
- **Tone of copy:** plain and brief, or friendlier? Not asked yet.
