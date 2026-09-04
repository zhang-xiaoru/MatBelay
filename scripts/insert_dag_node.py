#!/usr/bin/env python3
"""Insert a node into a workflow DAG JSON (see templates/dag_template.json).

The DAG is an acyclic graph keyed by a UNIQUE integer `id`; `prev`/`next`
are lists of node ids. Each node also carries a `level` (tree depth: parallel
nodes share a level; level = max(parent levels)+1). This tool adds a node,
derives its level from its parents (unless --level is given), wires the edges
in BOTH directions, and (optionally) opens an id slot by shifting later ids.

Examples
--------
Append a terminal node after node 4:
    python insert_dag_node.py DAG.json --name plot_bands \\
        --description "Plot band-offset summary" --prev 4

Splice a node onto the edge 1 -> 3 (re-routes 1 -> NEW -> 3), opening slot 3
and bumping old ids 3,4 to 4,5:
    python insert_dag_node.py DAG.json --name check \\
        --description "Force sanity check" --between 1:3

Insert at an explicit free id with manual wiring:
    python insert_dag_node.py DAG.json --name aux --id 5 --prev 3 --next 4

Add `--dry-run` to preview (prints JSON, writes nothing) or `--render` to
show the ASCII diagram afterwards.
"""
import argparse
import json
import os
import sys

# canonical field order for a node (mirrors templates/dag_template.json)
FIELD_ORDER = [
    "name", "description", "status", "id", "level", "tool", "cluster", "allocation",
    "partition", "num_nodes", "expected_start", "request_time", "job_id", "job_name",
    "elapsed_time", "running_time", "blocked_on", "terminated_reason",
    "prev", "next",
]


def _nid(n):
    """Node identity key (edges reference this). Falls back to legacy `stage`."""
    return n.get("id", n.get("stage"))


def _ints(s):
    return [int(x) for x in s.split(",") if x.strip() != ""] if s else []


def _ordered(node):
    """Return node dict in canonical field order (unknown keys appended)."""
    out = {k: node[k] for k in FIELD_ORDER if k in node}
    for k, v in node.items():
        if k not in out:
            out[k] = v
    return out


def validate(dag):
    """Raise ValueError on a malformed/cyclic DAG or inconsistent tree levels."""
    nodes = dag.get("nodes", [])
    ids = [_nid(n) for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate node ids: "
                         + str([s for s in ids if ids.count(s) > 1]))
    sset = set(ids)
    for n in nodes:
        s = _nid(n)
        for p in n.get("prev", []):
            if p == s:
                raise ValueError(f"node {s} lists itself in prev (self-cycle)")
            if p not in sset:
                raise ValueError(f"node {s} prev references missing node {p}")
        for q in n.get("next", []):
            if q == s:
                raise ValueError(f"node {s} lists itself in next (self-cycle)")
            if q not in sset:
                raise ValueError(f"node {s} next references missing node {q}")
    # Kahn topological sort to confirm acyclicity
    succ = {_nid(n): list(n.get("next", [])) for n in nodes}
    indeg = {s: 0 for s in sset}
    for s in succ:
        for q in succ[s]:
            indeg[q] += 1
    queue = [s for s in indeg if indeg[s] == 0]
    seen = 0
    while queue:
        s = queue.pop()
        seen += 1
        for q in succ[s]:
            indeg[q] -= 1
            if indeg[q] == 0:
                queue.append(q)
    if seen != len(sset):
        raise ValueError("graph is cyclic (topological sort incomplete)")
    # tree-level consistency: level == max(parent levels)+1 (root=0). Only
    # enforced when every node carries an explicit `level`.
    if all("level" in n for n in nodes):
        lvl = {_nid(n): n["level"] for n in nodes}
        prev_of = {_nid(n): list(n.get("prev", [])) for n in nodes}
        for n in nodes:
            s = _nid(n)
            parents = prev_of[s]
            want = 0 if not parents else max(lvl[p] for p in parents) + 1
            if lvl[s] != want:
                raise ValueError(
                    f"node {s} ({n['name']}) has level {lvl[s]} but its parents "
                    f"imply level {want}")


