## Purpose

Define how sandboxed agents participate in multi-agent work without direct actor-to-actor
networking: teams are run by a mediating coordinator, and an agent delegating to another
agent or team from inside its sandbox is mediated by a delegation gateway, with shared state in
Ark Memory. Direct actor-to-actor communication is explicitly a non-goal here (a separate
Substrate capability).

## ADDED Requirements

### Requirement: Teams of sandboxed agents execute via a mediating coordinator

A Team whose members run on the sandboxed tier SHALL be executed by a coordinator that applies
the team strategy and invokes each member; members SHALL NOT be required to communicate directly
with one another.

#### Scenario: Sandboxed team runs per strategy
- **WHEN** a Team of sandboxed members is queried
- **THEN** the coordinator invokes members according to the team strategy and aggregates their outputs

#### Scenario: Members do not call each other directly
- **WHEN** one member's output is needed by another
- **THEN** it is relayed by the coordinator and shared state, not by a direct member-to-member call

### Requirement: An agent may delegate to another agent or team from within a sandbox

An agent running on the sandboxed tier SHALL be able to invoke another agent or team declared as
one of its tools, with the call mediated by a delegation gateway rather than a direct connection
to the target.

#### Scenario: Agent-as-tool delegation
- **WHEN** a sandboxed agent invokes an agent-typed tool
- **THEN** the request is mediated by the delegation gateway and the target's result is returned to the caller

#### Scenario: Team-as-tool delegation
- **WHEN** a sandboxed agent invokes a team-typed tool
- **THEN** the team is executed via the coordinator and its result is returned to the caller

### Requirement: Delegation is authorized against the declared graph

Delegation SHALL be default-deny: a caller SHALL only reach targets it declares as tools (or team
membership), the caller SHALL be authenticated by its actor identity, and the gateway SHALL
enforce the permitted caller-to-target graph.

#### Scenario: Undeclared target refused
- **WHEN** a sandboxed agent attempts to delegate to a target it has not declared
- **THEN** the delegation is refused

#### Scenario: Authenticated and authorized delegation
- **WHEN** a sandboxed agent delegates to a declared target
- **THEN** the gateway verifies the caller's identity and authorizes the call before dispatching it

### Requirement: Shared conversation state flows through Ark Memory

Delegated participants SHALL exchange context through Ark Memory (the broker) keyed by
conversation, not through sandbox-local state, so a sandboxed participant sees the relevant shared
history and its contribution is persisted.

#### Scenario: Delegated participant sees shared context
- **WHEN** a sub-agent is invoked within an ongoing conversation
- **THEN** it can load the relevant conversation history and its result is persisted to Ark Memory

### Requirement: Delegation cycles are bounded

The system SHALL detect and halt delegation cycles so a chain of agent-to-agent delegations
cannot recurse without bound.

#### Scenario: Cycle halted
- **WHEN** a delegation chain would revisit an agent already active in the same chain
- **THEN** the system halts the cycle and surfaces an error rather than recursing indefinitely
