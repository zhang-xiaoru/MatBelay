#!/usr/bin/env python3
"""Render a workflow DAG JSON as an ASCII view for quick terminal inspection.

Usage:
    python render_dag.py [path/to/workflow_dag.json]

Default path is ./workflow_dag.json. Reads the schema written by
templates/dag_template.json (exploration/description + nodes with
name/description/status/stage/cluster/allocation/job fields and prev/next,
where prev/next are lists of upstream/downstream integer stage numbers).
"""
import json
import sys
import os

# short ASCII status tags (padded to equal width for alignment)
TAG = {
    "completed": "[done]",
    "ready":     "[redy]",
    "queued":    "[que.]",
    "running":   "[run.]",
    "pending":   "[pend]",
    "failed":    "[FAIL]",
    "blocked":   "[blkd]",
    "terminated": "[TERM]",
}


def load(path):
    with open(path) as f:
        return json.load(f)


def _nid(n):
    """Node identity key (edges reference this). Falls back to legacy `stage`."""
    return n.get("id", n.get("stage", 0))


def _lvl(n):
    """Tree level (depth). Falls back to the identity if `level` is absent."""
    return n.get("level", _nid(n))


INDENT = 8          # left margin for the whole diagram
INNER = 46          # inner width of each box


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _meta_lines(node):
    """Optional per-node meta lines (cluster/allocation, job, timing).

    Only emitted when the underlying fields are populated, so an unsubmitted
    node stays compact."""
    lines = []
    cl, al = node.get("cluster", ""), node.get("allocation", "")
    part, nn = node.get("partition", ""), node.get("num_nodes", "")
    tool = node.get("tool", "")
    loc = "  ".join(x for x in (f"@{cl}" if cl else "", part,
                                f"x{nn}" if nn else "", tool,
                                al if al and al != "-" else "") if x)
    if loc:
        lines.append(loc)
    jn, jid = node.get("job_name", ""), node.get("job_id", "")
    if jn or jid:
        lines.append("job " + "  ".join(x for x in (jn, f"#{jid}" if jid else "") if x))
    timing = []
    if node.get("request_time"):
        timing.append("req " + node["request_time"])
    if node.get("elapsed_time"):
        timing.append("elapsed " + node["elapsed_time"])
    if node.get("running_time"):
        timing.append("run " + node["running_time"])
    if timing:
        lines.append("  ".join(timing))
    if node.get("expected_start"):
        lines.append("eta " + node["expected_start"])
    out = []
    for l in lines:
        out += _wrap(l, INNER)
    return out


def _box(node):
    """Return the list of text lines forming one node box.

    The workflow is an acyclic DAG (stage/prev/next), so boxes are drawn
    plainly with no self-return arc."""
    tag = TAG.get(node.get("status", ""), "[????]")
    marker = f"L{_lvl(node)} #{_nid(node)}"                    # level + identity
    head = f"{tag} {node['name']}"
    head = f"{head}{marker.rjust(INNER - len(head))}"          # right-aligned
    body = [head[:INNER]]
    for line in _wrap(node.get("description", ""), INNER):
        body.append(line)
    body += _meta_lines(node)
    if node.get("blocked_on"):
        for line in _wrap("! blocked: " + node["blocked_on"], INNER):
            body.append(line)
    if node.get("terminated_reason"):
        for line in _wrap("x terminated: " + node["terminated_reason"], INNER):
            body.append(line)
    pad = " " * INDENT
    top = pad + "+" + "-" * (INNER + 2) + "+"
    return [top] + [pad + "| " + l.ljust(INNER) + " |" for l in body] + [top]


def _connector(label=""):
    pad = " " * (INDENT + (INNER + 4) // 2)
    lines = [pad + "|"]
    if label:
        lines.append(pad[:-len(label) - 1] + label + " |")
    lines.append(pad + "v")
    return lines


def render(dag):
    out = []
    out.append("#" * (INNER + INDENT + 4))
    out.append(f"# WORKFLOW DAG: {dag.get('exploration', dag.get('project', '<unnamed>'))}")
    if dag.get("description"):
        for line in _wrap(dag["description"], INNER + INDENT):
            out.append(f"#   {line}")

    nodes = dag.get("nodes", [])
    # summarize clusters/allocations across nodes (cluster/allocation are per-node now)
    clusters = sorted({n["cluster"] for n in nodes if n.get("cluster")})
    allocs = sorted({n["allocation"] for n in nodes
                     if n.get("allocation") and n["allocation"] != "-"})
    if clusters:
        out.append(f"#   clusters={', '.join(clusters)}")
    if allocs:
        out.append(f"#   allocations={', '.join(allocs)}")
    out.append("#" * (INNER + INDENT + 4))
    out.append("")

    order = sorted(nodes, key=lambda n: (_lvl(n), _nid(n)))
    ids = {_nid(n) for n in nodes}
    name_of = {_nid(n): n["name"] for n in nodes}
    chain = [_nid(n) for n in order]

    for i, n in enumerate(order):
        nxt = n.get("next", [])
        sid = _nid(n)
        out += _box(n)
        # forward edges to nodes that are NOT the immediate next in the chain
        following = chain[i + 1] if i + 1 < len(chain) else None
        skips = [x for x in nxt if x != sid and x != following and x in ids]
        for s in skips:
            tgt = name_of.get(s, f"#{s}")
            out.append(" " * (INDENT + 2)
                       + f"`--------(edge)--------> {tgt} (#{s})")
        # main downward arrow to the next box in the chain
        if following is not None:
            out += _connector()

    out.append("")
    out.append("legend: " + "  ".join(f"{v}={k}" for k, v in TAG.items()))
    return "\n".join(out)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "workflow_dag.json"
    if not os.path.isfile(path):
        sys.exit(f"error: {path} not found")
    print(render(load(path)))


if __name__ == "__main__":
    main()
