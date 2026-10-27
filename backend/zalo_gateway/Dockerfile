# ==============================================================================
# Multi-stage Dockerfile for Zalo Gateway Microservice (< 60MB RAM)
# ==============================================================================

# Stage 1: Dependencies installation
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force

# Stage 2: Production runtime
FROM node:20-alpine AS runner

LABEL org.opencontainers.image.title="FnBOps Optional Zalo Gateway" \
      org.opencontainers.image.vendor="Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/nguyendaihoanh/fnbop"

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=8177
ENV SESSION_DIR=/app/data/zalo_session

# Create directories and set ownership for non-root 'node' user
RUN mkdir -p /app/data/zalo_session && chown -R node:node /app

COPY --chown=node:node --from=deps /app/node_modules ./node_modules
COPY --chown=node:node package.json ./
COPY --chown=node:node server.js ./

USER node

EXPOSE 8177

HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:8177/health', (r) => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "--max-old-space-size=64", "server.js"]
