#!/usr/bin/env python3
"""Local web visualizer for the workflow DAGs in project_workflow/.

A tiny standard-library HTTP server (no pip installs) that serves the built
React UI and a small JSON API. The UI renders each exploration's workflow_dag.json
as an interactive 2-D dependency graph and lets you click a node to view its
description and edit + save its fields back to disk.

Run (end user):
    python3 dag_viewer/serve.py
then open the printed URL (default http://127.0.0.1:8765).

Portability notes
-----------------
* No absolute Python path is baked in anywhere -- you launch this with your own
  interpreter, so system / conda / venv Python all work, from any clone location.
* Zero third-party dependencies at runtime; the browser talks to this server via
  relative /api URLs, so it never references Python or any filesystem path.
* Writes reuse the SAME logic the CLI tools use (insert_dag_node.validate /
  _ordered and update_dag_node's status-lifecycle rules), so a node edited in the
  browser is byte-for-byte consistent with one edited via the scripts.
* Only node metadata is editable here; graph topology (prev/next/level/id) is
  left to insert_dag_node.py / delete_dag_node.py so validation is never bypassed.
* Binds to 127.0.0.1 only -- it is a personal tool, not a network service.
"""
import argparse
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

if sys.version_info < (3, 7):
    sys.exit("dag_viewer requires Python 3.7+ (found %d.%d). Launch it with a "
             "newer interpreter, e.g. `python3.9 dag_viewer/serve.py`."
             % sys.version_info[:2])

_HERE = os.path.dirname(os.path.abspath(__file__))       # .../<repo>/dag_viewer
_ROOT = os.path.dirname(_HERE)                           # .../<repo>
_SCRIPTS = os.path.join(_ROOT, "scripts")
_DIST = os.path.join(_HERE, "web", "dist")               # committed Vite build

# Reuse the repo's graph/lifecycle logic so the viewer never diverges from the CLI.
sys.path.insert(0, _SCRIPTS)
try:
    from insert_dag_node import validate, _ordered, _nid      # noqa: E402
    import update_dag_node                                     # noqa: E402
except ImportError as e:
    sys.exit("could not import the DAG CLI helpers from %s (%s).\n"
             "dag_viewer expects to live alongside scripts/ in the repo."
             % (_SCRIPTS, e))

STATUSES = update_dag_node.STATUSES
REQUIRED = update_dag_node.REQUIRED
CLEAR = update_dag_node.CLEAR

# Fields the detail pop-up may write. Topology/identity stay read-only.
PLAIN_FIELDS = ["name", "description", "tool", "cluster", "allocation"]
LIFECYCLE_FIELDS = ["partition", "num_nodes",
                    "job_id", "job_name", "expected_start", "request_time",
                    "elapsed_time", "running_time", "blocked_on",
                    "terminated_reason"]
READONLY_FIELDS = ["id", "level", "prev", "next"]

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}


