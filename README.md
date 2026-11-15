# CourseTrack

Upload a curriculum PDF, get an interactive degree tree. Check off what you've completed, see what it unlocks, and try what-if plans.

## Run locally
    pip install -r requirements.txt
    python app.py
Open http://127.0.0.1:5000, create an account (or continue as guest), and pick a program or click **Upload PDF**. Sample PDFs are in `samples/`.

## Planning tips
- Drag a course to another term to start your own plan; the official plan never changes. **Reset** puts a plan back, and every change can be undone (**Ctrl+Z** / **Ctrl+Shift+Z**, or the arrows in the header).
- Plan menu tools: **Reset** (one plan back to official), and in the plan panel under *Your data*: clear all checkmarks or **Start over** (all your plans for that program). The program menu's **Manage programs…** renames or deletes a shared program.
- Each term shows its credits and whether that load is `(within)` your normal limit, an `(overload)`, or `(over max)`. Only "over max" counts as a problem. Click a term's credits to set your own limits (defaults: 19 normal / 30 max for Fall and Spring).

## Tests
    pip install pytest playwright && python -m playwright install chromium
    python -m pytest            # browser tests are skipped if Playwright is missing

## How it's built
- `app.py`      Flask routes, accounts (SQLite + hashed passwords), per-user saved state
- `extract.py`  PDF -> curriculum JSON. Reads semester grids, plan-of-study tables (stacked or side by side, with or without a header row), flowchart arrows, notes and catalog text straight from the PDF. No AI.
- `llm.py`      Optional AI pass (off unless a key is set)
- `static/app.js`, `static/style.css`, `templates/index.html`  the whole front end, no build step

Data lives in `data/`: `programs/*.json` (shared), `coursetrack.db` (accounts, plans, checkmarks, notes), `secret.key` (session signing, created on first run).

## Colour code
green = completed, blue = ready to take, grey = locked, red = broken rule. Nothing else is coloured.

## Optional AI pass
Not required. Set ONE key to have a model read extra rules out of the footnotes, once per PDF, in the background:
    export GEMINI_API_KEY=...            # or
    export ANTHROPIC_API_KEY=sk-ant-...
    export COURSETRACK_MODEL=<model id>  # optional override

## Hosting
    gunicorn app:app
Set `SECRET_KEY` and point `COURSETRACK_DATA` at a folder that survives restarts. On hosts with a temporary disk the SQLite file is wiped on every redeploy.
