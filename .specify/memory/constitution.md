<!--
SYNC IMPACT REPORT
==================
Version change: [template] → 1.0.0
Modified principles: (none — initial authoring from blank template)
Added sections:
  - Core Principles (5 principles)
  - Windows Deployment Standards
  - Development Workflow & Quality Gates
  - Governance
Templates requiring updates:
  - .specify/templates/plan-template.md  ✅ aligned — Constitution Check section maps to 5 principles
  - .specify/templates/spec-template.md  ✅ no structural changes needed
  - .specify/templates/tasks-template.md ✅ no structural changes needed — TDD task ordering already present
Follow-up TODOs:
  - None — all placeholders resolved
-->

# pms-scanner Constitution

## Core Principles

### I. Windows-First, Unattended Operation

This service MUST run reliably as a background process on Windows machines without any
human interaction. Specific requirements:

- The service MUST handle restarts gracefully via a process supervisor (Docker Desktop
  `restart: unless-stopped`, NSSM, or `win32serviceutil`).
- The service MUST NOT require an interactive session or GUI at any point.
- All file-system paths MUST be configurable via environment variables — no hard-coded
  Windows paths (e.g., `C:\...`) in source code.
- The watcher MUST recover from transient I/O errors (locked files, network share
  interruptions) without crashing; retry logic with exponential back-off is REQUIRED.
- Startup and shutdown lifecycle MUST be explicitly managed: log startup success,
  trap SIGTERM/SIGINT, and flush in-flight uploads before exit.

**Rationale**: An unattended service that crashes silently causes data loss. Reliability
and self-recovery are non-negotiable for a production background process.

### II. Test-Driven Development (NON-NEGOTIABLE)

TDD MUST be followed without exception on every change:

1. Write the failing test first — it MUST fail before any implementation is written.
2. Implement only the minimum code required to make the test pass (Red → Green).
3. Refactor under green (Red → Green → Refactor cycle strictly enforced).
4. No production code may be merged to `main` without a corresponding test that
   was committed before the implementation.

Test pyramid for this project:

- **Unit tests**: Pure logic — config parsing, retry calculation, file-settle logic.
- **Integration tests**: Watcher lifecycle, HTTP upload against a local mock server.
- **Contract tests**: API contract against the backend upload endpoint schema.

**Rationale**: TDD prevents regressions, forces clear interface design before
implementation, and is the primary quality gate for an unattended service where
runtime failures are not immediately visible.

### III. Quality First

Code quality is a first-class constraint, not an afterthought:

- All code MUST pass `ruff` (linting + formatting) with zero violations.
- All code MUST pass `mypy --strict` type checking with zero errors.
- Test coverage MUST remain ≥ 90% on all non-trivial modules.
- No `TODO` or `FIXME` comments may be merged to `main` without a linked issue.
- Functions with cyclomatic complexity > 10 MUST be refactored or explicitly justified
  before merge.

**Rationale**: This service runs unattended; defects discovered at 3 AM are expensive
to diagnose and fix. Automated quality gates catch issues before they reach production.

### IV. Observability & Structured Logging

Every meaningful runtime event MUST be logged at the appropriate level:

- Use Python's `logging` module with the standard structured format:
  `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Log startup configuration (secrets such as `api_token` MUST be redacted — never
  logged in plain text).
- Log every file detected, upload attempt, upload outcome (success/failure), and retry.
- Errors MUST include context: file path, HTTP status code, and exception message.
- Log level MUST be configurable via `LOG_LEVEL` environment variable (default: `INFO`).

**Rationale**: When a service runs unattended, logs are the only window into its
behaviour. Insufficient logging means silent data loss with no path to diagnosis.

### V. Documentation Before PR

Documentation MUST be current and accurate before any pull request is submitted for
review:

- `README.md` MUST reflect any new or changed environment variables, configuration
  options, or operational procedures introduced by the PR.
- Any API contract changes or deployment procedure changes MUST be documented in
  the relevant `docs/` file before the PR is opened.
- The PR description MUST include a confirmed "Docs updated" checklist item.
- Reviewers MUST reject PRs where documentation is demonstrably out of date or
  missing for user-visible changes.

**Rationale**: Unattended services are operated by people who were not present at
implementation time. Accurate, current documentation is the only operational guide
available without interrupting the original author.

## Windows Deployment Standards

- **Supported hosts**: Windows 10/11 (x64), Windows Server 2019/2022.
- **Recommended supervisor**: Docker Desktop with `restart: unless-stopped` is the
  preferred deployment method. NSSM (Non-Sucking Service Manager) is the recommended
  alternative for native Windows service registration.
- **Environment config**: All configuration via `.env` file or system environment
  variables — never baked into the Docker image or committed to source control.
- **Volume mapping**: The `incoming` watch directory MUST be a host-mounted volume;
  all container-to-host path mappings MUST be documented in `README.md`.
- **Security**: `api_token` MUST be supplied via environment variable only — never
  stored in source control, Docker image layers, or log output.
- **Health monitoring**: A health-check mechanism (Docker `HEALTHCHECK` directive or
  a lightweight `/healthz` HTTP endpoint) SHOULD be provided.

## Development Workflow & Quality Gates

### Pre-Merge Checklist (every PR)

1. All tests pass: `pytest` — unit, integration, and contract where applicable.
2. TDD cycle verified: the failing test commit predates the implementation commit
   in the PR's commit history.
3. `ruff check .` returns zero violations.
4. `mypy --strict scanner/` returns zero errors.
5. Coverage report shows ≥ 90% on changed/new modules.
6. Documentation updated: README, environment variable table, changelog if needed.
7. PR description includes: motivation, testing notes, and confirmed docs update.

### Branch Strategy

- `main`: always deployable; protected; requires PR + at least one reviewer approval.
- Feature branches: `###-short-description` (e.g., `001-retry-logic`).
- Hotfix branches: `hotfix/short-description`.

### Review Standards

- At least one reviewer approval is required before merge to `main`.
- Reviewer MUST verify documentation is current (Principle V).
- Reviewer MUST verify TDD cycle evidence in the commit history (Principle II).
- Reviewer MUST confirm quality gates passed (Principle III).

## Governance

This constitution supersedes all informal conventions and verbal agreements for
the pms-scanner project.

- Amendments require a dedicated PR to `.specify/memory/constitution.md` with an
  incremented version number, a rationale comment in the PR description, and at
  least one reviewer approval.
- Version policy: MAJOR for principle removals or redefinitions; MINOR for new
  principles or sections; PATCH for clarifications and wording fixes.
- Compliance is reviewed at feature-start (Constitution Check in `plan.md`) and
  again at PR review time.
- All contributors and AI agents MUST read this constitution before beginning any
  work on the project.

**Version**: 1.0.0 | **Ratified**: 2026-04-08 | **Last Amended**: 2026-04-08
