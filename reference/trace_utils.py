"""
追踪工具 - 用于记录和监控AI输出
"""
from __future__ import annotations
import os
import threading
from datetime import datetime

_trace_file_path: str | None = None
_lock = threading.Lock()


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sanitize_filename(name: str) -> str:
    bad = '<>:"/\\|?*\n\r\t'
    cleaned = ''.join(c if c not in bad else '_' for c in name)
    # 防止过长路径
    return cleaned.strip()[:80] or "chat"


def set_trace_file(file_path: str | None):
    global _trace_file_path
    _trace_file_path = file_path
    if file_path:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)


def start_conversation_log(company: str, topic: str) -> str:
    base_dir = os.path.join("data", "processed", "chat_logs")
    os.makedirs(base_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{sanitize_filename(company)}_{sanitize_filename(topic)}_{ts}.log"
    path = os.path.join(base_dir, fname)
    set_trace_file(path)
    trace(f"[log] 会话日志已开启 -> {path}")
    return path


def end_conversation_log():
    global _trace_file_path
    trace("[log] 会话日志结束。")
    _trace_file_path = None


def trace(message):
    """
    支持传入多种形式的 message：
    - 字符串 -> 直接使用
    - tuple/list -> 多种组合：
        (prefix, content, max_chars)
        (prefix, content)
        (content, max_chars)

    控制台输出会对内容做 summarize 截断，日志文件写入完整内容。
    """
    # 解析可能的 tuple 输入
    full_message = None
    console_message = None
    if isinstance(message, (list, tuple)):
        # 解包多种可能形式
        try:
            if len(message) == 3:
                prefix, content, max_chars = message
            elif len(message) == 2:
                a, b = message
                if isinstance(b, int):
                    prefix = ""
                    content = a
                    max_chars = b
                else:
                    prefix = a
                    content = b
                    max_chars = 400
            else:
                prefix = ""
                content = message[0]
                max_chars = 400
        except Exception:
            # 发生异常时退回到简单处理
            full_message = str(message)
            console_message = summarize(full_message)
        else:
            try:
                # 尝试把复杂对象序列化为可读字符串
                import json as _json

                content_str = (
                    content if isinstance(content, str) else _json.dumps(content, ensure_ascii=False, default=str)
                )
            except Exception:
                content_str = str(content)
            prefix_str = (str(prefix).rstrip() + " ") if prefix else ""
            full_message = f"{prefix_str}{content_str}"
            # 控制台显示截断版本
            console_content = summarize(content, max_chars=max_chars)
            console_message = f"{prefix_str}{console_content}"
    else:
        # 普通字符串或其他对象
        full_message = message if isinstance(message, str) else str(message)
        console_message = summarize(full_message)

    # 控制台输出（截断）
    print(f"[{_timestamp()}] {console_message}")
    # 写入文件（完整）
    if _trace_file_path:
        try:
            with _lock:
                with open(_trace_file_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{_timestamp()}] {full_message}\n")
        except Exception:
            # 安静失败，避免影响主流程
            pass


def summarize(value, max_chars: int = 400, max_items: int = 5) -> str:
    try:
        if value is None:
            return "<None>"
        if isinstance(value, str):
            s = value
            return s if len(s) <= max_chars else (s[:max_chars] + " ...")
        if isinstance(value, (list, tuple)):
            items = [summarize(v, max_chars=max_chars//max(1, max_items), max_items=2) for v in value[:max_items]]
            more = f", ... (+{len(value)-max_items})" if len(value) > max_items else ""
            return f"[{', '.join(items)}{more}]"
        if isinstance(value, dict):
            items = []
            for i, (k, v) in enumerate(value.items()):
                if i >= max_items:
                    items.append(f"... (+{len(value)-max_items})")
                    break
                items.append(f"{k}={summarize(v, max_chars=max_chars//max(1, max_items), max_items=2)}")
            return "{" + ", ".join(items) + "}"
        s = str(value)
        return s if len(s) <= max_chars else (s[:max_chars] + " ...")
    except Exception:
        return "<unprintable>"
