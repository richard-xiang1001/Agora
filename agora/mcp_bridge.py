from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agora.mcp_adapter import build_mcp_prompt_action_name, build_mcp_tool_action_name


@runtime_checkable
class MCPReadOnlyBridge(Protocol):
    def call_readonly_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        workflow_id: str,
        action_id: str,
        action_name: str,
    ) -> Any: ...

    def read_resource(
        self,
        *,
        server_id: str,
        uri: str,
        workflow_id: str,
        action_id: str,
        action_name: str,
    ) -> Any: ...

    def get_prompt(
        self,
        *,
        server_id: str,
        prompt_name: str,
        arguments: dict[str, Any],
        workflow_id: str,
        action_id: str,
        action_name: str,
    ) -> Any: ...


def _mcp_tool_claims_mutation(tool: dict[str, Any]) -> bool:
    input_schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    text = " ".join(
        str(item or "").lower()
        for item in [
            tool.get("name"),
            tool.get("title"),
            tool.get("description"),
            tool.get("command"),
            tool.get("path"),
            input_schema.get("description"),
        ]
    )
    return any(token in text for token in ("write", "delete", "remove", "exec", "shell", "chmod", "touch", "patch", "mutat"))


def build_mcp_capability_inventory(mcp_servers: list[dict[str, Any]] | None) -> dict[str, Any]:
    by_tool_action: dict[str, dict[str, Any]] = {}
    by_prompt_action: dict[str, dict[str, Any]] = {}
    resources_by_server: dict[str, dict[str, Any]] = {}
    servers: list[dict[str, Any]] = []
    server_ids: set[str] = set()
    for item in list(mcp_servers or []):
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        surface = item.get("surface") if isinstance(item.get("surface"), dict) else {}
        manifest = surface.get("manifest") if isinstance(surface.get("manifest"), dict) else {}
        if not bool(summary.get("enabled")):
            continue
        server_id = str(summary.get("server_id") or manifest.get("server_id") or "").strip()
        if not server_id:
            continue
        server_ids.add(server_id)
        transport = str(summary.get("transport") or manifest.get("transport") or "").strip()
        instruction_summary = str(summary.get("instruction_summary") or "").strip()
        source_scope = str(summary.get("source_scope") or manifest.get("source_scope") or "").strip()
        source_path = str(summary.get("source_path") or manifest.get("source_path") or "").strip()
        approval_state = str(summary.get("approval_state") or manifest.get("approval_state") or "approved").strip() or "approved"
        server_meta = {
            "server_id": server_id,
            "transport": transport,
            "instruction_summary": instruction_summary,
            "source_scope": source_scope,
            "source_path": source_path,
            "approval_state": approval_state,
        }
        servers.append(
            {
                **server_meta,
                "tool_count": int(summary.get("tool_count") or len(list(surface.get("tools") or []))),
                "resource_count": int(summary.get("resource_count") or len(list(surface.get("resources") or []))),
                "prompt_count": int(summary.get("prompt_count") or len(list(surface.get("prompts") or []))),
                "command_count": int(summary.get("command_count") or len(list(surface.get("commands") or []))),
            }
        )
        resource_items: list[dict[str, Any]] = []
        resource_by_uri: dict[str, dict[str, Any]] = {}
        for tool in list(surface.get("tools") or []):
            if not isinstance(tool, dict):
                continue
            if not bool(tool.get("allowed", True)):
                continue
            if not bool(tool.get("read_only", True)) or bool(tool.get("destructive", False)) or _mcp_tool_claims_mutation(tool):
                continue
            tool_name = str(tool.get("name") or "").strip()
            action = build_mcp_tool_action_name(server_id, tool_name)
            if not action:
                continue
            by_tool_action[action] = {
                "action": action,
                "server_id": server_id,
                "tool_name": tool_name,
                "title": str(tool.get("title") or tool_name or action).strip() or action,
                "description": str(tool.get("description") or "").strip(),
                "transport": transport,
                "instruction_summary": instruction_summary,
                "source_scope": source_scope,
                "source_path": source_path,
                "approval_state": approval_state,
                "read_only": True,
            }
        command_entries = list(surface.get("commands") or [])
        if not command_entries:
            for prompt in list(surface.get("prompts") or []):
                if not isinstance(prompt, dict):
                    continue
                command_entries.append(
                    {
                        "name": str(prompt.get("name") or "").strip(),
                        "action_name": build_mcp_prompt_action_name(server_id, prompt.get("name")),
                        "title": str(prompt.get("title") or prompt.get("name") or "").strip(),
                        "description": str(prompt.get("description") or "").strip(),
                        "argument_names": list(prompt.get("argument_names") or []),
                        "allowed": bool(prompt.get("allowed", True)),
                    }
                )
        for command in command_entries:
            if not isinstance(command, dict):
                continue
            if not bool(command.get("allowed", True)):
                continue
            prompt_name = str(command.get("name") or "").strip()
            action = str(command.get("action_name") or build_mcp_prompt_action_name(server_id, prompt_name)).strip()
            if not prompt_name or not action:
                continue
            by_prompt_action[action] = {
                "action": action,
                "server_id": server_id,
                "prompt_name": prompt_name,
                "title": str(command.get("title") or prompt_name or action).strip() or action,
                "description": str(command.get("description") or "").strip(),
                "argument_names": [str(item).strip() for item in list(command.get("argument_names") or []) if str(item).strip()],
                "transport": transport,
                "instruction_summary": instruction_summary,
                "source_scope": source_scope,
                "source_path": source_path,
                "approval_state": approval_state,
                "read_only": True,
            }
        for resource in list(surface.get("resources") or []):
            if not isinstance(resource, dict):
                continue
            if not bool(resource.get("allowed", True)) or not bool(resource.get("read_only", True)):
                continue
            uri = str(resource.get("uri") or "").strip()
            name = str(resource.get("name") or "").strip()
            if not uri or not name:
                continue
            entry = {
                "server_id": server_id,
                "uri": uri,
                "name": name,
                "title": str(resource.get("title") or name or uri).strip() or uri,
                "description": str(resource.get("description") or "").strip(),
                "transport": transport,
                "instruction_summary": instruction_summary,
                "source_scope": source_scope,
                "source_path": source_path,
                "approval_state": approval_state,
                "read_only": True,
            }
            resource_items.append(entry)
            resource_by_uri[uri] = entry
        resources_by_server[server_id] = {
            "server_id": server_id,
            "count": len(resource_items),
            "items": resource_items,
            "by_uri": resource_by_uri,
        }
    tool_action_names = sorted(by_tool_action)
    prompt_action_names = sorted(by_prompt_action)
    return {
        "version": "mcp_inventory_v1",
        "server_ids": sorted(server_ids),
        "servers": sorted(servers, key=lambda item: str(item.get("server_id") or "")),
        "tool_count": len(tool_action_names),
        "resource_count": sum(int(item.get("count") or 0) for item in resources_by_server.values()),
        "prompt_count": len(prompt_action_names),
        "command_count": len(prompt_action_names),
        "tool_action_names": tool_action_names,
        "prompt_action_names": prompt_action_names,
        "action_names": sorted({*tool_action_names, *prompt_action_names}),
        "by_tool_action": {name: dict(by_tool_action[name]) for name in tool_action_names},
        "by_prompt_action": {name: dict(by_prompt_action[name]) for name in prompt_action_names},
        "resources_by_server": resources_by_server,
    }


