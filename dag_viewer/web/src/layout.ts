import type { Edge, Node } from '@xyflow/react'
import type { DagNode } from './types'
import { lvl, nid } from './status'

export const NODE_W = 230
export const NODE_H = 116
const COL_GAP = 64 // horizontal gap between cards in the same level
const ROW_GAP = 72 // vertical gap between levels

const dag = (n: Node): DagNode => (n.data as { node: DagNode }).node

// Level-driven layered layout: every node's DEPTH is its `level` (id ?? stage
// fallback via lvl), so lower levels sit at shallower rows. Within a level, order
// by the mean slot of each node's parents (one downward barycenter pass) to reduce
// edge crossings, breaking ties by id. Rows are then centered horizontally.
export function layout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return nodes

  const nidOf = (n: Node) => nid(dag(n))

  // group nodes by level
  const byLevel = new Map<number, Node[]>()
  for (const n of nodes) {
    const L = lvl(dag(n))
    const bucket = byLevel.get(L)
    if (bucket) bucket.push(n)
    else byLevel.set(L, [n])
  }
  const levels = [...byLevel.keys()].sort((a, b) => a - b)

  // parents (edge source) per node id -- parents always live in a shallower level
  const parents = new Map<string, string[]>()
  for (const e of edges) {
    const p = parents.get(e.target)
    if (p) p.push(e.source)
    else parents.set(e.target, [e.source])
  }

  // order each level; a node's key is the average slot of its already-placed parents
  const slotOf = new Map<string, number>()
  const barycenter = (n: Node): number => {
    const ps = parents.get(n.id) ?? []
    const xs: number[] = []
    for (const p of ps) {
      const s = slotOf.get(p)
      if (s !== undefined) xs.push(s)
    }
    if (xs.length === 0) return nidOf(n) // roots / detached: fall back to id order
    return xs.reduce((a, b) => a + b, 0) / xs.length
  }

  const ordered: Node[][] = []
  levels.forEach((L, rowIdx) => {
    const row = byLevel.get(L)!.slice()
    if (rowIdx === 0) {
      row.sort((a, b) => nidOf(a) - nidOf(b))
    } else {
      row.sort((a, b) => {
        const ka = barycenter(a)
        const kb = barycenter(b)
        return ka === kb ? nidOf(a) - nidOf(b) : ka - kb
      })
    }
    row.forEach((n, i) => slotOf.set(n.id, i))
    ordered.push(row)
  })

  const colStep = NODE_W + COL_GAP
  const rowStep = NODE_H + ROW_GAP
  const maxCols = Math.max(...ordered.map((r) => r.length))
  const fullWidth = maxCols * NODE_W + (maxCols - 1) * COL_GAP

  return ordered.flatMap((row, rowIdx) => {
    const rowWidth = row.length * NODE_W + (row.length - 1) * COL_GAP
    const left = (fullWidth - rowWidth) / 2 // center each row
    return row.map((n, i) => ({
      ...n,
      position: { x: left + i * colStep, y: rowIdx * rowStep },
      width: NODE_W,
      height: NODE_H,
    }))
  })
}
