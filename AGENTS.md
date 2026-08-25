# Repository Guidelines

## Project Overview

DocGrading supports rubric-based evaluation of academic PDF reports. Automated rules, NLP, and LLM evaluators produce suggestions and evidence; a Teacher remains responsible for review, approval, and publication. The one-month MVP is scoped to Vietnamese SRS reports and text-native PDFs.

The repository currently contains two different maturity levels:

- `frontend/` is a runnable React/Vite prototype backed only by mock data.
- `docs/` defines the intended modular-monolith product, backend, worker, persistence, security, and QA contracts. Most of that target system is not implemented yet.

Treat `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md` as the current product/architecture baseline, then verify the implementation before changing code. When documentation and code disagree, identify whether code is incomplete or documentation is stale; do not silently invent a third contract.

## Architecture & Data Flow

### Current prototype

`frontend/src/main.tsx` mounts `App`. `frontend/src/app/App.tsx` currently contains the application shell, mock entities, and all Admin, Teacher, and Student views in one file.

- `App` owns cross-view state: `role`, `view`, courses, assignments, active identifiers, and selected submissions.
- Child views receive data and mutation/navigation callbacks through props. View-local forms, tabs, upload stages, and autosave indicators use `useState`.
- Navigation is a `View` string union plus `NAV` and `BREADCRUMBS` maps; there is no router.
- `STATUS` is the shared mapping from submission status to label and visual treatment; render statuses through `StatusBadge` rather than duplicating classes.
- Upload, processing, and autosave are simulated with `setTimeout`. There is no API client, backend, persistence, dependency-injection container, or global state library.
- Tailwind utilities and `clsx` compose styles; shared tokens live in `frontend/src/styles/theme.css`.

### Target system

The design baseline selects a modular monolith with a separate worker:

```text
React/Vite SPA -> REST/OpenAPI -> FastAPI modular monolith -> PostgreSQL/file storage
                                      |
                                      +-> Redis -> Celery worker -> PDF/rule/LLM evaluators
```

Frontend technology is still contradictory across current sources: the design baseline selects React/Vite, while `docs/requirements/SRS.docx` specifies Next.js 16 with App Router and Server Components; the runnable prototype uses React/Vite. Treat the production frontend choice as unresolved and escalate it before creating production architecture or migrating dependencies.

Expected flow: Student uploads a text-native PDF -> API validates and versions it -> worker extracts Document IR once -> evaluators emit criterion results, findings, and evidence anchors -> Teacher reviews/overrides -> Teacher approves -> Teacher separately publishes -> Student sees the immutable published result and may request review.

Preserve these boundaries:

- `Approve` and `Publish` are distinct actions and states.
- Automated scores are proposals, never autonomously published grades.
- Student-facing views must not expose prompts, model details, raw confidence, queue/worker names, or rejected findings.
- `docs/design/PROTOTYPE_CONTEXT.md` and the prototype use `Course -> Assignment`; the design baseline uses `Assessment` plus `AssessmentMembership`, while the current SRS lists `Assessment` and `Submission` without a membership entity. Escalate the persistent domain model instead of silently standardizing on any one hierarchy.
- Target backend modules are `identity`, `assessment`, `rubric`, `submission`, `analysis`, `review`, `appeal`, and `operations`; communicate through in-process service interfaces/domain events, not internal HTTP.

## Key Directories

- `frontend/src/app/`: current shell, mock data, role navigation, and all prototype screens.
- `frontend/src/styles/`: Tailwind v4 source scanning, font imports, and theme tokens.
- `docs/design/`: product scope, business rules, target stack, lifecycle states, and prototype UX context.
- `docs/requirements/`: current SRS in `SRS.docx`; `archive/` contains the superseded draft.
- `docs/planning/`: WBS and delivery planning; use for schedule context, not final architecture decisions.

## Development Commands

Run frontend commands from `frontend/`; the repository root has no `package.json`.

```bash
cd frontend
pnpm install   # install from pnpm-lock.yaml
pnpm dev       # start the Vite development server
pnpm build     # create the production bundle in frontend/dist/
```

Only `dev` and `build` scripts exist. Do not claim or invoke `pnpm test`, `pnpm lint`, `pnpm format`, or `pnpm typecheck` until those scripts and tools are added.

## Code Conventions & Common Patterns