def build_mcp_tool_allowlist(mcp_servers: list[dict[str, Any]] | None) -> dict[str, Any]:
    inventory = build_mcp_capability_inventory(mcp_servers)
    tool_action_names = list(inventory.get("tool_action_names") or [])
    by_tool_action = inventory.get("by_tool_action") if isinstance(inventory.get("by_tool_action"), dict) else {}
    return {
        "version": "mcp_allowlist_v1",
        "count": len(tool_action_names),
        "server_ids": list(inventory.get("server_ids") or []),
        "action_names": tool_action_names,
        "items": [dict(by_tool_action[name]) for name in tool_action_names if isinstance(by_tool_action.get(name), dict)],
        "by_action": {name: dict(by_tool_action[name]) for name in tool_action_names if isinstance(by_tool_action.get(name), dict)},
    }


def lookup_mcp_tool_allowlist_entry(
    allowlist: dict[str, Any] | None,
    *,
    action_name: str,
) -> dict[str, Any] | None:
    payload = dict(allowlist or {})
    by_action = payload.get("by_action") if isinstance(payload.get("by_action"), dict) else {}
    direct = by_action.get(str(action_name or "").strip())
    if isinstance(direct, dict):
        return dict(direct)
    for item in list(payload.get("items") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "").strip() == str(action_name or "").strip():
            return dict(item)
    return None


def lookup_mcp_prompt_inventory_entry(
    inventory: dict[str, Any] | None,
    *,
    action_name: str,
) -> dict[str, Any] | None:
    payload = dict(inventory or {})
    by_action = payload.get("by_prompt_action") if isinstance(payload.get("by_prompt_action"), dict) else {}
    direct = by_action.get(str(action_name or "").strip())
    return dict(direct) if isinstance(direct, dict) else None


def lookup_mcp_resource_inventory_entry(
    inventory: dict[str, Any] | None,
    *,
    server_id: str,
    uri: str,
) -> dict[str, Any] | None:
    payload = dict(inventory or {})
    resources_by_server = payload.get("resources_by_server") if isinstance(payload.get("resources_by_server"), dict) else {}
    server_payload = resources_by_server.get(str(server_id or "").strip())
    if not isinstance(server_payload, dict):
        return None
    by_uri = server_payload.get("by_uri") if isinstance(server_payload.get("by_uri"), dict) else {}
    entry = by_uri.get(str(uri or "").strip())
    return dict(entry) if isinstance(entry, dict) else None


def list_mcp_resources_from_inventory(
    inventory: dict[str, Any] | None,
    *,
    server_id: str | None = None,
) -> list[dict[str, Any]]:
    payload = dict(inventory or {})
    resources_by_server = payload.get("resources_by_server") if isinstance(payload.get("resources_by_server"), dict) else {}
    if server_id:
        server_payload = resources_by_server.get(str(server_id).strip())
        if not isinstance(server_payload, dict):
            return []
        return [dict(item) for item in list(server_payload.get("items") or []) if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    for item in resources_by_server.values():
        if not isinstance(item, dict):
            continue
        rows.extend(dict(row) for row in list(item.get("items") or []) if isinstance(row, dict))
    rows.sort(key=lambda row: (str(row.get("server_id") or ""), str(row.get("name") or ""), str(row.get("uri") or "")))
    return rows
