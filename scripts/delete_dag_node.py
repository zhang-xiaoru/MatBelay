#!/usr/bin/env python3
"""Delete a node from a workflow DAG JSON (see templates/dag_template.json).

Removes a node identified by --id or --name, strips every reference to it
from the other nodes' prev/next, and optionally bridges its parents straight
to its children so the chain is not broken. Validates acyclicity before
writing.

Examples
--------
Delete node 3, reconnecting its parents to its children (parents -> children):
    python delete_dag_node.py DAG.json --id 3 --bridge

Delete by name and then compact node ids to 0..N-1:
    python delete_dag_node.py DAG.json --name aux --bridge --renumber

Add `--dry-run` to preview (prints JSON, writes nothing) or `--render` to
show the ASCII diagram afterwards.
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from insert_dag_node import validate, _ordered, _nid, relevel   # noqa: E402


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


def delete(dag, nid=None, name=None, bridge=False, renumber=False):
    nodes = dag["nodes"]
    target = _find(nodes, nid, name)
    s = _nid(target)
    parents = list(target.get("prev", []))
    children = list(target.get("next", []))

    nodes.remove(target)
    by_id = {_nid(n): n for n in nodes}

    # strip references to the deleted node id
    for n in nodes:
        n["prev"] = [p for p in n.get("prev", []) if p != s]
        n["next"] = [q for q in n.get("next", []) if q != s]

    if bridge:
        for p in parents:
            for c in children:
                if p == c or p not in by_id or c not in by_id:
                    continue
                if c not in by_id[p]["next"]:
                    by_id[p]["next"] = sorted(by_id[p]["next"] + [c])
                if p not in by_id[c]["prev"]:
                    by_id[c]["prev"] = sorted(by_id[c]["prev"] + [p])
    else:
        orphaned = [by_id[c]["name"] for c in children
                    if c in by_id and not by_id[c]["prev"]]
        if orphaned:
            sys.stderr.write("warning: downstream node(s) left with no parent: "
                             + ", ".join(orphaned) + "  (use --bridge to reconnect)\n")

    if renumber:
        order = sorted(nodes, key=lambda n: _nid(n))
        remap = {_nid(n): i for i, n in enumerate(order)}
        for n in nodes:
            n["id"] = remap[_nid(n)]
            n.pop("stage", None)
            n["prev"] = sorted(remap[p] for p in n["prev"])
            n["next"] = sorted(remap[q] for q in n["next"])

    relevel(dag)          # bridging/removal can shorten descendants' depth
    nodes.sort(key=lambda n: (n.get("level", 0), _nid(n)))
    dag["nodes"] = [_ordered(n) for n in nodes]
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="path to workflow_dag.json")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int, help="id of the node to delete")
    g.add_argument("--name", help="name of the node to delete")
    ap.add_argument("--bridge", action="store_true",
                    help="reconnect the deleted node's parents to its children")
    ap.add_argument("--renumber", action="store_true",
                    help="compact node ids to 0..N-1 after deletion")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write")
    ap.add_argument("--render", action="store_true",
                    help="render the ASCII diagram after deleting")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit(f"error: {args.path} not found")
    with open(args.path) as f:
        dag = json.load(f)

    removed = delete(dag, nid=args.id, name=args.name,
                     bridge=args.bridge, renumber=args.renumber)
    validate(dag)

    text = json.dumps(dag, indent=2) + "\n"
    rid = removed.get("id", removed.get("stage"))
    if args.dry_run:
        sys.stdout.write(text)
        sys.stderr.write(f"\n[dry-run] would delete '{removed['name']}' "
                         f"(id {rid})\n")
        return
    with open(args.path, "w") as f:
        f.write(text)
    print(f"deleted '{removed['name']}' (id {rid}) -> {args.path}")

    if args.render:
        import render_dag
        print()
        print(render_dag.render(dag))


if __name__ == "__main__":
    main()
