#!/usr/bin/env python3
"""Check a workflow_dag.json against the schema templates/dag_template.json presets.

insert/update/delete_dag_node.py keep a DAG well-formed as long as every edit
goes through them. This is the gate that catches what hand-editing breaks:
stray or missing node fields, a status outside the legend, a terminated node
with no reason, prev/next that disagree, a level that no longer matches the
graph. The template is the schema -- field names, canonical order and the
status legend are all read from it, so the two can never drift.

Reports ERRORs (schema is violated -- exit 1) and WARNs (legal but suspicious,
e.g. a node stranded below a terminated one, or a node that is 'pending' when
all of its dependencies are already 'completed'). Exit 0 means the file is
safe to commit.

Examples
--------
    python check_dag.py project_workflow/rTiO2/workflow_dag.json
    python check_dag.py project_workflow/*/workflow_dag.json --quiet
    python check_dag.py DAG.json --fix     # canonical field order + legend top-up
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)                 # repo root, for implementation/
sys.path.insert(0, _HERE)
from insert_dag_node import validate, _ordered, _nid, FIELD_ORDER   # noqa: E402
from new_dag import load_template                                   # noqa: E402
from update_dag_node import live_downstream, _STICKY                # noqa: E402


def schema(template=None):
    """Derive the schema from the template: (top keys, node order, base, optional)."""
    t = template if template is not None else load_template()
    top = [k for k in t if not k.startswith("_")]
    order = list(t.get("_node_format", {}))
    base = list(t["nodes"][0]) if t.get("nodes") else []
    optional = [k for k in order if k not in base]
    return top, order, base, optional, list(t.get("status_legend", []))


def dir_name(n):
    """The canonical directory name for a node: <level>_<id>_<name>."""
    return "%s_%s_%s" % (n.get("level"), _nid(n), n.get("name"))


def node_dir(exploration, n):
    """Where this node's prepared artifacts live, relative to the repo root."""
    return os.path.join(_ROOT, "implementation", exploration, dir_name(n))


def find_node_dir(exploration, n):
    """The node's run dir ON DISK, which may carry a STALE level prefix.

    A node's identity is `<id>_<name>`; the leading level is a convenience that
    makes the directory listing sort by graph depth. But `level` is re-derived
    from structure on every edit, so splicing a node in (a continuation round,
    `insert --between`, any `rewire`) deepens every descendant and silently
    invalidates their directory names.

    Matching on identity and tolerating a stale prefix is what keeps that edit
    from un-preparing a subtree that is in fact perfectly prepared. Returns the
    real path, or None."""
    exact = node_dir(exploration, n)
    if os.path.isdir(exact):
        return exact
    import glob as _glob
    hits = _glob.glob(os.path.join(_ROOT, "implementation", exploration,
                                   "*_%s_%s" % (_nid(n), n.get("name"))))
    hits = [h for h in hits if os.path.isdir(h)]
    return hits[0] if len(hits) == 1 else None


def is_prepared(exploration, n):
    """A node is PREPARED when its run dir holds a NODE.md record.

    Deliberately derived from the filesystem rather than stored in the DAG: a
    status field mirroring the disk goes stale the moment a directory moves,
    and nothing catches it. `ready` stays a pure graph fact."""
    d = find_node_dir(exploration, n)
    return bool(d) and os.path.isfile(os.path.join(d, "NODE.md"))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Queries used by the run driver (skill `run-workflow`), not by the schema check.
#
# Both are derived from the DAG on every call rather than stored anywhere. The
# run driver is re-entered constantly -- after each watcher event, after a
# context compaction hours later -- so anything it "remembers" is a bug. Asking
# the file is always correct; a cached answer is only sometimes correct.
# ---------------------------------------------------------------------------

def submittable(dag):
    """Nodes that could be submitted right now.

    Three conditions, all necessary:
      * every `prev` is 'completed'      -- the graph says it may run
      * a NODE.md exists                 -- it has actually been prepared
      * its own status is not already in flight or finished

    'failed' is excluded on purpose: it means a human decision is outstanding,
    and resubmitting unchanged would repeat whatever went wrong."""
    nodes = dag.get("nodes", [])
    by_id = {_nid(n): n for n in nodes if isinstance(n, dict)}
    expl = dag.get("exploration", dag.get("project", ""))
    out = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("status") not in ("pending", "ready"):
            continue
        if not all(by_id.get(p, {}).get("status") == "completed"
                   for p in n.get("prev", [])):
            continue
        if not is_prepared(expl, n):
            continue
        out.append(n)
    return sorted(out, key=lambda n: (n.get("level", 0), _nid(n)))


