from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
import asyncio as aio
import json
import logging
import uuid
import time
import re
import hashlib
from typing import Optional, List, Dict, Any

from backend.core.account_pool import Account
from backend.services.qwen_client import QwenClient
from backend.services.prompt_builder import messages_to_prompt
from backend.services.tool_parser import parse_tool_calls, inject_format_reminder, build_tool_blocks_from_native_chunks, should_block_tool_call
from backend.core.config import resolve_model, settings, IMAGE_MODEL_DEFAULT, MODEL_MAP

log = logging.getLogger("qwen2api.chat")
router = APIRouter()

# --- Helper Functions ---

def _detect_media_intent(messages: list) -> str:
    """Return 't2i', 't2v', or 't2t' based on last user message."""
    _T2I_PATTERN = re.compile(r'(生成图片|画(一|个|张)?图|draw|generate\s+image|create\s+image|make\s+image|图片生成|文生图|生成一张|画一张)', re.IGNORECASE)
    _T2V_PATTERN = re.compile(r'(生成视频|make\s+video|generate\s+video|create\s+video|视频生成|文生视频)', re.IGNORECASE)
    
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            else:
                text = str(content)
            if _T2V_PATTERN.search(text): return "t2v"
            if _T2I_PATTERN.search(text): return "t2i"
            break
    return "t2t"

def _extract_last_user_text(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            return str(content)
    return ""

def _extract_image_urls(text: str) -> list[str]:
    urls: list[str] = []
    for u in re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', text):
        urls.append(u.rstrip(").,;"))
    if not urls:
        for u in re.findall(r'"(?:url|image|src|imageUrl|image_url)"\s*:\s*"(https?://[^"]+)"', text):
            urls.append(u)
    if not urls:
        cdn_pattern = r'https?://(?:wanx\.alicdn\.com|img\.alicdn\.com|[^\s"<>]+\.(?:jpg|jpeg|png|webp|gif))[^\s"<>]*'
        for u in re.findall(cdn_pattern, text, re.IGNORECASE):
            urls.append(u.rstrip(".,;)\"'>"))
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u); result.append(u)
    return result

def _hash_history(messages: list) -> str:
    """Create a unique hash for a conversation history to enable sticky sessions."""
    try:
        relevant = []
        for m in messages:
            relevant.append({"r": m.get("role"), "c": m.get("content")})
        return hashlib.md5(json.dumps(relevant).encode()).hexdigest()
    except:
        return hashlib.md5(str(time.time()).encode()).hexdigest()

def _extract_blocked_tool_names(text: str) -> list[str]:
    if not text: return []
    return re.findall(r"Tool\s+([A-Za-z0-9_.:-]+)\s+does not exists?\.?", text)

# --- Routes ---

@router.get("/v1/models")
@router.get("/models")
async def list_models(request: Request):
    app = request.app
    pool = app.state.account_pool
    models_data = []
    seen = set()
    
    qwen_discovered = getattr(pool, "discovered_models", [])
    if not qwen_discovered:
        qwen_discovered = [{"id": "qwen-max"}, {"id": "qwen-plus"}, {"id": "qwen-turbo"}]

    for m in qwen_discovered:
        m_id = m.get("id", str(m)) if isinstance(m, dict) else str(m)
        if m_id not in seen:
            seen.add(m_id)
            models_data.append({"id": m_id, "object": "model", "created": int(time.time()), "owned_by": "qwen"})

    for alias in MODEL_MAP.keys():
        if alias not in seen:
            seen.add(alias)
            models_data.append({"id": alias, "object": "model", "created": int(time.time()), "owned_by": "gateway-alias"})
            
    return {"object": "list", "data": models_data}

