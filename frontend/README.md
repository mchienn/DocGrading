
# DocGrading Frontend

React/Vite client for Admin, Teacher, and Student workspaces. Active product routes use FastAPI session, Course, Assignment, Rubric, PDF upload, analysis-job, submission queue, PDF.js review with bidirectional evidence, review draft/evidence, approval/publication, published-result, and criterion review-request APIs. Notification, audit, administration, and resubmission/version-comparison screens remain outside product routing.

Original design: [Figma — Follow Markdown Guide](https://www.figma.com/design/VNMmj3UUihw1Wp1duygxZl/Follow-Markdown-Guide).

## Run locally

Start FastAPI on `http://127.0.0.1:8000`, then:

```bash
pnpm install
pnpm dev
```

Vite proxies `/api` and `/health` to FastAPI. Presigned PDF uploads and viewer downloads require object-storage CORS for the frontend origin.

```bash
pnpm typecheck
pnpm build
pnpm generate:api
```

`generate:api` rebuilds `src/api/schema.ts` from checked-in `openapi.json`. Refresh `openapi.json` from `create_app().openapi()` after backend contract changes.

## Structure

- `src/app/`: authenticated role routing and API-backed workspace shell.
- `src/api/`: shared OpenAPI client and generated schema.
- `src/components/`: active views plus unregistered prototype references.
- `src/styles/`: Tailwind setup and neutral visual theme.
- `../docs/design/PROTOTYPE_CONTEXT.md`: role, screen, and design-flow reference.