# --------------------------------------------------------------------------- #
# DAG discovery / IO
# --------------------------------------------------------------------------- #
def list_explorations(exploration_dir):
    """Every <exploration>/workflow_dag.json under exploration_dir, with a status summary."""
    out = []
    if not os.path.isdir(exploration_dir):
        return out
    for name in sorted(os.listdir(exploration_dir)):
        path = os.path.join(exploration_dir, name, "workflow_dag.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                dag = json.load(f)
        except (OSError, ValueError):
            continue
        nodes = dag.get("nodes", [])
        counts = {}
        for n in nodes:
            counts[n.get("status", "?")] = counts.get(n.get("status", "?"), 0) + 1
        out.append({
            "exploration": dag.get("exploration", name),
            "dir": name,
            "description": dag.get("description", ""),
            "node_count": len(nodes),
            "status_counts": counts,
            "legacy": any("id" not in n for n in nodes),
        })
    return out


def dag_path(exploration_dir, dirname):
    """Resolve <dirname>'s DAG file, guarding against path traversal."""
    root = os.path.abspath(exploration_dir)
    path = os.path.abspath(os.path.join(root, dirname, "workflow_dag.json"))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("invalid exploration")
    if not os.path.isfile(path):
        raise ValueError("no such exploration: %s" % dirname)
    return path


def load_dag(path):
    with open(path) as f:
        return json.load(f)


def write_dag_atomic(path, dag):
    text = json.dumps(dag, indent=2) + "\n"          # matches the CLI writer exactly
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Editing
# --------------------------------------------------------------------------- #
def find_node(dag, node_id):
    for n in dag.get("nodes", []):
        if _nid(n) == node_id:
            return n
    raise ValueError("no node with id %r" % node_id)


def _apply_status_change(node, target, fields):
    """Drive a real status transition through update_dag_node's lifecycle rules
    (required inputs + auto-clear of stale fields). Reuses the CLI logic so the
    two paths cannot diverge; SystemExit (its error channel) becomes ValueError."""
    import types
    ns = types.SimpleNamespace(
        status=target, no_clear=False,
        **{f: fields.get(f) for f in LIFECYCLE_FIELDS})
    try:
        update_dag_node.update(node, ns)
    except SystemExit as e:
        raise ValueError(str(e.code) if e.code else "invalid status update")


def apply_edit(dag, node_id, fields):
    """Apply a detail-pop-up edit to one node, then validate the whole DAG.

    Two paths:
      * status unchanged -> plain metadata edit, set provided fields directly.
      * status changed    -> full lifecycle transition (enforces / clears fields).
    """
    node = find_node(dag, node_id)
    legend = dag.get("status_legend", STATUSES)

    # 1. free-text metadata (never subject to lifecycle clearing)
    for f in PLAIN_FIELDS:
        if f in fields:
            node[f] = fields[f]

    # 2. status + job/timing fields
    target = fields.get("status", node.get("status"))
    if "status" in fields and target not in legend:
        raise ValueError("status %r not in this DAG's legend %s" % (target, legend))
    status_changing = ("status" in fields) and (fields["status"] != node.get("status"))

    if status_changing:
        _apply_status_change(node, target, fields)
    else:
        for f in LIFECYCLE_FIELDS:
            if f in fields:
                v = fields[f]
                if f in ("blocked_on", "terminated_reason") and not v:
                    node.pop(f, None)
                else:
                    node[f] = v

    # 3. normalize + validate the graph (never write a broken DAG)
    legacy = any("id" not in n for n in dag.get("nodes", []))
    if not legacy:                       # keep legacy (stage-based) files unreshaped
        dag["nodes"] = [_ordered(n) for n in dag["nodes"]]
    validate(dag)
    return node


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    exploration_dir = None                    # set on the class before serving

    def log_message(self, fmt, *args):    # quieter, single-line access log
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers --
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _err(self, code, msg):
        self._send(code, {"ok": False, "error": msg})

    def _serve_static(self, urlpath):
        """Serve a file from the committed Vite build (web/dist/)."""
        rel = urlpath.lstrip("/") or "index.html"
        full = os.path.abspath(os.path.join(_DIST, rel))
        if os.path.commonpath([_DIST, full]) != _DIST:
            self._err(403, "forbidden")
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            # SPA fallback: unknown non-asset path -> index.html
            if "." not in os.path.basename(full):
                full = os.path.join(_DIST, "index.html")
            if not os.path.isfile(full):
                self._err(404, "not found: %s (is web/dist/ built? run "
                               "`npm run build` in dag_viewer/web/)" % urlpath)
                return
        ctype = _MIME.get(os.path.splitext(full)[1].lower(),
                          "application/octet-stream")
        try:
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError as e:
            self._err(500, str(e))

    # -- routes --
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/api/config":
            self._send(200, {
                "statuses": STATUSES,
                "required": REQUIRED,
                "clear": CLEAR,
                "plain_fields": PLAIN_FIELDS,
                "lifecycle_fields": LIFECYCLE_FIELDS,
                "readonly_fields": READONLY_FIELDS,
            })
            return

        if u.path == "/api/explorations":
            self._send(200, {"ok": True, "explorations": list_explorations(self.exploration_dir)})
            return

        if u.path == "/api/dag":
            qs = parse_qs(u.query)
            dirname = (qs.get("exploration") or [""])[0]
            try:
                dag = load_dag(dag_path(self.exploration_dir, dirname))
            except ValueError as e:
                self._err(404, str(e))
                return
            except OSError as e:
                self._err(500, str(e))
                return
            self._send(200, {"ok": True, "dir": dirname, "dag": dag})
            return

        if u.path.startswith("/api/"):
            self._err(404, "not found: %s" % u.path)
            return

        self._serve_static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/node":
            self._err(404, "not found: %s" % u.path)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._err(400, "invalid JSON body")
            return

        dirname = body.get("exploration")
        node_id = body.get("id")
        fields = body.get("fields") or {}
        if not dirname or node_id is None:
            self._err(400, "body needs 'exploration' and 'id'")
            return
        try:
            path = dag_path(self.exploration_dir, dirname)
            dag = load_dag(path)
            apply_edit(dag, node_id, fields)
            write_dag_atomic(path, dag)
        except ValueError as e:
            self._err(400, str(e))
            return
        except OSError as e:
            self._err(500, str(e))
            return
        self._send(200, {"ok": True, "dir": dirname, "dag": dag})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exploration-dir", default=os.path.join(_ROOT, "project_workflow"),
                    help="directory holding <exploration>/workflow_dag.json "
                         "(default: the repo's project_workflow/)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("DAG_VIEWER_PORT", 8765)))
    ap.add_argument("--no-browser", action="store_true",
                    help="do not auto-open a browser")
    args = ap.parse_args()

    Handler.exploration_dir = os.path.abspath(args.exploration_dir)
    explorations = list_explorations(Handler.exploration_dir)

    url = "http://%s:%d" % (args.host, args.port)
    print("=" * 62)
    print(" Workflow DAG viewer")
    print("   serving : %s" % url)
    print("   explorations: %s (%d found)" % (Handler.exploration_dir, len(explorations)))
    for p in explorations:
        print("       - %s (%d nodes)" % (p["dir"], p["node_count"]))
    if not explorations:
        print("       (none found -- pass --exploration-dir to point elsewhere)")
    if not os.path.isfile(os.path.join(_DIST, "index.html")):
        print("   NOTE: web/dist/ not built yet -- run `npm run build` in "
              "dag_viewer/web/")
    print("   Ctrl-C to stop")
    print("=" * 62)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