def in_flight(dag):
    """Nodes with a live SLURM job -- what the watcher should be watching."""
    return sorted(
        [n for n in dag.get("nodes", [])
         if isinstance(n, dict)
         and n.get("status") in ("queued", "running")
         and n.get("job_id")],
        key=lambda n: (n.get("level", 0), _nid(n)))


def _dirname(expl, n):
    """The directory to actually use -- on disk if it exists, else canonical.

    The remote tree mirrors the local one, so a row that named the canonical
    directory while a stale-prefixed one sat on disk would point the submitter
    and the watcher at a path that does not exist."""
    d = find_node_dir(expl, n)
    return os.path.basename(d) if d else dir_name(n)


def check(dag, path="<dag>", template=None):
    """Return (errors, warnings) as lists of strings."""
    top_keys, order, base, optional, legend = schema(template)
    err, warn = [], []
    E = lambda w, m: err.append("%s: %s" % (w, m))       # noqa: E731
    W = lambda w, m: warn.append("%s: %s" % (w, m))      # noqa: E731

    # ---- top level ------------------------------------------------------
    if not isinstance(dag, dict):
        return ["%s: top level is not a JSON object" % path], []
    extra = [k for k in dag if k not in top_keys]
    missing = [k for k in top_keys if k not in dag]
    if extra:
        E(path, "unexpected top-level key(s) %s; the template presets exactly %s"
          % (extra, top_keys))
    if missing:
        E(path, "missing top-level key(s) %s" % missing)
    if not isinstance(dag.get("nodes", []), list):
        E(path, "'nodes' must be a list")
        return err, warn

    dag_legend = dag.get("status_legend", [])
    if dag_legend != legend:
        E(path, "status_legend is %s but the template presets %s "
                "(run with --fix to top it up)" % (dag_legend, legend))
    allowed_status = set(dag_legend) | set(legend)

    nodes = dag.get("nodes", [])
    legacy = bool(nodes) and all("id" not in n and "stage" in n for n in nodes)
    if legacy:
        W(path, "legacy 'stage'-keyed schema (pre-2026-07-17); field checks "
                "relaxed. Edges and levels are still verified.")

    # ---- per node -------------------------------------------------------
    seen_names, seen_ids = {}, {}
    for i, n in enumerate(nodes):
        where = "%s[%d]" % (path, i)
        if not isinstance(n, dict):
            E(where, "node is not a JSON object")
            continue
        where = "%s '%s'" % (where, n.get("name", "?"))

        if not legacy:
            unknown = [k for k in n if k not in order]
            absent = [k for k in base if k not in n]
            if unknown:
                E(where, "unexpected field(s) %s; the template presets %s "
                         "(+ optional %s)" % (unknown, base, optional))
            if absent:
                E(where, "missing field(s) %s" % absent)
            got = [k for k in n if k in order]
            if got != [k for k in order if k in n]:
                W(where, "fields are out of canonical order (run --fix)")
            if not _is_int(n.get("id")):
                E(where, "'id' must be an integer, got %r" % (n.get("id"),))
            if not _is_int(n.get("level")):
                E(where, "'level' must be an integer, got %r" % (n.get("level"),))
            for k in order:
                if k in ("id", "level", "prev", "next"):
                    continue
                if k in n and not isinstance(n[k], str):
                    E(where, "'%s' must be a string, got %r" % (k, n[k]))

        for k in ("prev", "next"):
            v = n.get(k, [])
            if not isinstance(v, list) or not all(_is_int(x) for x in v):
                E(where, "'%s' must be a list of integer node ids, got %r" % (k, v))

        name = n.get("name", "")
        if not name:
            E(where, "'name' is empty")
        elif name in seen_names:
            E(where, "duplicate node name '%s' (also node index %d)"
              % (name, seen_names[name]))
        else:
            seen_names[name] = i
        sid = _nid(n)
        if sid in seen_ids:
            E(where, "duplicate node id %r (also '%s')" % (sid, seen_ids[sid]))
        else:
            seen_ids[sid] = name

        # ---- status + its sticky explanatory field ----------------------
        st = n.get("status", "")
        if st not in allowed_status:
            E(where, "status %r is not in the legend %s" % (st, sorted(allowed_status)))
        for status_name, field in _STICKY.items():
            if st == status_name:
                if not n.get(field):
                    E(where, "status '%s' requires a non-empty '%s'"
                      % (status_name, field))
            elif field in n:
                E(where, "'%s' is only valid while status == '%s' (status is '%s')"
                  % (field, status_name, st))
        if st == "terminated" and len(n.get("terminated_reason", "")) > 200:
            W(where, "terminated_reason is very long; keep it to one line and put "
                     "the detail in the node's run dir")

    # ---- graph integrity ------------------------------------------------
    by_id = {_nid(n): n for n in nodes if isinstance(n, dict)}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        sid = _nid(n)
        where = "%s '%s'" % (path, n.get("name", "?"))
        for p in n.get("prev", []):
            if p in by_id and sid not in by_id[p].get("next", []):
                E(where, "prev lists #%s but #%s's next does not list #%s "
                         "(edges must agree in both directions)" % (p, p, sid))
        for q in n.get("next", []):
            if q in by_id and sid not in by_id[q].get("prev", []):
                E(where, "next lists #%s but #%s's prev does not list #%s" % (q, q, sid))
    try:
        validate(dag)
    except ValueError as e:
        E(path, str(e))

    # ---- lint: statuses that disagree with the graph --------------------
    done = lambda i: by_id.get(i, {}).get("status") == "completed"   # noqa: E731
    # Only check prepared-ness when this exploration actually has an
    # implementation tree -- otherwise (a scratch copy, a fresh DAG) every node
    # would report "not prepared", which is noise rather than a finding.
    expl = dag.get("exploration", dag.get("project", ""))
    check_prep = bool(expl) and os.path.isdir(
        os.path.join(_ROOT, "implementation", expl))
    for n in nodes:
        if not isinstance(n, dict):
            continue
        where = "%s '%s'" % (path, n.get("name", "?"))
        st, prev = n.get("status", ""), n.get("prev", [])
        if st == "terminated":
            stranded = live_downstream(dag, _nid(n))
            if stranded:
                W(where, "terminated, but %d live node(s) still depend on it "
                         "(%s); terminate them too or re-wire their prev"
                  % (len(stranded), ", ".join("#%s %s" % (s, by_id[s].get("name", "?"))
                                              for s in stranded)))
        if st == "pending" and prev and all(done(p) for p in prev):
            W(where, "every dependency is completed -- this node should be 'ready'")
        if st == "ready":
            waiting = [p for p in prev if not done(p)]
            if waiting:
                W(where, "marked 'ready' but %s not completed"
                  % ", ".join("#%s" % p for p in waiting))
            elif check_prep and not is_prepared(expl, n):
                W(where, "ready but NOT PREPARED (no NODE.md in %s) -- prepare it "
                         "before submitting"
                  % os.path.relpath(node_dir(expl, n), _ROOT))
        if st == "running" and not n.get("job_id") and n.get("cluster") != "local":
            W(where, "'running' on a cluster but has no job_id")
        if check_prep:
            d = find_node_dir(expl, n)
            if d and os.path.basename(d) != dir_name(n):
                W(where, "run dir is '%s' but this node is now at level %s "
                         "(expected '%s') -- harmless, rename if you want the "
                         "listing to sort by depth"
                  % (os.path.basename(d), n.get("level"), dir_name(n)))
        # A remote node with no `tool` cannot be routed to a health probe, so
        # the watcher would silently fall back to the generic one. Cheap to fix
        # at plan time, invisible once a job is already running.
        cl = n.get("cluster", "")
        if cl and cl != "local" and not n.get("tool"):
            W(where, "runs on '%s' but declares no 'tool' -- job monitoring will "
                     "fall back to the generic probe (see reference/quick-ref.md)"
              % cl)
    return err, warn


