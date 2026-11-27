# syntax=docker/dockerfile:1
# Build context = repo root: docker build -f services/ui/Dockerfile -t $REGISTRY/ui:$(git rev-parse --short HEAD) .
FROM node:20.18.1-alpine AS build
WORKDIR /app
COPY services/ui/package.json services/ui/package-lock.json* ./
RUN npm ci || npm install
COPY services/ui/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27.3-alpine
COPY services/ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY --chmod=755 services/ui/docker-entrypoint.sh /docker-entrypoint-ui.sh
USER 101
EXPOSE 8080
ENTRYPOINT ["/docker-entrypoint-ui.sh"]
