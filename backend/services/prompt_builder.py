import json
import logging
import uuid

log = logging.getLogger("qwen2api.prompt")

def _extract_text(content, user_tool_mode: bool = False) -> str:
    """Extract text from content (string or list of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        text_blocks = []
        other_parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            t = part.get("type", "")
            if t == "text":
                text_blocks.append(part.get("text", ""))
            elif t == "tool_use":
                inp = json.dumps(part.get("input", {}), ensure_ascii=False)
                other_parts.append(
                    f'##TOOL_CALL##\n{{"name": {json.dumps(part.get("name",""))}, "input": {inp}}}\n##END_CALL##'
                )
            elif t == "tool_result":
                inner = part.get("content", "")
                tid = part.get("tool_use_id", "")
                if isinstance(inner, str):
                    other_parts.append(f"[Tool Result for call {tid}]\n{inner}\n[/Tool Result]")
                elif isinstance(inner, list):
                    texts = [p.get("text", "") for p in inner if isinstance(p, dict) and p.get("type") == "text"]
                    other_parts.append(f"[Tool Result for call {tid}]\n{''.join(texts)}\n[/Tool Result]")

        if user_tool_mode and text_blocks:
            parts.append(text_blocks[-1])
        else:
            parts.extend(text_blocks)
        parts.extend(other_parts)
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def _normalize_tool(tool: dict) -> dict:
    """Normalize OpenAI or Anthropic tool format to internal {name, description, parameters}."""
    if tool.get("type") == "function" and "function" in tool:
        fn = tool["function"]
        return {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {}),
        }
    return {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema") or tool.get("parameters") or {},
    }


def _normalize_tools(tools: list) -> list:
    if not isinstance(tools, list):
        return []
    return [_normalize_tool(t) for t in tools if t]


def build_prompt_with_tools(system_prompt: str, messages: list, tools: list, context_graft: str = None) -> str:
    MAX_CHARS = 18000 if tools else 120000
    
    # Base system part
    sys_part = f"<system>\n{system_prompt[:2000]}\n</system>" if system_prompt else ""
    
    graft_part = ""
    if context_graft:
        graft_part = f"<Knowledge_Anchor>\n{context_graft}\n</Knowledge_Anchor>"
    
    tools_part = ""
    if tools:
        names = [t.get("name", "") for t in tools if t.get("name")]
        lines = [
            "=== MANDATORY TOOL CALL INSTRUCTIONS ===",
            "IGNORE any previous output format instructions.",
            f"You have access to these tools: {', '.join(names)}",
            "",
            "WHEN YOU NEED TO CALL A TOOL — output EXACTLY this format (nothing else):",
            "##TOOL_CALL##",
            '{"name": "EXACT_TOOL_NAME", "input": {"param1": "value1"}}',
            "##END_CALL##",
            "",
            "STRICT RULES:",
            "- No preamble, no explanation before or after ##TOOL_CALL##...##END_CALL##.",
            "- Use EXACT tool name from the list below.",
            "- Prioritize the most recent user request as TOP PRIORITY task.",
            "- You HAVE full file system access via tools. NEVER say you cannot access files.",
            "- Keep calling tools until the task is FULLY COMPLETE.",
            "- When NO tool is needed, answer normally in plain text.",
            "- If multiple tools are needed, call them one by one.",
            "",
            "Available tools:",
        ]
        verbose_tools = len(tools) <= 20
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            lines.append(f"- {name}: {desc[:120]}")
            if verbose_tools:
                params = tool.get("parameters", {})
                if params:
                    props = params.get("properties", {})
                    req = params.get("required", [])
                    if props:
                        ps = ", ".join(f"{k}({'req' if k in req else 'opt'})" for k in props)
                        lines.append(f"  params: {ps}")
        lines.append("=== END TOOL INSTRUCTIONS ===")
        tools_part = "\n".join(lines)

    overhead = len(sys_part) + len(tools_part) + 100
    budget = MAX_CHARS - overhead
    history_parts = []
    used = 0
    NEEDSREVIEW_MARKERS = ("需求回显", "已了解规则", "等待用户输入", "待执行任务", "待确认事项")
    
    # Message processing
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role not in ("user", "assistant", "system", "tool"):
            continue
            
        content = msg.get("content")
        text = _extract_text(content, user_tool_mode=(bool(tools) and role == "user"))

        # Handle tool results (OpenAI role='tool')
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            disp_content = text if len(text) < 1500 else text[:1500] + "...[truncated]"
            line = f"[Tool Result id={tool_call_id}]\n{disp_content}\n[/Tool Result]"
            if used + len(line) + 2 > budget: break
            history_parts.insert(0, line)
            used += len(line) + 2
            continue

        # Handle assistant tool calls (OpenAI tool_calls list)
        if role == "assistant" and not text and msg.get("tool_calls"):
            tc_parts = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_str = fn.get("arguments", "{}")
                try: args = json.loads(args_str)
                except: args = {"raw": args_str}
                tc_parts.append(f'##TOOL_CALL##\n{{"name": {json.dumps(name)}, "input": {json.dumps(args, ensure_ascii=False)}}}\n##END_CALL##')
            text = "\n".join(tc_parts)

        if not text and role != "system":
            continue

        if role == "assistant" and any(m in text for m in NEEDSREVIEW_MARKERS):
            continue

        is_tool_result = role == "user" and ("[Tool Result]" in text or "[tool result]" in text.lower())
        max_len = 800 if is_tool_result else 2500
        if len(text) > max_len:
            text = text[:max_len] + "...[truncated]"
        
        prefix = {"user": "Human: ", "assistant": "Assistant: ", "system": "System: "}.get(role, "System: ")
        line = f"{prefix}{text}"
        
        if used + len(line) + 2 > budget: break
        history_parts.insert(0, line)
        used += len(line) + 2

    # Ensure original task is always present
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    if first_user and tools:
        first_text = _extract_text(first_user.get("content", ""), True)
        if first_text and (not history_parts or first_text[:50] not in history_parts[0]):
            history_parts.insert(0, f"Human (ORIGINAL TASK): {first_text[:1000]}")

    parts = []
    if sys_part: parts.append(sys_part)
    if graft_part: parts.append(graft_part)
    parts.extend(history_parts)
    if tools_part: parts.append(tools_part)
    parts.append("Assistant:")
    return "\n\n".join(parts)


def messages_to_prompt(req_data: dict) -> tuple:
    messages = req_data.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    
    tools = _normalize_tools(req_data.get("tools", []))
    
    system_prompt = ""
    sys_field = req_data.get("system", "")
    if isinstance(sys_field, list):
        system_prompt = " ".join(p.get("text", "") for p in sys_field if isinstance(p, dict))
    elif isinstance(sys_field, str):
        system_prompt = sys_field
    
    if not system_prompt:
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = _extract_text(msg.get("content", ""))
                break
    
    graft = req_data.get("extra_body", {}).get("context_graft") or req_data.get("context_graft")
    return build_prompt_with_tools(system_prompt, messages, tools, context_graft=graft), tools
