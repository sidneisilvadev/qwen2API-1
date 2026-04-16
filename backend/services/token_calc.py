import tiktoken
import logging

log = logging.getLogger("qwen2api.token")

try:
    # Default to cl100k_base as it's the most common GPT-4 level tokenizer
    encoder = tiktoken.get_encoding("cl100k_base")
except Exception as e:
    log.warning(f"Failed to load tiktoken: {e}")
    encoder = None

def count_tokens(text: str) -> int:
    """Calculate exact token count for text."""
    if not text:
        return 0
    if encoder:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    # Fallback：每汉字 1 token，每 3 个英文字母 1 token 的粗略估算
    return max(1, len(text.encode('utf-8')) // 2)

def calculate_usage(prompt: str, completion: str) -> dict:
    """Calculate usage for billing."""
    prompt_tokens = count_tokens(prompt)
    completion_tokens = count_tokens(completion)
    total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    }
