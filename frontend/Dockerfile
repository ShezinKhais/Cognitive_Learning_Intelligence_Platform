# C.L.I.P frontend image for the demo deployment. Build context: frontend/.
#
# Stage 1 builds the static bundle. Stage 2 serves it with nginx, which also
# proxies /api and /ws to the backend (see nginx.conf).
FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# Vite bakes these in at build time. They are feature switches, not secrets.
ARG VITE_MATERIAL_PIPELINE_ENABLED=true
ARG VITE_LIVE_SESSIONS_ENABLED=true
ARG VITE_SOCRATIC_CHAT_ENABLED=true
ARG VITE_LOCAL_ATTENTION_ENABLED=false
ARG VITE_TEAMS_MOCK_ENABLED=false
ENV VITE_MATERIAL_PIPELINE_ENABLED=$VITE_MATERIAL_PIPELINE_ENABLED \
    VITE_LIVE_SESSIONS_ENABLED=$VITE_LIVE_SESSIONS_ENABLED \
    VITE_SOCRATIC_CHAT_ENABLED=$VITE_SOCRATIC_CHAT_ENABLED \
    VITE_LOCAL_ATTENTION_ENABLED=$VITE_LOCAL_ATTENTION_ENABLED \
    VITE_TEAMS_MOCK_ENABLED=$VITE_TEAMS_MOCK_ENABLED

COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
