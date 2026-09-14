FROM node:22-bookworm-slim

RUN npm install --global pnpm@11.19.0

WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .

EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
