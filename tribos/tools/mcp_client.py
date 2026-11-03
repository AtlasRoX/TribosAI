"""
A client for external MCP tool servers (docs/plans/tribos-harness-landscape.md item 10).

Tribos already serves MCP; this lets it *call* MCP servers, for example lean-lsp-mcp (Lean goals, diagnostics and
Mathlib search) or LeanExplore. Servers are configured in TRIBOS_MCP_CLIENT_SERVERS as JSON:

    {"lean": {"command": ["uvx", "lean-lsp-mcp"], "cwd": "X:/lean/mathlib_project",
              "tools": ["lean_leansearch", "lean_loogle"], "timeout_s": 60}}

Each listed tool is registered as `mcp_<server>_<tool>` (adapter REMOTE_MCP), so plans and the approval layer see it
like any other tool. Only the stdio transport is supported: newline-delimited JSON-RPC 2.0 on the server's
stdin/stdout. One process per server is started on first use and reused; it is restarted after a failure. To see what a
server offers: `python -m tribos.tools.mcp_client <server>`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "2025-06-18"


class MCPToolInput(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict, description="The tool's arguments, as its schema defines")


class StdioMCPClient:
    """One MCP server process spoken to over stdio."""

    def __init__(self, name: str, command: list[str], cwd: str | None = None, env: dict[str, str] | None = None,
                 timeout_s: float = 60.0) -> None:
        self.name, self.command, self.cwd, self.timeout_s = name, command, cwd, timeout_s
        self.env = {**os.environ, **(env or {})}
        self._proc: asyncio.subprocess.Process | None = None
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 0

    def _guard(self) -> asyncio.Lock:
        """The lock of the running event loop; a process started on another (finished) loop is dropped."""
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop, self._lock, self._proc = loop, asyncio.Lock(), None
        assert self._lock is not None
        return self._lock

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(message) + "\n").encode())
        await self._proc.stdin.drain()

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        assert self._proc is not None and self._proc.stdout is not None
        self._next_id += 1
        rid = self._next_id
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            line = await asyncio.wait_for(self._proc.stdout.readline(), self.timeout_s)
            if not line:
                raise ConnectionError(f"MCP server {self.name} closed its output")
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # a log line on stdout
            if msg.get("id") != rid:
                continue  # a notification or another request's reply
            if "error" in msg:
                raise RuntimeError(f"MCP {method}: {msg['error'].get('message', msg['error'])}")
            return msg.get("result")

    async def _start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self.command, cwd=self.cwd, env=self.env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        await self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "tribos", "version": "1.0"}})
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _ensure(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            await self._start()

    async def close(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
        self._proc = None

    async def list_tools(self) -> list[dict[str, Any]]:
        async with self._guard():
            await self._ensure()
            return list((await self._request("tools/list")).get("tools") or [])

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """{"text": joined text content, "is_error": bool, "structured": structuredContent or None}."""
        result: dict[str, Any] = {}
        async with self._guard():
            for attempt in (1, 2):
                try:
                    await self._ensure()
                    result = await self._request("tools/call", {"name": tool, "arguments": arguments}) or {}
                    break
                except (TimeoutError, ConnectionError, OSError):
                    await self.close()
                    if attempt == 2:
                        raise
        text = "\n".join(str(c.get("text", "")) for c in result.get("content") or [] if c.get("type") == "text")
        return {"text": text, "is_error": bool(result.get("isError")), "structured": result.get("structuredContent")}


_CLIENTS: dict[str, StdioMCPClient] = {}


def configured_servers() -> dict[str, dict[str, Any]]:
    from ..config.settings import get_str

    raw = str(get_str("TRIBOS_MCP_CLIENT_SERVERS") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("TRIBOS_MCP_CLIENT_SERVERS is not valid JSON; no MCP servers registered")
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("command"), list)}


def client_for(name: str, spec: dict[str, Any]) -> StdioMCPClient:
    if name not in _CLIENTS:
        _CLIENTS[name] = StdioMCPClient(name, [str(c) for c in spec["command"]], spec.get("cwd"),
                                        {str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                                        float(spec.get("timeout_s") or 60.0))
    return _CLIENTS[name]


def register_mcp_tools(registry: Any) -> list[str]:
    """Register every tool listed for every configured server; returns the registered names."""
    from .registry import AdapterType, ErrorType, ToolResult, ToolUniverseEntry

    names: list[str] = []
    for server, spec in configured_servers().items():
        for tool in spec.get("tools") or []:
            reg_name = f"mcp_{server}_{tool}"

            async def execute(arguments: dict[str, Any] | None = None, _s: str = server, _t: str = tool,
                              _spec: dict[str, Any] = spec, _n: str = reg_name) -> ToolResult:
                try:
                    out = await client_for(_s, _spec).call(_t, dict(arguments or {}))
                except Exception as exc:  # noqa: BLE001 - reported as a failed tool call
                    return ToolResult(success=False, tool_name=_n, error=f"MCP server {_s}: {exc}",
                                      error_type=ErrorType.UPSTREAM_API_ERROR)
                return ToolResult(success=not out["is_error"], tool_name=_n, data=out,
                                  error=out["text"][:500] if out["is_error"] else None)

            registry.register(
                ToolUniverseEntry(name=reg_name, description=str(spec.get("descriptions", {}).get(tool)
                                                                 or f"{tool} on the external MCP server '{server}'"),
                                  domain="general", adapter_type=AdapterType.REMOTE_MCP, input_schema=MCPToolInput,
                                  timeout_seconds=float(spec.get("timeout_s") or 60.0), tags=["mcp", server, tool],
                                  is_async=True),
                executor=execute,
            )
            names.append(reg_name)
    return names


async def _main(server: str) -> None:
    spec = configured_servers().get(server)
    if spec is None:
        print(f"no MCP server named {server!r} in TRIBOS_MCP_CLIENT_SERVERS")
        return
    client = client_for(server, spec)
    try:
        for t in await client.list_tools():
            print(f"{t.get('name')}: {str(t.get('description') or '').splitlines()[0][:120] if t.get('description') else ''}")
    finally:
        await client.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else ""))


__all__ = ["MCPToolInput", "StdioMCPClient", "configured_servers", "register_mcp_tools"]
