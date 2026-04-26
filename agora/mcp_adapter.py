from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Literal


MCPConnectionStatus = Literal["connected", "disconnected", "connecting", "error", "unknown"]
MCPTransportKind = Literal["stdio", "http", "sse", "sse-ide", "websocket", "ws-ide", "claudeai-proxy", "unknown"]
MCPItemKind = Literal["tool", "resource", "prompt", "command"]
_MCP_ACTION_TOKEN_RE = re.compile(r"[^a-z0-9_]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, *, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _clean_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            items.append(text)
    return items


def _normalize_server_id(value: object) -> str:
    return _clean_text(value).replace(" ", "-").lower()


def _normalize_action_token(value: object) -> str:
    text = _clean_text(value).strip().lower().replace("-", "_")
    text = _MCP_ACTION_TOKEN_RE.sub("_", text).strip("_")
    return text


def _truncate_text(value: object, *, max_chars: int = 180) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 1)].rstrip()}…"


def build_mcp_tool_action_name(server_id: object, tool_name: object) -> str:
    server_token = _normalize_action_token(_normalize_server_id(server_id))
    tool_token = _normalize_action_token(tool_name)
    if not server_token or not tool_token:
        return ""
    return f"mcp__{server_token}__{tool_token}"


def build_mcp_prompt_action_name(server_id: object, prompt_name: object) -> str:
    server_token = _normalize_action_token(_normalize_server_id(server_id))
    prompt_token = _normalize_action_token(prompt_name)
    if not server_token or not prompt_token:
        return ""
    return f"mcp_prompt__{server_token}__{prompt_token}"


def parse_mcp_tool_action_name(action_name: object) -> tuple[str, str] | None:
    text = _clean_text(action_name).lower()
    if not text.startswith("mcp__"):
        return None
    remainder = text[5:]
    if "__" not in remainder:
        return None
    server_token, tool_token = remainder.split("__", 1)
    server_token = _normalize_action_token(server_token)
    tool_token = _normalize_action_token(tool_token)
    if not server_token or not tool_token:
        return None
    return server_token, tool_token


def parse_mcp_prompt_action_name(action_name: object) -> tuple[str, str] | None:
    text = _clean_text(action_name).lower()
    if not text.startswith("mcp_prompt__"):
        return None
    remainder = text[12:]
    if "__" not in remainder:
        return None
    server_token, prompt_token = remainder.split("__", 1)
    server_token = _normalize_action_token(server_token)
    prompt_token = _normalize_action_token(prompt_token)
    if not server_token or not prompt_token:
        return None
    return server_token, prompt_token


def is_mcp_action_name(action_name: object) -> bool:
    return parse_mcp_tool_action_name(action_name) is not None or parse_mcp_prompt_action_name(action_name) is not None


