FROM oven/bun:1-alpine AS builder

WORKDIR /app

COPY services/web/package.json services/web/bun.lock ./
RUN bun install --frozen-lockfile

COPY services/web/ ./
RUN bun run build


FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# SPA fallback + reverse proxy to mcp_server
RUN printf 'server {\n\
    listen 80;\n\
    location /v1 {\n\
        proxy_pass http://mcp_server:8000;\n\
    }\n\
    location / {\n\
        root /usr/share/nginx/html;\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