def relevel(dag):
    """Recompute every node's `level` as its longest-path depth from a root.

    level(root) = 0; level(n) = max(level(parent)) + 1. Called after any
    structural edit so the tree-level invariant validate() enforces holds
    (a spliced-in node deepens all of its descendants)."""
    from collections import deque
    nodes = dag["nodes"]
    succ = {_nid(n): list(n.get("next", [])) for n in nodes}
    indeg = {_nid(n): 0 for n in nodes}
    for s in succ:
        for q in succ[s]:
            indeg[q] += 1
    level = {}
    queue = deque()
    for s in indeg:
        if indeg[s] == 0:
            level[s] = 0
            queue.append(s)
    while queue:
        s = queue.popleft()
        for q in succ[s]:
            level[q] = max(level.get(q, 0), level[s] + 1)
            indeg[q] -= 1
            if indeg[q] == 0:
                queue.append(q)
    for n in nodes:
        n["level"] = level.get(_nid(n), 0)


def build_node(args, nid, level, prev, nxt):
    node = {
        "name": args.name,
        "description": args.description or "",
        "status": args.status,
        "id": nid,
        "level": level,
        "tool": args.tool or "",
        "cluster": args.cluster or "",
        "allocation": args.allocation or "",
        "partition": args.partition or "",
        "num_nodes": args.num_nodes or "",
        "expected_start": args.expected_start or "",
        "request_time": args.request_time or "",
        "job_id": args.job_id or "",
        "job_name": args.job_name or "",
        "elapsed_time": args.elapsed_time or "",
        "running_time": args.running_time or "",
    }
    if args.blocked_on:
        node["blocked_on"] = args.blocked_on
    node["prev"] = sorted(set(prev))
    node["next"] = sorted(set(nxt))
    return _ordered(node)


