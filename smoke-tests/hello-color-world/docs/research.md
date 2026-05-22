# Basic Website Creation Research

## Static Site Shape

A small static webpage only needs:

- `index.html` for semantic document structure.
- `styles.css` for presentation.
- `script.js` for optional behavior or validation.

## Implementation Notes

- Keep text content accessible by preserving a readable phrase in the DOM.
- Use one span per visible character when individual character styling is required.
- Link CSS in the document head so visual styling is ready during page render.
- Defer JavaScript so it runs after the DOM is available.
- For screenshot validation, prefer high contrast colors on a simple background.

## Validation Notes

- Confirm the page renders `Hello World`.
- Confirm there are eleven visible character spans, including the space.
- Confirm every character span has a distinct computed color.
- Capture a screenshot after load.

