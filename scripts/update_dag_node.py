#!/usr/bin/env python3
"""Update a node's status (and status-specific fields) in a workflow DAG JSON.

Focused on driving a node through its TACC job lifecycle. Each target status
requires specific inputs and clears fields that no longer apply, so the node
always reflects a consistent job state. Meant to be called by an agent that
polls TACC (squeue/sacct) via MCP and records the result here.

Status lifecycle / required inputs
----------------------------------
    pending    (no inputs)      created, not submitted        [resets job fields]
    ready      (no inputs)      deps satisfied, submittable   [resets job fields]
    blocked    --blocked-on     waiting on external input
    queued     --job-id         submitted, in SLURM queue (PD)
               --expected-start   -> squeue --start est. start
    running    --elapsed-time   executing (R) -> squeue %M elapsed
    completed  --running-time   finished OK (CD) -> sacct elapsed
    failed     (no inputs)      crashed / timeout / cancelled -- RETRYABLE
    terminated --terminated-reason
                                judged INVALID and retired from the live graph.
                                Distinct from 'failed': the run may have finished
                                cleanly, but its result is not usable (wrong cell,
                                superseded settings, dead-end approach). A
                                terminated node never reaches 'completed', so
                                nothing downstream of it can ever become ready.

Examples
--------
    python update_dag_node.py DAG.json --name relax_dopant --status queued \\
        --job-id 1234567 --job-name relax_dopant --expected-start "2026-07-05 08:30"
    python update_dag_node.py DAG.json --id 1 --status running --elapsed-time 02:14:00
    python update_dag_node.py DAG.json --id 1 --status completed --running-time 07:41:12
    python update_dag_node.py DAG.json --id 4 --status terminated \\
        --terminated-reason "216-atom supercell too small; superseded by 3x3x5"

Add --dry-run to preview, --render for the diagram, --print-node to emit the
updated node as JSON on stdout (for the calling agent to consume).
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from insert_dag_node import validate, _ordered, _nid      # noqa: E402

STATUSES = ["pending", "ready", "queued", "running", "completed", "failed",
            "blocked", "terminated"]

# inputs that MUST be supplied to enter each status
REQUIRED = {
    "pending":   [],
    "ready":     [],
    "blocked":   ["blocked_on"],
    "queued":    ["job_id", "expected_start"],
    "running":   ["elapsed_time"],
    "completed": ["running_time"],
    "failed":    [],
    "terminated": ["terminated_reason"],
}

# fields cleared on entering each status (stale for that state), unless --no-clear
CLEAR = {
    "pending":   ["job_id", "expected_start", "elapsed_time", "running_time"],
    "ready":     ["job_id", "expected_start", "elapsed_time", "running_time"],
    "blocked":   [],
    "queued":    ["elapsed_time", "running_time"],
    "running":   ["expected_start"],
    "completed": ["expected_start", "elapsed_time"],
    "failed":    ["expected_start"],
    # keep job_id / running_time: a terminated node's provenance still matters
    "terminated": ["expected_start", "elapsed_time"],
}

# CLI flag (dest) -> node field  (all optional writable fields)
SETTABLE = {
    "tool": "tool",
    "cluster": "cluster",
    "allocation": "allocation",
    "partition": "partition",
    "num_nodes": "num_nodes",
    "job_id": "job_id",
    "job_name": "job_name",
    "expected_start": "expected_start",
    "request_time": "request_time",
    "elapsed_time": "elapsed_time",
    "running_time": "running_time",
    "blocked_on": "blocked_on",
    "terminated_reason": "terminated_reason",
}

# node-side field name -> the CLI flag the user should pass (for error messages)
_FLAG = {
    "job_id": "--job-id", "expected_start": "--expected-start",
    "elapsed_time": "--elapsed-time", "running_time": "--running-time",
    "blocked_on": "--blocked-on", "terminated_reason": "--terminated-reason",
}

# statuses whose explanatory field lives on the node only while that status holds
_STICKY = {"blocked": "blocked_on", "terminated": "terminated_reason"}


def _find(nodes, nid, name):
    if nid is not None:
        hits = [n for n in nodes if _nid(n) == nid]
        if not hits:
            sys.exit(f"error: no node with id {nid}")
        return hits[0]
    hits = [n for n in nodes if n.get("name") == name]
    if not hits:
        sys.exit(f"error: no node named '{name}'")
    return hits[0]


def update(node, args):
    status = args.status
    if status not in STATUSES:
        sys.exit(f"error: unknown status '{status}'; choose from {STATUSES}")

    # collect the explicitly-provided field values
    provided = {field: getattr(args, dest)
                for dest, field in SETTABLE.items()
                if getattr(args, dest) is not None}

    # enforce required inputs for the target status (either passed now, or,
    # for blocked_on, already present on the node)
    missing = []
    for req in REQUIRED[status]:
        if req in provided and provided[req] != "":
            continue
        if req in _STICKY.values() and node.get(req):
            continue
        missing.append(_FLAG.get(req, "--" + req.replace("_", "-")))
    if missing:
        sys.exit(f"error: status '{status}' requires: {', '.join(missing)}")

    # apply the writes
    node["status"] = status
    for field, val in provided.items():
        if field in _STICKY.values() and val == "":
            node.pop(field, None)
        else:
            node[field] = val

    # blocked_on / terminated_reason are only meaningful in their own status
    for st, field in _STICKY.items():
        if status != st and field in node and field not in provided:
            node.pop(field, None)

    # clear fields that no longer apply (skip anything just provided)
    if not args.no_clear:
        for field in CLEAR[status]:
            if field not in provided:
                node[field] = ""

    # A local node legitimately runs with no job id -- check_dag.py carries the
    # same exemption. A warning that fires on every correct write is how people
    # learn to ignore warnings.
    if (node.get("job_id") in (None, "") and status == "running"
            and node.get("cluster") != "local"):
        sys.stderr.write("warning: node set to 'running' but has no job_id\n")

    return node


def live_downstream(dag, node_id):
    """Ids of every node reachable from `node_id` that is not itself terminated.

    Terminating a node makes it a dead end: it can never reach 'completed', so
    by the readiness rule nothing below it can ever become ready. These are the
    nodes the caller must now retire as well or re-wire onto a replacement."""
    by_id = {_nid(n): n for n in dag.get("nodes", [])}
    start = by_id.get(node_id)
    if start is None:
        return []
    seen, out, stack = set(), [], list(start.get("next", []))
    while stack:
        s = stack.pop()
        if s in seen or s not in by_id:
            continue
        seen.add(s)
        if by_id[s].get("status") != "terminated":
            out.append(s)
        stack.extend(by_id[s].get("next", []))
    return sorted(out)


def warn_stranded(dag, node):
    """Print the downstream fallout of terminating `node`. Returns the id list."""
    stranded = live_downstream(dag, _nid(node))
    if not stranded:
        return stranded
    by_id = {_nid(n): n for n in dag.get("nodes", [])}
    sys.stderr.write("warning: %d downstream node(s) now depend on a terminated "
                     "node and can never become ready:\n" % len(stranded))
    for s in stranded:
        sys.stderr.write("    #%s %s\n" % (s, by_id[s].get("name", "?")))
    sys.stderr.write("  -> terminate them too, or re-wire their prev onto a "
                     "replacement node.\n")
    return stranded


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="path to workflow_dag.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int, help="id of the node to update")
    g.add_argument("--name", help="name of the node to update")
    ap.add_argument("--status", required=True, help="target status: " + "|".join(STATUSES))
    ap.add_argument("--tool", dest="tool",
                    help="software this node runs; selects the health probe")
    ap.add_argument("--cluster", dest="cluster",
                    help="where this node runs: local | lonestar6 | ... "
                         "(the cluster, not an ssh alias)")
    ap.add_argument("--allocation", dest="allocation",
                    help="TACC allocation charged; '-' for a local node")
    ap.add_argument("--partition", dest="partition")
    ap.add_argument("--num-nodes", dest="num_nodes")
    ap.add_argument("--job-id", dest="job_id")
    ap.add_argument("--job-name", dest="job_name")
    ap.add_argument("--expected-start", dest="expected_start")
    ap.add_argument("--request-time", dest="request_time")
    ap.add_argument("--elapsed-time", dest="elapsed_time")
    ap.add_argument("--running-time", dest="running_time")
    ap.add_argument("--blocked-on", dest="blocked_on")
    ap.add_argument("--terminated-reason", dest="terminated_reason",
                    help="why this node was judged invalid (required for "
                         "--status terminated)")
    ap.add_argument("--no-clear", action="store_true",
                    help="do not auto-clear fields that no longer apply")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write")
    ap.add_argument("--render", action="store_true", help="render the diagram afterwards")
    ap.add_argument("--print-node", action="store_true",
                    help="print the updated node as JSON on stdout")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit(f"error: {args.path} not found")
    with open(args.path) as f:
        dag = json.load(f)
    legend = dag.get("status_legend", STATUSES)
    if args.status not in legend:
        sys.exit(f"error: status '{args.status}' not in this DAG's legend {legend}")

    node = _find(dag["nodes"], args.id, args.name)
    update(node, args)
    dag["nodes"] = [_ordered(n) for n in dag["nodes"]]
    validate(dag)

    if node["status"] == "terminated":
        warn_stranded(dag, node)

    ordered_node = _ordered(node)
    text = json.dumps(dag, indent=2) + "\n"
    if args.dry_run:
        sys.stderr.write(f"[dry-run] '{node['name']}' -> status={node['status']}\n")
    else:
        with open(args.path, "w") as f:
            f.write(text)
        sys.stderr.write(f"updated '{node['name']}' -> status={node['status']} "
                         f"({args.path})\n")

    if args.print_node:
        print(json.dumps(ordered_node, indent=2))

    if args.render:
        import render_dag
        print(render_dag.render(dag))


if __name__ == "__main__":
    main()
