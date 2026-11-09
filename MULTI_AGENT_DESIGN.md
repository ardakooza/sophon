# Sophon Multi-Agent Architecture — Design Draft

Status: proposal for review. This document does not claim that `multi-agent`
syntax or its XAF policies are implemented. The existing single-agent API stays
unchanged until this design is agreed.

## 1. Goals

- A named orchestration group contains multiple specialized agents.
- Each agent has an identity and a role.
- Agents can receive private inputs and shared group inputs.
- Multiple messages/tasks are distinct work items with deterministic ordering.
- Results remain attributable to the agent and the exact input item.
- XAF remains the authority for capabilities, limits, and external access.

## 2. Proposed SPH structure

```sph
use { agent }
connect to sophon.xaf

multi-agent {
    id = "research-team"

    agent {
        id = "researcher"
        role = "Research"
        message {
            "Bu mesaj yalnız researcher ajanına gider."
        }
    }

    agent {
        id = "analyst"
        role = "Analysis"
    }

    message = "Ortak bağlam: araştırma konusunu incele."
    task = "Kaynakları değerlendir ve bulguları çıkar."
}
```

The above is illustrative, not executable syntax yet. A group-level message/task
is broadcast to every member. Agent-level content is private to that member.

## 3. Single and multiple payloads

Proposed short form:

```sph
message = "Tek mesaj"
task = "Tek görev"
```

Proposed ordered form:

```sph
message {
    "Mesaj 1"
    "Mesaj 2"
}

task {
    "Görev 1"
    "Görev 2"
}
```

Decision required: are message and task independent queues, or are all entries
executed in one source-ordered queue? Recommended default: preserve source order
across all work items, while each item retains its kind (`message` or `task`).
For each agent, private items and broadcast items should be merged by declaration
order, with the broadcast item expanded to each member.

## 4. Work-item identity and output model

Do not overwrite one output state for every response. That would lose earlier
responses. Recommended runtime result shape:

```text
MultiAgentResult {
  group_id
  status
  agents: [
    {
      agent_id
      role
      status
      outputs: [
        { item_id, kind, input_index, status, response, error }
      ]
    }
  ]
}
```

Candidate SPH output declarations to decide between:

1. `output = results` — one list/object state containing every result (recommended).
2. `output { researcher = research_results analyst = analysis_results }` —
   one output state per agent.
3. Per-item output mapping — most expressive, but more verbose and harder to validate.

Recommended: support group-level `output = results` first, and store a structured
list preserving agent ID, role, item ID, kind, status, and response. A later
`output { ... }` mapping can be added without changing the result model.

## 5. Scheduling and execution semantics

Decisions to finalize:

- Sequential or parallel execution. Recommended initial implementation:
  sequential and deterministic; add `strategy = parallel` later.
- Per-agent ordering: preserve declaration order.
- Group ordering: process agents in declaration order unless a strategy says otherwise.
- Failure policy: choose `continue`, `stop-group`, or `fail-fast`; recommended
  default is `continue`, recording each failure, with optional fail-fast.
- Retry policy: XAF-configured bounded retries, not unbounded loops.
- Cancellation: group cancellation should stop scheduling new work and request
  cancellation of active provider calls where supported.

## 6. Context and communication

Separate three channels:

- Private input: visible only to the addressed agent.
- Broadcast input: delivered independently to every agent.
- Inter-agent message: a later explicit capability; never implicitly expose one
  agent's private prompt or response to another.

Potential future syntax (not approved):

```sph
agent-message {
    from = "researcher"
    to = "analyst"
    content = "Kaynak listesi hazır."
}
```

The runtime must define whether agents can read previous agents' outputs. The
recommended default is no; XAF must explicitly grant shared-result access.

## 7. Proposed XAF policy surface

Illustrative policy shape only:

```xaf
policy research-team-policy {
    access {
        agent
        multi-agent {
            execute = true
            broadcast = true
            private-input = true
            read-results = true
            inter-agent-message = false
            delegate = false
        }
    }

    limits {
        max-agents = 5
        max-work-items-per-agent = 10
        max-total-work-items = 30
        max-parallel = 1
        timeout = 120
        retries = 1
        max-total-tokens = 20000
    }

    action {
        read = true
    }
}
```

Policy decisions to settle:

- Whether `multi-agent` is a distinct capability or an extension of `agent`.
  Recommended: distinct capability, requiring both `agent` and `multi-agent`.
- Whether each agent inherits its own policy or the group policy. Recommended:
  each agent retains its own agent policy; the group policy is an additional
  ceiling. Effective permission is the intersection, never the union.
- Whether broadcast, result sharing, delegation, and inter-agent messaging are
  separate permissions. Recommended: yes, each independently controlled.
- Whether provider/model selection belongs to the agent block or XAF. Recommended:
  provider/model and secrets remain XAF-only; SPH selects only declared agent IDs.

## 8. XAF resource and safety limits

Proposed controls:

- `max-agents`, `max-work-items-per-agent`, `max-total-work-items`.
- `max-parallel` and per-agent `delay`/timeout.
- `retries`, `max-total-tokens`, and optionally a monetary budget.
- Allowed tools/connectors per agent; deny-by-default tool access.
- Data classification and redaction rules for shared context/results.
- Explicit permission for reading another agent's output.
- Audit logging for group start/end, work-item start/end, provider, model,
  token usage, policy decision, and failure reason.

## 9. Lifecycle and state model

Suggested lifecycle: `pending -> running -> completed | failed | cancelled`.
A group is `completed` only when all scheduled work items are terminal. Partial
success is represented explicitly; it must not be collapsed into a single string.
Persisting results to `.svt` should be a later opt-in feature governed by database
and file-system policies, not an implicit side effect.

## 10. Error handling and observability

Every work item should have a stable ID, agent ID, kind, sequence index, start/end
time, status, and structured error. One provider failure should not erase prior
successful outputs. Logs must avoid secrets and private prompts unless XAF
explicitly enables protected prompt logging.

## 11. Proposed implementation phases

1. Finalize syntax, work-item ordering, and output structure.
2. Implement parser + static validation; no parallelism yet.
3. Implement sequential execution and structured result state.
4. Add XAF policy intersection, quotas, timeout, retry, and audit records.
5. Add parallel scheduling, cancellation, and inter-agent communication only
   after their security semantics are agreed.

## 12. Open decisions for review

1. Should each agent accept both private `message` and private `task`, or exactly one?
2. Should group-level `message` and `task` both be allowed in the same group?
3. Should message/task items interleave in source order, or run as separate queues?
4. Should every agent receive all group-level items, even if it has private items?
5. Which output model: one structured list, per-agent states, or both?
6. Sequential default accepted, with explicit parallel strategy later?
7. Should a failed agent stop the group, or should other agents continue?
8. Should inter-agent messaging be part of the first release or a later capability?
