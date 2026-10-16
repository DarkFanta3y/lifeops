"""将本地 MCP 启动配置适配为容器内程序，不修改宿主机 .env。"""

from __future__ import annotations

import json
import os
import sys


NPM_COMMANDS = {
    "@upstash/context7-mcp": "context7-mcp",
    "@playwright/mcp": "playwright-mcp",
    "@modelcontextprotocol/server-memory": "mcp-server-memory",
    "@modelcontextprotocol/server-sequential-thinking": "mcp-server-sequential-thinking",
    "@modelcontextprotocol/server-filesystem": "mcp-server-filesystem",
    "12306-mcp": "12306-mcp",
}
PRESETS = {
    "context7": "context7-mcp",
    "playwright": "playwright-mcp",
    "memory": "mcp-server-memory",
    "sequential_thinking": "mcp-server-sequential-thinking",
    "filesystem": "mcp-server-filesystem",
}


def container_servers(raw: str, presets: str) -> dict:
    servers = json.loads(raw or "{}")
    for config in servers.values():
        command = config.get("command")
        args = config.get("args", [])
        if command == "docker" and any(
            arg.startswith("ghcr.io/github/github-mcp-server") for arg in args
        ):
            image_index = next(
                i for i, arg in enumerate(args)
                if arg.startswith("ghcr.io/github/github-mcp-server")
            )
            config.update(command="github-mcp-server", args=args[image_index + 1:] or ["stdio"])
        elif command == "uvx" and args and args[0] == "workspace-mcp":
            config.update(command="workspace-mcp", args=args[1:])
        elif command == "npx":
            arguments = [arg for arg in args if arg not in ("-y", "--yes")]
            if arguments:
                package = arguments[0].removesuffix("@latest")
                if package in NPM_COMMANDS:
                    config.update(command=NPM_COMMANDS[package], args=arguments[1:])
        env = config.get("env", {})
        if "GOOGLE_MCP_CREDENTIALS_DIR" in env:
            env["GOOGLE_MCP_CREDENTIALS_DIR"] = os.environ["GOOGLE_MCP_CREDENTIALS_DIR"]

    for name in presets.split(","):
        name = name.strip().replace("-", "_")
        if name not in PRESETS or name in servers:
            continue
        servers[name] = {"command": PRESETS[name], "args": [], "env": {}}
        if name == "filesystem":
            servers[name]["args"] = os.environ.get(
                "LIFEOPS_FILESYSTEM_MCP_ROOTS", "/workspace"
            ).split(",")

    for config in servers.values():
        if config.get("command") == "playwright-mcp":
            config["args"] = [*config.get("args", []), "--headless", "--no-sandbox"]
            if "--executable-path" not in config["args"]:
                config["args"].extend(["--executable-path", "/usr/local/bin/lifeops-chromium"])
    # OAuth 初始化可能较慢，先连接无需授权的工具，避免占满 Web 启动超时。
    return dict(sorted(servers.items(), key=lambda item: item[0] == "google_workspace"))


if __name__ == "__main__":
    os.environ["LIFEOPS_MCP_SERVERS"] = json.dumps(container_servers(
        os.environ.get("LIFEOPS_MCP_SERVERS", ""),
        os.environ.get("LIFEOPS_MCP_PRESETS", ""),
    ))
    args = sys.argv[1:] or ["lifeops-web"]
    os.execvp(args[0], args)
