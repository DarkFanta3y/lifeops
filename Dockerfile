FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS node
FROM ghcr.io/github/github-mcp-server@sha256:ffced0d76e77428532a2ced185516992d77fd146d69eec2f244e6237d1a97796 AS github-mcp
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=github-mcp /server/github-mcp-server /usr/local/bin/github-mcp-server

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PATH="/app/.venv/bin:/root/.local/bin:$PATH"

WORKDIR /app

RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

# 固定 MCP 主版本，并在构建时安装，避免启动期 npx 下载超过连接超时。
RUN --mount=type=cache,target=/root/.npm \
    npm install --global --loglevel=info --fetch-retries=1 --fetch-timeout=60000 \
      @upstash/context7-mcp@4.4.1 \
      @playwright/mcp@0.0.83 \
      @modelcontextprotocol/server-memory@1.0.0 \
      @modelcontextprotocol/server-sequential-thinking@1.0.0 \
      @modelcontextprotocol/server-filesystem@1.0.0 \
      12306-mcp@0.3.10

# 使用 HTTPS 下载系统包；只安装无界面浏览器，缓存系统包以支持断点重试。
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
       /etc/apt/sources.list.d/debian.sources \
    && node /usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright/cli.js \
       install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

RUN python -c "from pathlib import Path; files = [p for p in Path('/opt/playwright').rglob('*') if p.is_file() and p.name in ('headless_shell', 'chrome-headless-shell')]; assert len(files) == 1, files; Path('/usr/local/bin/lifeops-chromium').symlink_to(files[0])"

RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install --python /usr/local/bin/python workspace-mcp==2.1.0

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
COPY docker/ ./docker/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

EXPOSE 8082
ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["lifeops-web"]
