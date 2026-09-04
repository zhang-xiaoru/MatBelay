import { useEffect, useMemo } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from '@xyflow/react'
import type { Dag, DagNode } from '../types'
import { isActionable, nid, statusColor } from '../status'
import { layout } from '../layout'
import NodeCard, { type CardData } from './NodeCard'

const nodeTypes = { card: NodeCard }

function build(dag: Dag): { nodes: Node[]; edges: Edge[] } {
  const statusById = new Map<number, string>()
  dag.nodes.forEach((n) => statusById.set(nid(n), n.status))

  const nodes: Node[] = dag.nodes.map((n: DagNode) => ({
    id: String(nid(n)),
    type: 'card',
    position: { x: 0, y: 0 },
    data: { node: n, actionable: isActionable(n, statusById) } satisfies CardData,
  }))

  const edges: Edge[] = dag.nodes.flatMap((n) =>
    (n.next ?? [])
      .filter((q) => statusById.has(q))
      .map((q) => ({
        id: `${nid(n)}->${q}`,
        source: String(nid(n)),
        target: String(q),
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: { strokeWidth: 1.5 },
      })),
  )

  return { nodes: layout(nodes, edges), edges }
}

export default function Graph({
  dag,
  selectedId,
  onSelect,
}: {
  dag: Dag
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const built = useMemo(() => build(dag), [dag])
  const [nodes, setNodes, onNodesChange] = useNodesState(built.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(built.edges)

  useEffect(() => {
    setNodes(built.nodes)
    setEdges(built.edges)
  }, [built, setNodes, setEdges])

  const styled = useMemo(
    () => nodes.map((n) => ({ ...n, selected: Number(n.id) === selectedId })),
    [nodes, selectedId],
  )

  return (
    <div className="graph">
      <ReactFlow
        nodes={styled}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onSelect(Number(node.id))}
        fitView
        minZoom={0.15}
        maxZoom={2}
        nodesDraggable
      >
        <Background gap={18} />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) =>
            statusColor((n.data as CardData | undefined)?.node?.status ?? 'pending')
          }
        />
      </ReactFlow>
    </div>
  )
}
