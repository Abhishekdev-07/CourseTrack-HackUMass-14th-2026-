# CourseTrack

Upload a curriculum PDF, get an interactive degree tree. Check off what you've completed, see what it unlocks, and try what-if plans.

## Run locally
    pip install -r requirements.txt
    python app.py
Open http://127.0.0.1:5000, create an account (or continue as guest), and pick a program or click **Upload PDF**. Sample PDFs are in `samples/`.

## How it's built
- `app.py`      Flask routes, accounts (SQLite + hashed passwords), per-user saved state
- `extract.py`  PDF -> curriculum JSON. Reads the semester grid, the flowchart arrows and the notes straight from the PDF. No AI.
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
