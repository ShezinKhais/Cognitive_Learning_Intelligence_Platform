# C.L.I.P frontend image for the demo deployment. Build context: frontend/.
#
# Stage 1 builds the static bundle. Stage 2 serves it with nginx, which also
# proxies /api and /ws to the backend (see nginx.conf).
# Base images pinned by digest: node 24.22.3 and nginx 1.31.7, the versions of
# the image that passed the demo. npm ci pins the packages from the lockfile.
FROM node:24.22.3-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
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
ARG CLIP_RELEASE_SHA=unknown
RUN CLIP_RELEASE_SHA="$CLIP_RELEASE_SHA" node scripts/write-release.mjs

FROM nginx:1.31.7-alpine@sha256:892bb2152464f0c5d8972593a5f5afaf8054552580b699d95f8ff4af08c2d33d
ARG CLIP_RELEASE_SHA=unknown
LABEL org.opencontainers.image.revision=$CLIP_RELEASE_SHA
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
