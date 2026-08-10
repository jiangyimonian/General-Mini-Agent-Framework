# Dynamic Workflow Nodes Design

**Version**: 1.7.0
**Status**: Draft
**Date**: 2026-08-07

## Objective

Permit constrained runtime graph expansion while keeping the workflow graph valid, observable, bounded, and reproducible.

## Expansion Boundary

### Which Node May Request Additions

Only `SequenceNode` and `ParallelNode` may request dynamic additions during execution.

**Rationale**: These container nodes already manage child node lists, making them natural extension points. `ConditionalNode` and `LoopNode` have fixed structure that should not change at runtime.

### Where Additions Are Attached

- For `SequenceNode`: appended to the end of the sequence
- For `ParallelNode`: appended to the parallel children list

Additions are attached **before** the requesting node completes, ensuring the new node executes in the same workflow run.

### When Graph Becomes Immutable

The graph becomes immutable (frozen) when:
1. The workflow completes (success or error)
2. The workflow is cancelled
3. Maximum node count is reached

After freeze, any `add_node` request is rejected with `graph_frozen` error.

## Bounds

### Maximum Dynamic Node Count

**Default**: 100 nodes per workflow run (including static nodes)

**Configurable**: Yes, via `WorkflowConfig(max_nodes=...)`

### Maximum Depth

**Default**: 10 levels

**Configurable**: Yes, via `WorkflowConfig(max_depth=...)`

### Duplicate Node Policy

Each node must have a unique `name` within a workflow. Duplicate name requests are rejected with `duplicate_node` error.

## Failure and Cancellation Behavior

### Node Failure

If a node fails after requesting additions:
- Additions already made are preserved in the graph
- Workflow stops with `node_error`
- Previously emitted `NodeResult` values remain immutable

### Workflow Cancellation

If workflow is cancelled:
- Graph is frozen immediately
- No further additions are accepted
- In-flight operations receive `CancelledError`

## Event Types

### `node_addition_requested`

Emitted when a node requests to add a child.

```python
{
    "type": "node_addition_requested",
    "requesting_node": str,  # Node name
    "node_to_add": str,      # New node name
    "node_type": str,        # Node class name
    "current_count": int,    # Current node count
}
```

### `node_addition_accepted`

Emitted when addition is successful.

```python
{
    "type": "node_addition_accepted",
    "requesting_node": str,
    "node_added": str,
    "new_count": int,
}
```

### `node_addition_rejected`

Emitted when addition is rejected.

```python
{
    "type": "node_addition_rejected",
    "requesting_node": str,
    "node_to_add": str,
    "reason": str,  # "max_nodes", "max_depth", "duplicate_node", "graph_frozen"
}
```

### `graph_frozen`

Emitted when workflow completes or is cancelled.

```python
{
    "type": "graph_frozen",
    "final_count": int,
    "stop_reason": str,  # "completed", "node_error", "cancelled"
}
```

## Public API

### WorkflowConfig

```python
@dataclass(frozen=True)
class WorkflowConfig:
    max_nodes: int = 100
    max_depth: int = 10
```

### Node.add_node()

```python
class DynamicNodeMixin:
    def add_node(
        self,
        node: WorkflowNode,
        *,
        name: str | None = None,
    ) -> bool:
        """Request to add a node dynamically.
        
        Returns:
            True if accepted, False if rejected.
        
        Raises:
            GraphFrozenError: If graph is already frozen.
        """
```

### GraphFrozenError

```python
class GraphFrozenError(Exception):
    """Raised when attempting to modify a frozen graph."""
    def __init__(self, reason: str):
        self.reason = reason
```

## State Isolation

Two executions of the same `Workflow` instance must not share dynamic additions:
- Each `run()` call starts with the original static graph
- Dynamic additions are tracked per-run in a `RunContext` attribute
- Additions from a prior run do not affect subsequent runs

## Implementation Approach

1. Add `WorkflowConfig` to `Workflow.__init__`
2. Add `DynamicNodeMixin` class with `add_node()` method
3. Modify `SequenceNode` and `ParallelNode` to inherit from `DynamicNodeMixin`
4. Add `_DynamicGraphState` to track additions per-run
5. Emit events for all addition requests, acceptances, and rejections
6. Add validation for bounds, duplicates, and frozen state

## Test Requirements

1. Valid runtime addition succeeds
2. Duplicate name rejected
3. Max nodes rejection
4. Max depth rejection  
5. Failure propagation preserves additions
6. Cancellation freezes graph
7. Event parent/child IDs stable
8. Two runs do not share additions