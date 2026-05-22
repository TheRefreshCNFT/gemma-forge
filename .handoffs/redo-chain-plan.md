# Plan: Redo restarts the Context Writer chain

> Status: **planned, not started.**

## Why

Today a user-initiated "Redo" on any card only re-runs THAT card. If the
deliverable contract was wrong (or got stale because the model picked an
unhelpful framing), no amount of repeating Execution will fix it. The
contract needs to be rebuilt.

Ian's stated rule: when a redo is requested, **Context Writer kicks in
again, and the chain starts again** so the agent gets a fresh contract
plus optional user-provided correction context.

## Behavior change

For any card from `gsd` onward (i.e., anything downstream of `intake`):

1. The harness re-runs `intake` (Project Context Writer) FIRST.
2. If the user attached a correction note when clicking Redo (e.g.
   *"the SVG was too busy, simpler"*), that note is appended to the
   Project Context Writer's prompt as `correction_hint`:
   ```
   The previous run did not meet the user's needs. Their correction:
   "the SVG was too busy, simpler"
   Factor that into the new contract.
   ```
3. Context Writer produces a fresh contract on `session.projectContext`.
4. The originally-clicked card then runs against that fresh contract.
5. If the originally-clicked card is downstream (e.g. Execution),
   intermediate cards (GSD plan) that already produced artifacts are
   left as-is — only Intake and the clicked card re-run by default.
   (Future: optional "redo full chain from intake" toggle.)

For a redo on `intake` itself: just re-run Intake with the correction
hint. Same behavior.

## API surface

Add an optional body field on the existing
`POST /api/sessions/<id>/cards/<card_id>/run`:

```json
{
  "model": "gemma-4",
  "mode": "auto",
  "redo": true,
  "correctionHint": "the SVG was too busy, simpler"
}
```

When `redo: true`, the dispatcher in `run_session_card` short-circuits
to:

```python
if redo and card_id != "intake":
    intake_session = run_intake_card(session_id, session, model, mode,
                                      correction_hint=correction_hint)
    save_session()
    return run_card_action(session_id, session, card_id, model, mode)
```

## UI hook

The existing "Not Verified" button on Human Verify, and any
explicit "Redo" buttons in the card view, switch to passing
`{redo: true, correctionHint: <textarea content>}` instead of the
plain rerun payload.

## Cost guard

Re-running the Context Writer is ~8 s on gemma-4 at temp 0.1. Cheap
enough to do on every redo. If a user spam-clicks Redo three times, we
get three contract rebuilds and three Executions. Acceptable.

## Risk: stale review state

Currently the small-model auto-review runs after each card. When
Context Writer is re-fired by a Redo, the previous card's
`extraReview` artifacts should be invalidated:

- Clear `card["lastRun"]["extraReview"]` before re-running.
- Old reviews stay archived under
  `<session>/<card>-extra-review.<UTC>.old.md` so the audit trail
  survives. This dovetails with the handoff-rotation-plan.md design.

## What this does NOT change

- The Context Writer's reasoning template, schema, or temperature.
- Cards' individual handlers other than receiving an optional
  `correction_hint` parameter on Intake.
- Auto-run mode (cards still chain forward; Redo is only triggered
  by user action).