@dataclass(frozen=True)
class MCPServerManifest:
    server_id: str
    name: str
    transport: MCPTransportKind
    endpoint: str
    description: str = ""
    instructions: str = ""
    enabled: bool = False
    read_only_only: bool = True
    tool_count: int = 0
    resource_count: int = 0
    prompt_count: int = 0
    command_count: int = 0
    source_scope: str = ""
    source_path: str = ""
    approval_state: str = "approved"
    failure_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPConnectionState:
    server_id: str
    status: MCPConnectionStatus
    connected: bool
    last_checked_at: str
    failure_reason: str = ""
    transport: MCPTransportKind = "unknown"
    endpoint: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPNormalizedTool:
    server_id: str
    name: str
    title: str
    description: str
    kind: MCPItemKind = "tool"
    source_kind: str = "mcp"
    read_only: bool = True
    destructive: bool = False
    allowed: bool = True
    unavailable_reason: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPNormalizedResource:
    server_id: str
    name: str
    uri: str
    title: str
    description: str
    kind: MCPItemKind = "resource"
    source_kind: str = "mcp"
    read_only: bool = True
    allowed: bool = True
    unavailable_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPNormalizedPrompt:
    server_id: str
    name: str
    title: str
    description: str
    argument_names: tuple[str, ...] = ()
    kind: MCPItemKind = "prompt"
    source_kind: str = "mcp"
    allowed: bool = True
    unavailable_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPNormalizedCommand:
    server_id: str
    name: str
    action_name: str
    title: str
    description: str
    argument_names: tuple[str, ...] = ()
    kind: MCPItemKind = "command"
    source_kind: str = "mcp"
    allowed: bool = True
    unavailable_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPServerSurface:
    manifest: MCPServerManifest
    connection: MCPConnectionState
    tools: tuple[MCPNormalizedTool, ...] = ()
    resources: tuple[MCPNormalizedResource, ...] = ()
    prompts: tuple[MCPNormalizedPrompt, ...] = ()
    commands: tuple[MCPNormalizedCommand, ...] = ()

    def model_dump(self) -> dict[str, Any]:
        return {
            "manifest": {
                "server_id": self.manifest.server_id,
                "name": self.manifest.name,
                "transport": self.manifest.transport,
                "endpoint": self.manifest.endpoint,
                "description": self.manifest.description,
                "instructions": self.manifest.instructions,
                "enabled": self.manifest.enabled,
                "read_only_only": self.manifest.read_only_only,
                "tool_count": self.manifest.tool_count,
                "resource_count": self.manifest.resource_count,
                "prompt_count": self.manifest.prompt_count,
                "command_count": self.manifest.command_count,
                "source_scope": self.manifest.source_scope,
                "source_path": self.manifest.source_path,
                "approval_state": self.manifest.approval_state,
                "failure_reason": self.manifest.failure_reason,
            },
            "connection": {
                "server_id": self.connection.server_id,
                "status": self.connection.status,
                "connected": self.connection.connected,
                "last_checked_at": self.connection.last_checked_at,
                "failure_reason": self.connection.failure_reason,
                "transport": self.connection.transport,
                "endpoint": self.connection.endpoint,
            },
            "tools": [self._tool_dump(item) for item in self.tools],
            "resources": [self._resource_dump(item) for item in self.resources],
            "prompts": [self._prompt_dump(item) for item in self.prompts],
            "commands": [self._command_dump(item) for item in self.commands],
        }

    @staticmethod
    def _tool_dump(item: MCPNormalizedTool) -> dict[str, Any]:
        return {
            "server_id": item.server_id,
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "kind": item.kind,
            "source_kind": item.source_kind,
            "read_only": item.read_only,
            "destructive": item.destructive,
            "allowed": item.allowed,
            "unavailable_reason": item.unavailable_reason,
            "input_schema": dict(item.input_schema),
        }

    @staticmethod
    def _resource_dump(item: MCPNormalizedResource) -> dict[str, Any]:
        return {
            "server_id": item.server_id,
            "name": item.name,
            "uri": item.uri,
            "title": item.title,
            "description": item.description,
            "kind": item.kind,
            "source_kind": item.source_kind,
            "read_only": item.read_only,
            "allowed": item.allowed,
            "unavailable_reason": item.unavailable_reason,
        }

    @staticmethod
    def _prompt_dump(item: MCPNormalizedPrompt) -> dict[str, Any]:
        return {
            "server_id": item.server_id,
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "argument_names": list(item.argument_names),
            "kind": item.kind,
            "source_kind": item.source_kind,
            "allowed": item.allowed,
            "unavailable_reason": item.unavailable_reason,
        }

    @staticmethod
    def _command_dump(item: MCPNormalizedCommand) -> dict[str, Any]:
        return {
            "server_id": item.server_id,
            "name": item.name,
            "action_name": item.action_name,
            "title": item.title,
            "description": item.description,
            "argument_names": list(item.argument_names),
            "kind": item.kind,
            "source_kind": item.source_kind,
            "allowed": item.allowed,
            "unavailable_reason": item.unavailable_reason,
        }


