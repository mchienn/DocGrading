
# DocGrading Frontend

React/Vite client for Admin, Teacher, and Student workspaces. Active product routes use FastAPI session, Course, roster, expiring Course join code/link/QR with explicit Student confirmation, Assignment, Rubric, PDF upload, analysis-job, submission queue, PDF.js review with bidirectional evidence, review draft/evidence, approval/publication, published-result, criterion review-request/response, polling notification/read, and Admin dashboard/user/job/audit/force-release APIs. Resubmission/version-comparison screens remain outside product routing.

Original design: [Figma — Follow Markdown Guide](https://www.figma.com/design/VNMmj3UUihw1Wp1duygxZl/Follow-Markdown-Guide).

## Run

From repository root, build and run the full stack:

```bash
docker compose up --build
```

The frontend image serves Vite production assets through Caddy at `http://localhost:5173`.

For frontend-only development, start FastAPI on `http://127.0.0.1:8000`, then:

```bash
pnpm install
pnpm dev
```

Frontend-only development uses Vite's `/api` and `/health` proxy. The Compose image provides the same paths through Caddy. Presigned PDF uploads and viewer downloads require object-storage CORS for the frontend origin.

```bash
pnpm typecheck
pnpm build
pnpm generate:api
```

`generate:api` rebuilds `src/api/schema.ts` from checked-in `openapi.json`. Refresh `openapi.json` from `create_app().openapi()` after backend contract changes.

## Release deployment

Compose host ports are loopback-only for development and UAT. Production must terminate TLS directly at Caddy and expose one public HTTPS origin. Compose pins Caddy to `172.30.255.3`; if network topology changes, set API `FORWARDED_ALLOW_IPS` to the exact Caddy address. If an upstream TLS load balancer is required, configure Caddy `trusted_proxies` with that proxy's exact CIDR plus `trusted_proxies_strict` so client IP rate limits remain per-client. Set `APP_ENV` outside `development`, set a random `JOIN_RATE_LIMIT_HASH_SECRET` of at least 32 characters, set `FRONTEND_ORIGIN` to the HTTPS origin, use non-placeholder storage credentials with an HTTPS public storage endpoint, and keep API port 8000 private; browser API traffic stays same-origin through Caddy.

## Structure

- `src/app/`: authenticated role routing and API-backed workspace shell.
- `src/api/`: shared OpenAPI client and generated schema.
- `src/components/`: active views plus unregistered prototype references.
- `src/styles/`: Tailwind setup and neutral visual theme.
- `../docs/design/PROTOTYPE_CONTEXT.md`: role, screen, and design-flow reference.
