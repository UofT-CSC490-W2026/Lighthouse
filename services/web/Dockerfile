FROM oven/bun:1-alpine AS builder

WORKDIR /app

COPY services/web/package.json services/web/bun.lock ./
RUN bun install --frozen-lockfile

COPY services/web/ ./
RUN bun run build


FROM nginx:alpine

ARG ENABLE_LOCAL_PROXY=false
ARG MCP_PROXY_UPSTREAM=mcp_server:8000

COPY --from=builder /app/dist /usr/share/nginx/html

# Local Docker Compose needs same-origin proxying to mcp_server.
# The AWS image should serve static files only and let the ALB route /v1 and /mcp.
RUN if [ "$ENABLE_LOCAL_PROXY" = "true" ]; then \
      printf 'server {\n\
    listen 80;\n\
    location /v1 {\n\
        proxy_pass http://%s;\n\
    }\n\
    location /mcp {\n\
        proxy_pass http://%s;\n\
    }\n\
    location / {\n\
        root /usr/share/nginx/html;\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' "$MCP_PROXY_UPSTREAM" "$MCP_PROXY_UPSTREAM" > /etc/nginx/conf.d/default.conf; \
    else \
      printf 'server {\n\
    listen 80;\n\
    location / {\n\
        root /usr/share/nginx/html;\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf; \
    fi

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
