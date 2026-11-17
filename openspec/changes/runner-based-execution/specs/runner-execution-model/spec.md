## Purpose

Define how an Ark agent's execution is selected and dispatched as a `runtime = (tier, framework)`
— where the tier decides *where* it runs (in-process vs sandboxed) and the framework is a
selectable runner adapter — so execution is chosen by configuration rather than by referencing a
per-framework execution engine.

## ADDED Requirements

### Requirement: Select execution via a runtime of tier and framework

An Agent SHALL declare its execution as a runtime comprising a tier and a framework. When the
runtime is unset, the system SHALL default to the in-process tier and the completions framework,
preserving today's default behavior.

#### Scenario: Default runtime when unset
- **WHEN** an agent declares no runtime
- **THEN** it executes on the in-process tier using the completions framework

#### Scenario: Explicit tier and framework honored
- **WHEN** an agent declares a tier and/or framework
- **THEN** it executes on that tier using that framework

### Requirement: Two execution tiers with equivalent agent semantics

The system SHALL provide an in-process (non-sandboxed) tier and a sandboxed tier, and an agent's
observable behavior SHALL be equivalent across tiers apart from the isolation and egress
constraints the sandboxed tier enforces.

#### Scenario: Sandboxed tier isolates the agent
- **WHEN** an agent runs on the sandboxed tier
- **THEN** it executes inside an isolated sandbox with default-deny egress

#### Scenario: In-process tier runs without a sandbox
- **WHEN** an agent runs on the in-process tier
- **THEN** it executes without sandbox or actor-lifecycle overhead

#### Scenario: Equivalent result across tiers
- **WHEN** the same Agent, Model, and Tool specification is run on either tier
- **THEN** the agent produces an equivalent result (model call, tool use, and final output)

### Requirement: Frameworks are selectable adapters, not per-framework deployments

The framework SHALL be selected by configuration and resolved to a runner adapter. Introducing a
new framework SHALL NOT require deploying a new per-framework execution service. A framework not
available on the chosen tier SHALL be reported to the user rather than silently ignored.

#### Scenario: Framework selected by configuration
- **WHEN** an agent selects a framework
- **THEN** the system resolves it to the corresponding runner adapter without a dedicated deployment

#### Scenario: Unsupported framework surfaced
- **WHEN** an agent selects a framework not available on its tier
- **THEN** the system reports the mismatch instead of executing silently with a different framework

### Requirement: Backward compatibility during migration

While the runtime model is being adopted, the system SHALL continue to honor the existing
execution-engine selection so existing agents keep working, with a defined precedence when both
are present.

#### Scenario: Legacy execution-engine selection still works
- **WHEN** an agent uses the legacy execution-engine selection and no runtime
- **THEN** it executes as before

#### Scenario: Runtime takes precedence
- **WHEN** an agent declares both a runtime and a legacy execution-engine selection
- **THEN** the runtime selection governs execution
