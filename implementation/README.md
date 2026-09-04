Prepared run directories — **one directory per DAG node**, flat siblings:
`implementation/<exploration>/<level>_<id>_<node>/`.

Written by the `prepare-node` skill. Never nest one node directory inside
another: the DAG has fan-in, so it cannot be a filesystem tree. Relations live
in `project_workflow/<exploration>/workflow_dag.json`.