def fix(dag, template=None):
    """Apply the safe, purely additive normalizations. Returns a change list."""
    _, order, _, _, legend = schema(template)
    changed = []
    if dag.get("status_legend") != legend:
        missing = [s for s in legend if s not in dag.get("status_legend", [])]
        if missing:
            dag["status_legend"] = list(dag.get("status_legend", [])) + missing
            changed.append("status_legend += %s" % missing)
    nodes = dag.get("nodes", [])
    # Legacy 'stage'-keyed files have no canonical order to restore -- _ordered()
    # would shunt their unknown `stage` key to the end. Leave them alone, exactly
    # as dag_viewer/serve.py does.
    legacy = bool(nodes) and all(isinstance(n, dict) and "id" not in n and "stage" in n
                                 for n in nodes)
    if not legacy:
        before = [list(n) for n in nodes if isinstance(n, dict)]
        dag["nodes"] = [_ordered(n) if isinstance(n, dict) else n for n in nodes]
        after = [list(n) for n in dag["nodes"] if isinstance(n, dict)]
        if before != after:
            changed.append("re-ordered node fields canonically")
    return changed


def _query(args):
    """Handle --list-submittable / --watchlist. Returns an exit code."""
    if args.watchlist and not args.remote_root:
        sys.stderr.write("error: --watchlist needs --remote-root (the remote "
                         "work root declared in CLAUDE.md)\n")
        return 2
    rows = 0
    for path in args.paths:
        if not os.path.isfile(path):
            sys.stderr.write("error: %s not found\n" % path)
            return 2
        with open(path) as f:
            dag = json.load(f)
        expl = dag.get("exploration", dag.get("project", ""))
        if args.list_submittable:
            for n in submittable(dag):
                print("%s\t%s\t%s\t%s\t%s\t%s" % (
                    expl, _dirname(expl, n), n.get("tool", ""), n.get("cluster", ""),
                    n.get("partition", ""), n.get("request_time", "")))
                rows += 1
        else:
            for n in in_flight(dag):
                d = _dirname(expl, n)
                print("%s %s %s %s/%s/%s %s" % (
                    n.get("job_id"), expl, d,
                    args.remote_root.rstrip("/"), expl, d, n.get("tool", "")))
                rows += 1
    # No rows is a legitimate answer -- nothing is ready, or nothing is running.
    # Say so on stderr so a human is not left wondering, but exit 0: an empty
    # set is not an error, and a caller that treats it as one would stall.
    if rows == 0:
        sys.stderr.write("(none)\n")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="workflow_dag.json file(s) to check")
    ap.add_argument("--fix", action="store_true",
                    help="apply safe normalizations (canonical field order, "
                         "top up status_legend) and re-check")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing on a clean file; exit code only")
    ap.add_argument("--warnings-as-errors", action="store_true")
    ap.add_argument("--list-submittable", action="store_true",
                    help="print nodes that could be submitted now (every prev "
                         "completed, NODE.md present, not already in flight) "
                         "and exit; skips the schema check")
    ap.add_argument("--watchlist", action="store_true",
                    help="print watchlist rows for every node with a live job, "
                         "for scripts/watch_jobs.sh. Requires --remote-root")
    ap.add_argument("--remote-root",
                    help="remote work root, e.g. /scratch/.../hpc_project. "
                         "Declared in CLAUDE.md; pass it rather than letting "
                         "this script carry a second copy of it")
    args = ap.parse_args()

    if args.list_submittable or args.watchlist:
        sys.exit(_query(args))

    template = load_template()
    worst = 0
    for path in args.paths:
        if not os.path.isfile(path):
            print("ERROR  %s: not found" % path)
            worst = 1
            continue
        with open(path) as f:
            try:
                dag = json.load(f)
            except ValueError as e:
                print("ERROR  %s: invalid JSON (%s)" % (path, e))
                worst = 1
                continue

        if args.fix:
            changed = fix(dag, template)
            if changed:
                with open(path, "w") as f:
                    f.write(json.dumps(dag, indent=2) + "\n")
                print("fixed  %s: %s" % (path, "; ".join(changed)))

        err, warn = check(dag, path, template)
        for m in err:
            print("ERROR  %s" % m)
        for m in warn:
            print("WARN   %s" % m)
        if err or (warn and args.warnings_as_errors):
            worst = 1
        elif not args.quiet:
            n = len(dag.get("nodes", []))
            print("ok     %s (%d node%s%s)"
                  % (path, n, "" if n == 1 else "s",
                     ", %d warning%s" % (len(warn), "" if len(warn) == 1 else "s")
                     if warn else ""))
    sys.exit(worst)


if __name__ == "__main__":
    main()
