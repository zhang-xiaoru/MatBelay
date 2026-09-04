**The DAGs — the single source of truth for computation status.**

One file per exploration: `project_workflow/<exploration>/workflow_dag.json`.

Never hand-edit these. Use `scripts/` (or the `workflow-dag` skill), which
maintain the id/level/edge invariants that hand-editing silently breaks.
Verify with `python3 scripts/check_dag.py project_workflow/*/workflow_dag.json`.
