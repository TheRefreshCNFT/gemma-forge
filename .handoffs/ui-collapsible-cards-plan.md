# Plan: Collapse completed sections into horizontal pills

> Status: **planned, not started.**

## Goal

Once a card finishes (status = complete, verified, or failed), the
full card panel collapses into a compact horizontal **pill** showing
just the title + status + verb (Re-run, Verify, Redo). Clicking
the pill expands it back to the full panel. The session view stays
clean and complete; the workflow doesn't blow up vertically.

## Behavior

- **Card status drives the default visibility:**
  - `active` (currently running or next-up) → expanded
  - `complete` / `verified` → collapsed pill
  - `needs-attention` / `failed` → collapsed pill but visually flagged (amber/red dot)
  - `inactive` / `pending` → small grey pill, deferred section
- Clicking a pill toggles it; choice is sticky per-session (`localStorage`).
- A small "expand all" / "collapse all" link sits above the card stack
  for power users.

## Pill anatomy

```
[●] Project Context    8.2s  ✓ verified                                    ▾
[●] GSD Planning       12s   ✓ complete                                    ▾
[●] Project Execution  18s   ✓ complete  · output/webot_agency_logo.svg    ▾
[●] Verification       4s    ⚠ needs attention                             ▾
```

- Left dot: card-type color (matches the current expanded panel).
- Title: card title from default_cards.
- Time: `lastRun.elapsedMs` formatted.
- Status word + glyph (verified ✓ / complete ✓ / attention ⚠ / running …).
- Optional tail: the most useful one-line summary from the card
  result (for Execution, the lone file path; for Verification, the
  pass/fail; etc.).
- Caret on the right that flips when expanded.

## File changes

- `chat/static/css/style.css` — add `.card.collapsed` ruleset:
  height auto, single row layout, padding shrinks, all inner panels
  set to `display: none` except the pill row.
- `chat/static/js/chat.js`:
  - Render each card with a `.card-pill` header row PLUS the
    existing detail body. The pill is always rendered; the body is
    conditionally shown based on the card's `collapsed` flag.
  - On card-status change (e.g. complete), set `card.collapsed = true`
    locally and persist to `localStorage[session_id]`.
  - Click handler on the pill toggles `collapsed`.
  - Add a `.card-bar` above the stack containing "Expand all" /
    "Collapse all" links.
- `chat/templates/index.html` — no markup change required; the
  card list is built in JS from `/api/sessions` data.

No server change needed. This is purely view-state.

## Edge cases handled

- **Live status update during a run**: while a card has `status: running`
  (in-flight POST), keep it expanded so the user sees streaming
  progress. Auto-collapse only fires AFTER the response sets
  `complete` / `verified`.
- **Failure cases**: `failed` and `needs-attention` cards stay
  expanded by default on the first failure (so the user sees what
  went wrong without an extra click). After the user explicitly
  collapses them, the choice is remembered.
- **New session**: all cards start expanded except `inactive` ones.
- **Mobile**: pill rows stack to 2 lines if width < 480 px; the time
  and tail text wrap below the title.

## Out of scope

- Drag-to-reorder cards (the order is harness-defined).
- Multi-select / batch actions.
- Persisting collapsed state across browser sessions (local storage
  is per-session only).

## Implementation order

1. CSS: `.card.collapsed` + `.card-pill` layout, status-dot colors.
2. JS render: split card markup into `pill` + `body`, default-state
   logic based on card status.
3. JS click handler + localStorage.
4. JS "expand all / collapse all" links.
5. Manual test on a session with all card states represented.

Total scope: ~150 lines of JS, ~80 lines of CSS. ~1 hour of work.
