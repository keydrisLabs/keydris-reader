FROM node:24-alpine AS builder
WORKDIR /app

# Workspace manifests first, so a source-only change reuses the install layer.
COPY package.json package-lock.json ./
COPY packages/kit-reader/package.json ./packages/kit-reader/
COPY examples/github-mcp-server/package.json ./examples/github-mcp-server/
RUN npm ci

COPY packages/kit-reader/tsconfig.json packages/kit-reader/tsconfig.build.json ./packages/kit-reader/
COPY packages/kit-reader/src ./packages/kit-reader/src
COPY examples/github-mcp-server/tsconfig.json ./examples/github-mcp-server/
COPY examples/github-mcp-server/src ./examples/github-mcp-server/src

# Builds the library first: the demo resolves it through the workspace symlink
# to its dist/, so it has to exist before the demo compiles.
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=8787

# The same manifest set, so `npm ci` recreates the @keydris/kit-reader symlink.
COPY package.json package-lock.json ./
COPY packages/kit-reader/package.json ./packages/kit-reader/
COPY examples/github-mcp-server/package.json ./examples/github-mcp-server/
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/packages/kit-reader/dist ./packages/kit-reader/dist
COPY --from=builder /app/examples/github-mcp-server/dist ./examples/github-mcp-server/dist

EXPOSE 8787

CMD ["node", "examples/github-mcp-server/dist/index.js"]
