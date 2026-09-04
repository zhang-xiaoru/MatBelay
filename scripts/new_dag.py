#!/usr/bin/env python3
"""Create a new, empty workflow DAG JSON from templates/dag_template.json.

The template carries documentation keys (`_comment`, `_node_format`) and a
placeholder node that must NOT end up in a real workflow_dag.json. Stamping the
file by hand is where stray fields and typo'd legends creep in, so this does it
deterministically: copy the template, drop every `_`-prefixed key, drop the
placeholder node, fill in exploration/description. Nodes are then added with
insert_dag_node.py, which owns id/level derivation and edge wiring.

Examples
--------
    python new_dag.py --exploration defect_kappa \\
        --description "T-matrix phonon-defect scattering in r-TiO2"

    python new_dag.py --exploration foo --description "bar" \\
        --out /tmp/scratch_dag.json --render
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
TEMPLATE = os.path.join(_ROOT, "templates", "dag_template.json")


def load_template(path=TEMPLATE):
    if not os.path.isfile(path):
        sys.exit("error: template not found at %s" % path)
    with open(path) as f:
        return json.load(f)


def blank_dag(exploration, description, template=None):
    """The exact top-level shape the template presets, with no nodes yet."""
    t = template if template is not None else load_template()
    dag = {}
    for k, v in t.items():
        if k.startswith("_"):
            continue                      # documentation-only keys
        dag[k] = v
    dag["exploration"] = exploration
    dag["description"] = description
    dag["nodes"] = []                     # placeholder node is not real data
    return dag


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exploration", required=True,
                    help="exploration tag; also the default output directory name")
    ap.add_argument("--description", default="",
                    help="one-line exploration summary")
    ap.add_argument("--out",
                    help="output path (default: "
                         "<repo>/project_workflow/<exploration>/workflow_dag.json)")
    ap.add_argument("--template", default=TEMPLATE, help="template to stamp from")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing file (refuses by default)")
    ap.add_argument("--dry-run", action="store_true", help="print result, do not write")
    ap.add_argument("--render", action="store_true", help="render the diagram afterwards")
    args = ap.parse_args()

    out = args.out or os.path.join(_ROOT, "project_workflow", args.exploration,
                                   "workflow_dag.json")
    dag = blank_dag(args.exploration, args.description, load_template(args.template))

    from insert_dag_node import validate
    validate(dag)

    text = json.dumps(dag, indent=2) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
        sys.stderr.write("\n[dry-run] would write %s\n" % out)
        return
    if os.path.exists(out) and not args.force:
        sys.exit("error: %s already exists; pass --force to overwrite (this "
                 "DISCARDS every node in it)" % out)
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(out, "w") as f:
        f.write(text)
    print("created empty DAG '%s' -> %s" % (args.exploration, out))
    print("next: add nodes with insert_dag_node.py (it derives id/level and "
          "wires prev/next)")

    if args.render:
        import render_dag
        print()
        print(render_dag.render(dag))


if __name__ == "__main__":
    sys.path.insert(0, _HERE)
    main()
