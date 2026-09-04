# Workflow DAG Viewer

A local, browser-based visualizer for the workflow DAGs in `project_workflow/`.
It renders each exploration's `workflow_dag.json` as an interactive 2-D dependency
graph, shows each node's status and where it runs (local vs. an HPC cluster), and
lets you click a node to read its description and **edit + save its fields back to
disk**.

It is a thin **Python-stdlib** server (no pip installs) serving a prebuilt
**TypeScript + React** UI. Edits reuse the exact same logic as the CLI tools
(`scripts/insert_dag_node.py`, `scripts/update_dag_node.py`), so a node changed in
the browser is byte-for-byte identical to one changed on the command line.

## Run it (end users — no Node needed)

```bash
python3 dag_viewer/serve.py
```

Then open the URL it prints (default <http://127.0.0.1:8765>); it also tries to
open your browser automatically. That's it — the built UI ships in
`web/dist/`, and you launch with **your own** Python (system, conda, or venv;
Python ≥ 3.7). Nothing hard-codes an interpreter path, so it works from any clone
location on any OS.

Options:

| flag | meaning | default |
|------|---------|---------|
| `--exploration-dir DIR` | where `<exploration>/workflow_dag.json` files live | repo's `project_workflow/` |
| `--port N` (or `DAG_VIEWER_PORT`) | port to serve on | `8765` |
| `--host H` | bind address | `127.0.0.1` |
| `--no-browser` | don't auto-open a browser | off |

## What you can do

- **See the whole workflow** as a layered graph — parallel branches and
  fan-in/fan-out render side by side (unlike the terminal `render_dag.py` view).
- **Read each node at a glance**: status color, locality badge (🖥 local vs ☁
  cluster), allocation, job id, timing. Nodes whose dependencies are all
  `completed` but haven't started get a highlight ("ready to run").
- **Edit a node**: click it → a drawer opens with its description and fields.
  Editable: `name`, `description`, `status`, `cluster`, `allocation`, and the
  job/timing fields. Changing `status` enforces the same required inputs as the
  CLI (e.g. `queued` needs a job id + expected start) and shows the error inline
  if something's missing. **Save** writes `workflow_dag.json` atomically.

Graph **topology** (`prev`/`next`/`level`/`id`) is intentionally *not* editable
here — use `scripts/insert_dag_node.py` / `scripts/delete_dag_node.py` so graph
validation (acyclicity, level invariants) is never bypassed.

## Develop the UI (needs Node)

Only required if you want to change the interface.

```bash
cd dag_viewer/web
npm install
npm run dev        # Vite dev server on :5173, proxies /api to serve.py on :8765
# ...edit src/...
npm run build      # rebuilds web/dist/ (commit this so end users need no Node)
npm run typecheck  # optional: tsc --noEmit
```

During development run the Python server (`python3 dag_viewer/serve.py`) in one
terminal and `npm run dev` in another, then use the Vite URL.

## Layout

```
dag_viewer/
├── serve.py     # stdlib HTTP server: JSON API + serves web/dist/
├── README.md
└── web/         # TypeScript + React + Vite source
    ├── src/     # App, Graph (React Flow), NodeCard, DetailDrawer, Toolbar, api/types/status/layout
    └── dist/    # committed production build (what serve.py serves)
```

## Notes

- Handles both the current node schema (`id` + `level`) and the older `stage`-based
  variant; legacy files are edited without being reshaped.
- Binds to localhost only — it's a personal tool, not a network service.