def insert(dag, args):
    nodes = dag["nodes"]
    ids = {_nid(n) for n in nodes}
    if any(n["name"] == args.name for n in nodes):
        sys.exit(f"error: a node named '{args.name}' already exists")

    between = None
    if args.between:
        try:
            a, b = args.between.split(":")
            between = (int(a), int(b))
        except ValueError:
            sys.exit("error: --between must look like A:B (e.g. 1:3)")
        if between[0] not in ids or between[1] not in ids:
            sys.exit(f"error: --between endpoints {between} not both present")

    # choose the target id slot
    if args.id is not None:
        slot = args.id
    elif between is not None:
        slot = between[1]                 # take B's slot; B shifts up
    else:
        slot = (max(ids) + 1) if ids else 0

    occupied = slot in ids
    if occupied and not args.shift and args.id is not None and between is None:
        sys.exit(f"error: id {slot} already exists; pass --shift to open a "
                 f"slot, or choose a free --id")
    do_shift = args.shift or occupied

    def bump(x):
        return x + 1 if do_shift and x >= slot else x

    if do_shift:
        for n in nodes:
            n["id"] = bump(_nid(n))
            n.pop("stage", None)
            n["prev"] = [bump(p) for p in n.get("prev", [])]
            n["next"] = [bump(q) for q in n.get("next", [])]

    prev = [bump(p) for p in _ints(args.prev)]
    nxt = [bump(q) for q in _ints(args.next)]
    if between is not None:
        a, b = bump(between[0]), bump(between[1])
        prev.append(a)
        nxt.append(b)
        # re-route: drop the direct a -> b edge that the new node now bridges
        for n in nodes:
            if _nid(n) == a:
                n["next"] = [q for q in n.get("next", []) if q != b]
            if _nid(n) == b:
                n["prev"] = [p for p in n.get("prev", []) if p != a]

    # tree level: explicit --level wins, else max(parent levels)+1, else 0 (root)
    by_id = {_nid(n): n for n in nodes}
    if args.level is not None:
        level = args.level
    elif prev:
        level = max(by_id[p].get("level", 0) for p in prev if p in by_id) + 1
    else:
        level = 0

    new = build_node(args, slot, level, prev, nxt)

    # wire edges bidirectionally on the neighbours
    for p in new["prev"]:
        if p not in by_id:
            sys.exit(f"error: prev references missing id {p}")
        nx = by_id[p].setdefault("next", [])
        if slot not in nx:
            nx.append(slot)
            by_id[p]["next"] = sorted(nx)
    for q in new["next"]:
        if q not in by_id:
            sys.exit(f"error: next references missing id {q}")
        pv = by_id[q].setdefault("prev", [])
        if slot not in pv:
            pv.append(slot)
            by_id[q]["prev"] = sorted(pv)

    nodes.append(new)
    relevel(dag)          # derive levels from structure (spliced nodes deepen descendants)
    nodes.sort(key=lambda n: (n.get("level", 0), _nid(n)))
    dag["nodes"] = [_ordered(n) for n in nodes]
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="path to workflow_dag.json")
    ap.add_argument("--name", required=True, help="unique node name")
    ap.add_argument("--description", default="")
    ap.add_argument("--status", default="pending",
                    help="pending|ready|queued|running|completed|failed|blocked "
                         "(a new node is never born 'terminated'; use "
                         "update_dag_node.py to retire one)")
    ap.add_argument("--id", type=int,
                    help="explicit node id; omit to append or use with --between")
    ap.add_argument("--level", type=int,
                    help="initial tree level hint; final level is always re-derived "
                         "from structure (longest path from root)")
    ap.add_argument("--prev", default="", help="comma-separated upstream node ids")
    ap.add_argument("--next", default="", help="comma-separated downstream node ids")
    ap.add_argument("--between", help="A:B — splice onto the edge A->B (re-routes it)")
    ap.add_argument("--shift", action="store_true",
                    help="open the target slot by bumping all ids >= it up by 1")
    ap.add_argument("--tool", default="",
                    help="software this node runs (vasp | phonopy | ...); '' for a "
                         "node that submits no batch job. Selects the health probe")
    ap.add_argument("--cluster", default="")
    ap.add_argument("--allocation", default="")
    ap.add_argument("--partition", default="",
                    help="SLURM partition/queue (normal | development | gpu-a100 | ...)")
    ap.add_argument("--num-nodes", dest="num_nodes", default="",
                    help="compute nodes requested (SLURM -N), e.g. 4")
    ap.add_argument("--expected-start", dest="expected_start", default="")
    ap.add_argument("--request-time", dest="request_time", default="")
    ap.add_argument("--job-id", dest="job_id", default="")
    ap.add_argument("--job-name", dest="job_name", default="")
    ap.add_argument("--elapsed-time", dest="elapsed_time", default="")
    ap.add_argument("--running-time", dest="running_time", default="")
    ap.add_argument("--blocked-on", dest="blocked_on", default="")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write")
    ap.add_argument("--render", action="store_true",
                    help="render the ASCII diagram after inserting")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit(f"error: {args.path} not found")
    with open(args.path) as f:
        dag = json.load(f)

    new = insert(dag, args)
    validate(dag)

    text = json.dumps(dag, indent=2) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        sys.stderr.write(f"\n[dry-run] would insert '{new['name']}' at id "
                         f"{new['id']} level {new['level']} "
                         f"(prev={new['prev']}, next={new['next']})\n")
        return
    with open(args.path, "w") as f:
        f.write(text)
    print(f"inserted '{new['name']}' at id {new['id']} level {new['level']} "
          f"(prev={new['prev']}, next={new['next']}) -> {args.path}")

    if args.render:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        import render_dag
        print()
        print(render_dag.render(dag))


if __name__ == "__main__":
    main()