class MCPAdapter:
    """Fail-closed, typed normalization for a narrow-but-live MCP surface."""

    def __init__(self, *, read_only_only: bool = True) -> None:
        self.read_only_only = bool(read_only_only)

    def normalize_server_manifest(self, payload: dict[str, Any] | None) -> MCPServerManifest:
        raw = dict(payload or {})
        server_id = _normalize_server_id(raw.get("server_id") or raw.get("id") or raw.get("name"))
        name = _clean_text(raw.get("name"), default=server_id)
        transport = self._normalize_transport(raw.get("transport") or raw.get("type"))
        endpoint = _clean_text(raw.get("endpoint") or raw.get("url") or raw.get("command"))
        if not server_id or not name or transport == "unknown" or not endpoint:
            return MCPServerManifest(
                server_id=server_id or "unknown",
                name=name or server_id or "unknown",
                transport=transport,
                endpoint=endpoint,
                description=_clean_text(raw.get("description")),
                instructions=_clean_text(raw.get("instructions")),
                enabled=False,
                read_only_only=True,
                tool_count=0,
                resource_count=0,
                prompt_count=0,
                command_count=0,
                source_scope=_clean_text(raw.get("source_scope")),
                source_path=_clean_text(raw.get("source_path")),
                approval_state=_clean_text(raw.get("approval_state"), default="approved"),
                failure_reason="invalid_manifest",
                raw=raw,
            )

        tools = list(raw.get("tools") or [])
        resources = list(raw.get("resources") or [])
        prompts = list(raw.get("prompts") or [])
        commands = list(raw.get("commands") or [])
        read_only_only = self.read_only_only and not _clean_bool(raw.get("allow_write"), default=False)
        return MCPServerManifest(
            server_id=server_id,
            name=name,
            transport=transport,
            endpoint=endpoint,
            description=_clean_text(raw.get("description")),
            instructions=_clean_text(raw.get("instructions")),
            enabled=_clean_bool(raw.get("enabled"), default=True),
            read_only_only=read_only_only,
            tool_count=len(tools),
            resource_count=len(resources),
            prompt_count=len(prompts),
            command_count=len(commands),
            source_scope=_clean_text(raw.get("source_scope")),
            source_path=_clean_text(raw.get("source_path")),
            approval_state=_clean_text(raw.get("approval_state"), default="approved"),
            failure_reason="",
            raw=raw,
        )

    def normalize_connection_state(
        self,
        payload: dict[str, Any] | None,
        *,
        manifest: MCPServerManifest | None = None,
    ) -> MCPConnectionState:
        raw = dict(payload or {})
        server_id = _normalize_server_id(
            raw.get("server_id")
            or raw.get("id")
            or (manifest.server_id if manifest is not None else "")
        )
        status = self._normalize_status(raw.get("status"))
        connected = _clean_bool(raw.get("connected"), default=status == "connected")
        if manifest is not None and not manifest.enabled:
            connected = False
            status = "disconnected"
        if manifest is not None and not manifest.server_id:
            connected = False
            status = "disconnected"
        return MCPConnectionState(
            server_id=server_id or (manifest.server_id if manifest is not None else "unknown"),
            status=status,
            connected=connected,
            last_checked_at=_clean_text(raw.get("last_checked_at"), default=_utc_now_iso()),
            failure_reason=_clean_text(raw.get("failure_reason") or raw.get("reason")),
            transport=self._normalize_transport(raw.get("transport") or (manifest.transport if manifest is not None else None)),
            endpoint=_clean_text(raw.get("endpoint") or (manifest.endpoint if manifest is not None else "")),
            raw=raw,
        )

    def normalize_tool(self, payload: dict[str, Any] | None, *, server_id: str = "") -> MCPNormalizedTool:
        raw = dict(payload or {})
        name = _clean_text(raw.get("name") or raw.get("id"))
        title = _clean_text(raw.get("title"), default=name)
        description = _clean_text(raw.get("description"))
        destructive = _clean_bool(raw.get("destructive"), default=False)
        read_only = _clean_bool(raw.get("read_only"), default=not destructive)
        allowed = _clean_bool(raw.get("allowed"), default=True)
        unavailable_reason = _clean_text(raw.get("unavailable_reason") or raw.get("reason"))
        if self.read_only_only and not read_only:
            allowed = False
            unavailable_reason = unavailable_reason or "non_read_only_tool_blocked"
        if not name:
            allowed = False
            unavailable_reason = unavailable_reason or "invalid_tool"
        return MCPNormalizedTool(
            server_id=_clean_text(server_id, default="unknown"),
            name=name or "unknown",
            title=title or name or "unknown",
            description=description,
            read_only=read_only,
            destructive=destructive,
            allowed=allowed,
            unavailable_reason=unavailable_reason,
            input_schema=dict(raw.get("input_schema") or raw.get("inputSchema") or {}),
            raw=raw,
        )

    def normalize_resource(self, payload: dict[str, Any] | None, *, server_id: str = "") -> MCPNormalizedResource:
        raw = dict(payload or {})
        name = _clean_text(raw.get("name") or raw.get("id"))
        uri = _clean_text(raw.get("uri") or raw.get("url"))
        title = _clean_text(raw.get("title"), default=name or uri)
        description = _clean_text(raw.get("description"))
        read_only = _clean_bool(raw.get("read_only"), default=True)
        allowed = _clean_bool(raw.get("allowed"), default=True)
        unavailable_reason = _clean_text(raw.get("unavailable_reason") or raw.get("reason"))
        if self.read_only_only and not read_only:
            allowed = False
            unavailable_reason = unavailable_reason or "non_read_only_resource_blocked"
        if not name or not uri:
            allowed = False
            unavailable_reason = unavailable_reason or "invalid_resource"
        return MCPNormalizedResource(
            server_id=_clean_text(server_id, default="unknown"),
            name=name or "unknown",
            uri=uri or "",
            title=title or name or uri or "unknown",
            description=description,
            read_only=read_only,
            allowed=allowed,
            unavailable_reason=unavailable_reason,
            raw=raw,
        )

    def normalize_prompt(self, payload: dict[str, Any] | None, *, server_id: str = "") -> MCPNormalizedPrompt:
        raw = dict(payload or {})
        name = _clean_text(raw.get("name") or raw.get("id"))
        title = _clean_text(raw.get("title"), default=name)
        description = _clean_text(raw.get("description"))
        argument_names = tuple(
            item
            for item in (
                _clean_text(entry.get("name"))
                for entry in list(raw.get("arguments") or [])
                if isinstance(entry, dict)
            )
            if item
        )
        allowed = _clean_bool(raw.get("allowed"), default=bool(name))
        unavailable_reason = _clean_text(raw.get("unavailable_reason") or raw.get("reason"))
        if not name:
            allowed = False
            unavailable_reason = unavailable_reason or "invalid_prompt"
        return MCPNormalizedPrompt(
            server_id=_clean_text(server_id, default="unknown"),
            name=name or "unknown",
            title=title or name or "unknown",
            description=description,
            argument_names=argument_names,
            allowed=allowed,
            unavailable_reason=unavailable_reason,
            raw=raw,
        )

    def normalize_command(self, payload: dict[str, Any] | None, *, server_id: str = "") -> MCPNormalizedCommand:
        raw = dict(payload or {})
        name = _clean_text(raw.get("name") or raw.get("id"))
        action_name = _clean_text(raw.get("action_name") or build_mcp_prompt_action_name(server_id, name))
        title = _clean_text(raw.get("title"), default=name)
        description = _clean_text(raw.get("description"))
        argument_names = tuple(
            item
            for item in (
                _clean_text(entry)
                for entry in list(raw.get("argument_names") or raw.get("arg_names") or [])
            )
            if item
        )
        allowed = _clean_bool(raw.get("allowed"), default=bool(name and action_name))
        unavailable_reason = _clean_text(raw.get("unavailable_reason") or raw.get("reason"))
        if not name or not action_name:
            allowed = False
            unavailable_reason = unavailable_reason or "invalid_command"
        return MCPNormalizedCommand(
            server_id=_clean_text(server_id, default="unknown"),
            name=name or "unknown",
            action_name=action_name or "",
            title=title or name or "unknown",
            description=description,
            argument_names=argument_names,
            allowed=allowed,
            unavailable_reason=unavailable_reason,
            raw=raw,
        )

    def build_surface(
        self,
        *,
        manifest_payload: dict[str, Any] | None,
        connection_payload: dict[str, Any] | None = None,
    ) -> MCPServerSurface:
        manifest = self.normalize_server_manifest(manifest_payload)
        connection = self.normalize_connection_state(connection_payload, manifest=manifest)
        if not manifest.enabled or not connection.connected:
            return MCPServerSurface(manifest=manifest, connection=connection, tools=(), resources=(), prompts=(), commands=())

        tools = tuple(
            self.normalize_tool(item, server_id=manifest.server_id)
            for item in list(manifest.raw.get("tools") or [])
        )
        resources = tuple(
            self.normalize_resource(item, server_id=manifest.server_id)
            for item in list(manifest.raw.get("resources") or [])
        )
        prompts = tuple(
            self.normalize_prompt(item, server_id=manifest.server_id)
            for item in list(manifest.raw.get("prompts") or [])
        )
        commands = tuple(
            self.normalize_command(item, server_id=manifest.server_id)
            for item in list(manifest.raw.get("commands") or [])
        )
        if self.read_only_only:
            tools = tuple(item for item in tools if item.allowed and item.read_only)
            resources = tuple(item for item in resources if item.allowed and item.read_only)
            prompts = tuple(item for item in prompts if item.allowed)
            commands = tuple(item for item in commands if item.allowed)
        return MCPServerSurface(
            manifest=manifest,
            connection=connection,
            tools=tools,
            resources=resources,
            prompts=prompts,
            commands=commands,
        )

    def summarize_surface(self, surface: MCPServerSurface) -> dict[str, Any]:
        return {
            "server_id": surface.manifest.server_id,
            "name": surface.manifest.name,
            "enabled": surface.manifest.enabled and surface.connection.connected,
            "read_only_only": surface.manifest.read_only_only,
            "transport": surface.manifest.transport,
            "tool_names": [item.name for item in surface.tools],
            "resource_names": [item.name for item in surface.resources],
            "prompt_names": [item.name for item in surface.prompts],
            "command_names": [item.name for item in surface.commands],
            "tool_count": len(surface.tools),
            "resource_count": len(surface.resources),
            "prompt_count": len(surface.prompts),
            "command_count": len(surface.commands),
            "instructions": surface.manifest.instructions,
            "instruction_summary": _truncate_text(surface.manifest.instructions),
            "source_scope": surface.manifest.source_scope,
            "source_path": surface.manifest.source_path,
            "approval_state": surface.manifest.approval_state,
            "failure_reason": surface.manifest.failure_reason or surface.connection.failure_reason,
        }

    @staticmethod
    def _normalize_transport(value: object) -> MCPTransportKind:
        text = _clean_text(value).lower()
        if text in {"stdio", "http", "sse"}:
            return text  # type: ignore[return-value]
        if text in {"ws", "websocket"}:
            return "websocket"
        return "unknown"

    @staticmethod
    def _normalize_status(value: object) -> MCPConnectionStatus:
        text = _clean_text(value).lower()
        if text in {"connected", "disconnected", "connecting", "error"}:
            return text  # type: ignore[return-value]
        return "unknown"
