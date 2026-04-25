# AgentRedTeam — Future Work

---

## Multi-Agent Attacks (D-category)

Deferred from initial implementation. See DD-12 in design-decisions-log.md.

### Attacks to implement
- **D-01 Orchestrator Hijacking** — compromise the orchestrator's instructions to redirect sub-agents toward an unintended goal
- **D-02 Sub-Agent Impersonation** — stand up a `MockSubAgent` stub that returns adversarial responses in place of a real sub-agent
- **D-03 Trust Escalation** — exploit implicit elevated trust between agents to issue instructions beyond a sub-agent's privilege level
- **D-04 Circular Delegation** — inject self-referential task IDs to create infinite delegation loops between agents

### Implementation notes
- Requires a "shadow topology" pattern: AgentRedTeam spins up a controlled `MockSubAgent` stub that sits in place of a real sub-agent in the orchestrator's call path
- Requires grey-box or SDK adapter access — pure black-box REST mode cannot reach inter-agent communication
- User must provide the target's multi-agent topology in the campaign YAML (agent names, endpoints, message formats)
- `MockSubAgent` wraps `AgentInterface` and intercepts/mutates messages before returning them to the orchestrator
- D-04 requires injecting self-referential task IDs into the delegation chain

### Prerequisites before implementing
- SDK adapter is stable and in use by real teams
- There is a user base with multi-agent deployments who are requesting this
- Campaign YAML schema extended to describe multi-agent topologies
