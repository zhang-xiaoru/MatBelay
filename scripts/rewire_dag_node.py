#!/usr/bin/env python3
"""Re-point an existing node's dependencies in a workflow DAG JSON.

insert_dag_node.py wires edges when a node is born and delete_dag_node.py
unwires them when it dies, but neither can move an edge on a node that already
exists. That is the operation you need after retiring a node: its children are
still pointing at a dead parent and must be re-pointed at the replacement.

Every edit is applied to BOTH endpoints (a prev entry always has a matching
next entry), then levels are re-derived and the graph re-validated -- the
invariants hand-editing the JSON silently breaks.

Examples
--------
Swap a dead parent for its replacement on node 4:
    python rewire_dag_node.py DAG.json --id 4 --drop-prev 3 --add-prev 14

Set a node's parents outright (replaces the whole prev list):
    python rewire_dag_node.py DAG.json --name kappa_defect --prev 11,14

Re-assert a one-directional edge left behind by a hand-edit (prev is right,
the parent's next is missing) -- passing the same prev repairs both sides:
    python rewire_dag_node.py DAG.json --id 13 --prev 4,11

Add `--dry-run` to preview (prints JSON, writes nothing) or `--render` to show
the ASCII diagram afterwards.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from insert_dag_node import validate, _ordered, _nid, relevel, _ints   # noqa: E402
from delete_dag_node import _find                                      # noqa: E402


def _resolve(current, exact, add, drop, self_id):
    """New edge list: `exact` replaces outright, then add/drop are applied."""
    out = set(current) if exact is None else set(exact)
    out |= set(add)
    out -= set(drop)
    out.discard(self_id)                 # never let a node point at itself
    return sorted(out)


def rewire(dag, nid=None, name=None, prev=None, add_prev=(), drop_prev=(),
           nxt=None, add_next=(), drop_next=()):
    nodes = dag["nodes"]
    target = _find(nodes, nid, name)
    s = _nid(target)
    by_id = {_nid(n): n for n in nodes}

    new_prev = _resolve(target.get("prev", []), prev, add_prev, drop_prev, s)
    new_next = _resolve(target.get("next", []), nxt, add_next, drop_next, s)
    for x in set(new_prev) | set(new_next):
        if x not in by_id:
            sys.exit("error: no node with id %s" % x)
    overlap = set(new_prev) & set(new_next)
    if overlap:
        sys.exit("error: node(s) %s would be both upstream and downstream of "
                 "'%s' (that is a 2-cycle)" % (sorted(overlap), target["name"]))

    old_prev, old_next = set(target.get("prev", [])), set(target.get("next", []))
    target["prev"], target["next"] = new_prev, new_next

    # Mirror onto the neighbours. This ENFORCES the full desired state rather
    # than replaying a diff: after the command the target's own prev/next are
    # authoritative, so an edge a hand-edit left one-directional gets repaired
    # even when the target's list did not itself change.
    repaired = []
    want_prev, want_next = set(new_prev), set(new_next)
    for n in nodes:
        i = _nid(n)
        if i == s:
            continue
        nx, pv = set(n.get("next", [])), set(n.get("prev", []))
        if (s in nx) != (i in want_prev):
            if i in want_prev:
                nx.add(s)
                if i in old_prev:
                    repaired.append("#%s next += %s" % (i, s))
            else:
                nx.discard(s)
                if i not in old_prev:
                    repaired.append("#%s next -= %s" % (i, s))
            n["next"] = sorted(nx)
        if (s in pv) != (i in want_next):
            if i in want_next:
                pv.add(s)
                if i in old_next:
                    repaired.append("#%s prev += %s" % (i, s))
            else:
                pv.discard(s)
                if i not in old_next:
                    repaired.append("#%s prev -= %s" % (i, s))
            n["prev"] = sorted(pv)
    if repaired:
        sys.stderr.write("note: repaired one-directional edge(s): %s\n"
                         % ", ".join(repaired))

    if not new_prev and old_prev:
        sys.stderr.write("note: '%s' is now a root (level 0)\n" % target["name"])

    relevel(dag)             # re-pointing a parent moves this node's whole subtree
    nodes.sort(key=lambda n: (n.get("level", 0), _nid(n)))
    dag["nodes"] = [_ordered(n) for n in nodes]
    return target, sorted(old_prev), new_prev, sorted(old_next), new_next


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="path to workflow_dag.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int, help="id of the node to rewire")
    g.add_argument("--name", help="name of the node to rewire")
    ap.add_argument("--prev", help="replace the whole prev list (comma-separated ids)")
    ap.add_argument("--add-prev", dest="add_prev", default="", help="ids to add to prev")
    ap.add_argument("--drop-prev", dest="drop_prev", default="",
                    help="ids to remove from prev")
    ap.add_argument("--next", dest="nxt", help="replace the whole next list")
    ap.add_argument("--add-next", dest="add_next", default="", help="ids to add to next")
    ap.add_argument("--drop-next", dest="drop_next", default="",
                    help="ids to remove from next")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write")
    ap.add_argument("--render", action="store_true",
                    help="render the ASCII diagram afterwards")
    args = ap.parse_args()

    if not any([args.prev is not None, args.nxt is not None, args.add_prev,
                args.drop_prev, args.add_next, args.drop_next]):
        sys.exit("error: nothing to do; pass at least one of --prev/--next/"
                 "--add-prev/--drop-prev/--add-next/--drop-next")
    if not os.path.isfile(args.path):
        sys.exit("error: %s not found" % args.path)
    with open(args.path) as f:
        dag = json.load(f)

    node, op, np_, on, nn = rewire(
        dag, nid=args.id, name=args.name,
        prev=_ints(args.prev) if args.prev is not None else None,
        add_prev=_ints(args.add_prev), drop_prev=_ints(args.drop_prev),
        nxt=_ints(args.nxt) if args.nxt is not None else None,
        add_next=_ints(args.add_next), drop_next=_ints(args.drop_next))
    validate(dag)

    summary = "'%s' (id %s) prev %s -> %s, next %s -> %s, level %s" % (
        node["name"], _nid(node), op, np_, on, nn, node.get("level"))
    text = json.dumps(dag, indent=2) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        sys.stderr.write("\n[dry-run] would rewire %s\n" % summary)
        return
    with open(args.path, "w") as f:
        f.write(text)
    print("rewired %s -> %s" % (summary, args.path))

    if args.render:
        import render_dag
        print()
        print(render_dag.render(dag))


if __name__ == "__main__":
    main()
