---
paths: implementation/**
---
# Implementation Directory Protocol
`implementation` contains multiple `[exploration]`, where each `[exploration]` contains the implementation of a specific computation workflow, corresponding to that exploration's DAG file at `project_workflow/[exploration]/workflow_dag.json`. Any computation node should lie in one `[exploration]`. 

Different `[exploration]` usually represent different computation task with their own goal, and share different workflow. They are mostly parallal but could be dependent in some cases

## Implementation folder structure
```
implementation/
├── [exploration1]/                 
│    └─[node1]                   # one node in a computation DAG
│    └─[node2]
│── [exploration2]/
│    └─[node1]
│    └─[node1]
....
```
Each `[exploration]` folder own seperate DAG and node structure

## Implementation layout convention

- **One directory per DAG node**, a **flat sibling** under `implementation/<exploration>/`,
  named `<level>_<id>_<name>` (e.g. `4_9_tmatrix_rcut_conv`) so the name encodes the
  node's DAG position.
- **Never nest node dirs inside each other.** The DAG has **fan-in** (a node can have
  several parents) so it cannot be a filesystem tree; relations stay in `workflow_dag.json`.
- Shared templates (`INCAR.*`, `KPOINTS`, `*.batch`, notes) and utility dirs like
  `helper/` stay as **loose non-node items** at the `[exploration]` root.