@router.post("/completions")
@router.post("/chat/completions")
@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    app = request.app
    db = app.state.db
    pool = app.state.account_pool
    qwen_client = app.state.qwen_client

    # Auth
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.headers.get("x-api-key", "").strip() or request.query_params.get("key", "").strip()

    user = None
    if token == settings.ADMIN_KEY:
        user = {"id": token, "name": "Master Admin", "quota": 999999999, "used_tokens": 0}
    else:
        is_admin = await db.fetch_one("SELECT key, name FROM admin_keys WHERE key = ?", (token,))
        if is_admin:
            user = {"id": token, "name": is_admin["name"], "quota": 999999999, "used_tokens": 0}
        else:
            is_valid_key = await db.fetch_one("SELECT key FROM api_keys WHERE key = ?", (token,))
            if not is_valid_key: raise HTTPException(status_code=401, detail="Invalid API Key")
            u_prof = await db.fetch_one("SELECT * FROM users WHERE id = ?", (token,))
            user = dict(u_prof) if u_prof else {"id": token, "name": "Basic User", "quota": 999999999, "used_tokens": 0}

    if user and user.get("quota", 0) <= user.get("used_tokens", 0):
        raise HTTPException(status_code=402, detail="Quota Exceeded")

    try:
        req_data = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON body")
        
    messages = req_data.get("messages", [])
    if not isinstance(messages, list): raise HTTPException(400, "messages must be a list")

    model_name = req_data.get("model", "gpt-3.5-turbo")
    resolved_model = resolve_model(model_name, pool.discovered_models)
    stream = req_data.get("stream", False)
    extra = req_data.get("extra_body", {})
    enable_thinking = req_data.get("enable_thinking", extra.get("enable_thinking", None))
    enable_search = req_data.get("enable_search", extra.get("enable_search", None))

    prompt, tools = messages_to_prompt(req_data)
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    async def update_usage_sql(ans_len: int, prompt_len: int):
        if user and token != settings.ADMIN_KEY:
            inc = ans_len + prompt_len
            await db.execute("UPDATE users SET used_tokens = used_tokens + ? WHERE id = ?", (inc, token))
            await db.commit()

    convo_id = _hash_history(messages)
    sticky_data = await db.fetch_one("SELECT account_email, qwen_chat_id FROM conversations WHERE id = ?", (convo_id,))
    preferred_acc = sticky_data["account_email"] if sticky_data else None

    # Media Routing
    if _detect_media_intent(messages) == "t2i":
        image_prompt = _extract_last_user_text(messages)
        if stream:
            async def generate_image_stream():
                def mk_c(delta, finish=None): return json.dumps({
                    "id": completion_id, "object": "chat.completion.chunk", "created": created, 
                    "model": model_name, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
                }, ensure_ascii=False)
                try:
                    answer_text, acc, chat_id = await qwen_client.image_generate_with_retry(IMAGE_MODEL_DEFAULT, image_prompt, preferred_email=preferred_acc)
                    pool.release(acc)
                    aio.create_task(qwen_client.delete_chat(acc.token, chat_id))
                    urls = _extract_image_urls(answer_text)
                    content = "\n".join(f"![generated]({u})" for u in urls) if urls else answer_text
                    yield f"data: {mk_c({'role': 'assistant'})}\n\n"
                    yield f"data: {mk_c({'content': content})}\n\n"
                    yield f"data: {mk_c({}, 'stop')}\n\n"
                    yield "data: [DONE]\n\n"
                    await update_usage_sql(len(content), len(image_prompt))
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return StreamingResponse(generate_image_stream(), media_type="text/event-stream")
        else:
            try:
                answer_text, acc, chat_id = await qwen_client.image_generate_with_retry(IMAGE_MODEL_DEFAULT, image_prompt, preferred_email=preferred_acc)
                pool.release(acc)
                aio.create_task(qwen_client.delete_chat(acc.token, chat_id))
                urls = _extract_image_urls(answer_text)
                content = "\n".join(f"![generated]({u})" for u in urls) if urls else answer_text
                return JSONResponse({
                    "id": completion_id, "object": "chat.completion", "created": created, "model": model_name,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": len(image_prompt), "completion_tokens": len(content), "total_tokens": len(image_prompt) + len(content)}
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    if stream:
        async def generate():
            current_prompt = prompt
            excluded_accounts = set()
            max_attempts = settings.TOOL_MAX_RETRIES if tools else settings.MAX_RETRIES
            prompt_tokens = len(prompt) // 2

            for stream_attempt in range(max_attempts):
                acc, chat_id = None, None
                try:
                    ans_text, reasoning_text = "", ""
                    native_tc = {}

                    def mk_chunk(delta, finish=None, usage=None):
                        obj = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model_name, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                        if usage: obj["usage"] = usage
                        return json.dumps(obj, ensure_ascii=False)

                    async for item in qwen_client.chat_stream_events_with_retry(resolved_model, current_prompt, has_custom_tools=bool(tools), exclude_accounts=excluded_accounts, thinking=enable_thinking, search=enable_search, preferred_email=preferred_acc):
                        if item["type"] == "keepalive":
                            yield ": keepalive\n\n"; continue
                        if item["type"] == "meta":
                            chat_id, acc = item["chat_id"], item["acc"]
                            yield f"data: {mk_chunk({'role': 'assistant'})}\n\n"; continue
                        if item["type"] == "event":
                            evt = item["event"]
                            if evt.get("type") != "delta": continue
                            phase, content = evt.get("phase", ""), evt.get("content", "")
                            if phase in ("think", "thinking_summary") and content:
                                reasoning_text += content; yield f"data: {mk_chunk({'reasoning_content': content})}\n\n"
                            elif phase == "answer" and content:
                                ans_text += content
                                if not tools: yield f"data: {mk_chunk({'content': content})}\n\n"
                            elif phase == "tool_call" and content:
                                tc_id = evt.get("extra", {}).get("tool_call_id", "tc_0")
                                if tc_id not in native_tc: native_tc[tc_id] = {"name": "", "args": ""}
                                try:
                                    c_obj = json.loads(content)
                                    if "name" in c_obj: native_tc[tc_id]["name"] = c_obj["name"]
                                    if "arguments" in c_obj: native_tc[tc_id]["args"] += c_obj["arguments"]
                                except: native_tc[tc_id]["args"] += content
                            if evt.get("status") == "finished" and phase == "answer": break

                    tool_blocks, stop = ([], "end_turn")
                    if tools:
                        if native_tc and not ans_text: tool_blocks, stop = build_tool_blocks_from_native_chunks(native_tc, tools)
                        else: tool_blocks, stop = parse_tool_calls(ans_text, tools)

                    if stop == "tool_use":
                        tc_list = [b for b in tool_blocks if b["type"] == "tool_use"]
                        for idx, tc in enumerate(tc_list):
                            yield f"data: {mk_chunk({'tool_calls': [{'index': idx, 'id': tc['id'], 'type': 'function', 'function': {'name': tc['name'], 'arguments': ''}}]})}\n\n"
                            yield f"data: {mk_chunk({'tool_calls': [{'index': idx, 'function': {'arguments': json.dumps(tc.get('input', {}), ensure_ascii=False)}}]})}\n\n"
                        yield f"data: {mk_chunk({}, 'tool_calls')}\n\n"
                    else:
                        if tools and ans_text: yield f"data: {mk_chunk({'content': ans_text})}\n\n"
                        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": len(ans_text)//2, "total_tokens": (prompt_tokens + len(ans_text)//2)}
                        yield f"data: {mk_chunk({}, 'stop', usage=usage)}\n\n"

                    yield "data: [DONE]\n\n"
                    await update_usage_sql(len(ans_text), len(prompt))
                    if acc and chat_id:
                        await db.execute("INSERT OR REPLACE INTO conversations (id, account_email, qwen_chat_id, last_used) VALUES (?, ?, ?, ?)", (convo_id, acc.email, chat_id, time.time()))
                        await db.commit(); pool.release(acc)
                    return
                except Exception as e:
                    if acc: pool.release(acc)
                    log.error(f"[Chat] Stream error: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"; return
        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        try:
            full_ans, full_reasoning, native_tc = "", "", {}
            async for item in qwen_client.chat_stream_events_with_retry(resolved_model, prompt, has_custom_tools=bool(tools), thinking=enable_thinking, search=enable_search, preferred_email=preferred_acc):
                if item["type"] == "meta": acc, chat_id = item["acc"], item["chat_id"]
                elif item["type"] == "event":
                    evt = item["event"]
                    phase, content = evt.get("phase", ""), evt.get("content", "")
                    if phase in ("think", "thinking_summary"): full_reasoning += content
                    elif phase == "answer": full_ans += content
                    elif phase == "tool_call":
                        tc_id = evt.get("extra", {}).get("tool_call_id", "tc_0")
                        if tc_id not in native_tc: native_tc[tc_id] = {"name": "", "args": ""}
                        try:
                            c_obj = json.loads(content)
                            if "name" in c_obj: native_tc[tc_id]["name"] = c_obj["name"]
                            if "arguments" in c_obj: native_tc[tc_id]["args"] += c_obj["arguments"]
                        except: native_tc[tc_id]["args"] += content
            tool_blocks, stop = ([], "end_turn")
            if tools:
                if native_tc and not full_ans: tool_blocks, stop = build_tool_blocks_from_native_chunks(native_tc, tools)
                else: tool_blocks, stop = parse_tool_calls(full_ans, tools)
            message = {"role": "assistant", "content": full_ans or None}
            if full_reasoning: message["reasoning_content"] = full_reasoning
            if stop == "tool_use":
                message["tool_calls"] = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}} for b in tool_blocks if b["type"] == "tool_use"]
            await update_usage_sql(len(full_ans), len(prompt))
            if acc and chat_id:
                await db.execute("INSERT OR REPLACE INTO conversations (id, account_email, qwen_chat_id, last_used) VALUES (?, ?, ?, ?)", (convo_id, acc.email, chat_id, time.time()))
                await db.commit(); pool.release(acc)
            return JSONResponse({
                "id": completion_id, "object": "chat.completion", "created": created, "model": model_name,
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if stop == "tool_use" else "stop"}],
                "usage": {"prompt_tokens": len(prompt)//2, "completion_tokens": len(full_ans)//2, "total_tokens": (len(prompt)+len(full_ans))//2}
            })
        except Exception as e:
            log.error(f"[Chat] Error: {e}"); raise HTTPException(500, detail=str(e))
