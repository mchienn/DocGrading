FROM node:22-bookworm-slim AS build

RUN npm install --global pnpm@11.19.0

WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2.10.2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

EXPOSE 5173
