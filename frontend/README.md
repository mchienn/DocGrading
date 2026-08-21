
# DocGrading Frontend

React/Vite prototype for the Admin, Teacher and Student workspaces. It uses mock data for flow and layout review and is not connected to a backend.

Original design: [Figma — Follow Markdown Guide](https://www.figma.com/design/VNMmj3UUihw1Wp1duygxZl/Follow-Markdown-Guide).

## Run locally

```bash
pnpm install
pnpm dev
```

Production build:

```bash
pnpm build
```

## Structure

- `src/app/`: application shell, mock data and role workspaces.
- `src/styles/`: Tailwind setup and neutral visual theme.
- `../docs/design/PROTOTYPE_CONTEXT.md`: role, screen and design-flow context.