- Use TypeScript React function components. Components and type aliases are PascalCase (`ReviewWorkspace`, `StudentUpload`, `Role`, `View`); variables and handlers are camelCase (`selectedCourseId`, `saveAssignment`). View/status literals use lowercase kebab-case (`teacher-review`, `needs-review`).
- Keep exhaustive unions and lookup maps aligned: adding a `View` normally requires updates to navigation, breadcrumbs, role switching, and the root render dispatch; adding a `Status` requires a `STATUS` entry.
- Keep shared entity state at the nearest common owner and pass typed props/callbacks. Keep transient UI state local. The current prototype has no Redux/Zustand or dependency-injection pattern; do not introduce one without an evidenced cross-feature need.
- Reuse configuration-driven UI such as `STATUS`/`StatusBadge` instead of copying labels or semantic colors.
- Preserve explicit async states such as `saving | saved | error` and `uploading | checking | done | error`. Current timers are mock behavior, not production concurrency. The target design calls for generated OpenAPI types, TanStack Query for server state, and bounded async work outside the web process.
- Use Tailwind utilities and `clsx` for conditional classes. Reuse `theme.css` tokens and the neutral wireframe palette; avoid gradients, decorative effects, dashboard templates, and status communicated by color alone.
- System copy, navigation, validation, and buttons should be English; user-entered names may be Vietnamese. Errors should state the cause and the next action. Student errors must hide infrastructure details.
- Preserve canonical domain terms such as `RubricVersion`, `DocumentVersion`, `AnalysisJob`, `CriterionResult`, `Finding`, `EvidenceAnchor`, `ReviewDecision`, and `PublishedResultVersion`.
- Treat uploaded PDF text as untrusted input. Never log PDF content, credentials, session cookies, API keys, or full prompts.

## Important Files

- `README.md`: repository purpose and top-level layout.
- `frontend/src/main.tsx`: browser entry point.
- `frontend/src/app/App.tsx`: current prototype architecture and behavior.
- `frontend/src/styles/index.css`: style entry point; imports fonts, Tailwind, and theme tokens.
- `frontend/package.json`: executable scripts and pinned frontend dependencies.
- `frontend/vite.config.ts`: React and Tailwind Vite plugins.
- `frontend/pnpm-lock.yaml`: dependency lockfile; keep synchronized with `package.json`.
- `frontend/pnpm-workspace.yaml`: package root, approved native builds, and supported OS/CPU combinations.
- `docs/design/PROJECT_SCOPE_BUSINESS_RULES_TECH_STACK.md`: product scope, business rules, target architecture, quality gates, and acceptance criteria.
- `docs/design/PROTOTYPE_CONTEXT.md`: role-specific screens, UX flows, copy, states, and layout constraints.
- `docs/requirements/SRS.docx`: current requirements source.

## Runtime/Tooling Preferences

- Use pnpm `11.19.0`, as declared by `frontend/package.json`; do not create npm or Yarn lockfiles.
- The target architecture specifies Node.js 24 LTS, but the repository has no `.nvmrc`, Volta configuration, or `engines` constraint yet. Treat Node 24 as a documented target, not an enforced current prerequisite.
- Current code is ESM (`"type": "module"`) and pins React `18.3.1`, Vite `6.3.5`, and Tailwind CSS `4.1.12`. The target design mentions newer React/Vite/TypeScript versions; dependency migration requires an explicit decision and validation, not an incidental update.
- There is currently no `tsconfig.json`, standalone `typescript` package, ESLint, Prettier, test runner, backend runtime, Docker Compose stack, or CI workflow.
- Do not commit `node_modules/`, `frontend/dist/`, `.vite/`, logs, environment files, or local agent/tooling state.

## Testing & QA

No automated test files, test configuration, test script, coverage tool, or coverage threshold currently exists. For present frontend changes:

1. Run `pnpm build` from `frontend/`; this verifies Vite bundling only, not standalone TypeScript type checking.
2. Run `pnpm dev` and exercise the affected Admin, Teacher, or Student flow in a browser.
3. Check loading, empty, error, disabled, and success states where relevant; verify Student behavior at 320 CSS px and Teacher/Admin desktop layouts where affected.

The target QA stack in the design baseline is pytest for backend unit/integration tests, Vitest for frontend units, Playwright for critical end-to-end flows, axe-core for accessibility, plus Ruff, mypy, ESLint, and TypeScript strict mode. These are requirements, not installed tools. When introducing a harness, add exact package scripts and update this guide rather than documenting hypothetical commands.

AT-28 requires lint/type checks, unit, integration, and critical-path E2E in CI. AT-30 defines the critical flow: Teacher creates/publishes a rubric -> Student submits a PDF -> worker processes -> Teacher reviews/approves/publishes -> Student opens evidence and submits a review request. Security QA must cover upload validation, object authorization, prompt injection, log redaction, and expiring file access. Evaluator activation has criterion-level benchmark gates; do not substitute a generic code-coverage number for those product-quality thresholds.
