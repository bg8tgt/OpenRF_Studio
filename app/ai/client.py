"""OpenAI 兼容的 Chat Completions 客户端（仅标准库 urllib）。

适配任何遵循 /v1/chat/completions 协议的服务，例如：
    OpenAI、DeepSeek、通义千问（兼容模式）、Moonshot、智谱、
    本地 Ollama（/v1）、LM Studio（/v1）、vLLM、one-api 网关等。

只做一件事：把 messages 发出去，拿回 content 文本。
不做流式、不缓存；限流/服务端 5xx/超时/连接中断会退避重试，
用完重试次数后抛 AIError，消息里同时带服务端原因和下一步该做什么。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from .config import AIConfig

# ---------------------------------------------------------------- 故障策略
# 可重试的 HTTP 状态码：限流 / 冲突 / 超时 / 服务端临时故障
RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
MAX_RETRIES = 2          # 首次 + 2 次重试 = 最多 3 次请求
BACKOFF_BASE = 0.4       # 退避 0.4s、0.8s


class AIError(RuntimeError):
    """AI 调用失败（网络、鉴权、协议、超时）。"""


def status_hint(code) -> str:
    """把 HTTP 状态码翻译成「用户下一步该做什么」。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "请核对 base_url / model / 网络"
    if code in (401, 403):
        return "密钥无效或未填，请到「设置」重新填写 API Key"
    if code == 404:
        return ("接口地址不对，base_url 通常要以 /v1 结尾"
                "（如 https://api.openai.com/v1）")
    if code == 402:
        return "账户余额不足"
    if code == 429:
        return "触发限流或额度用尽，稍后重试"
    if code == 400:
        return "请求格式或模型名不对，检查 model 字段"
    if code >= 500 or code == 408:
        return "服务端临时故障，可重试"
    return "请核对 base_url / model / 网络"


class AIClient:
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg

    # ---------- URL ----------
    def _url(self, path: str) -> str:
        base = (self.cfg.base_url or "").strip().rstrip("/")
        if not base:
            raise AIError("未配置 base_url\n→ 请到「设置」填写接口地址")
        return f"{base}/{path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json",
             "Accept": "application/json"}
        if self.cfg.api_key.strip():
            h["Authorization"] = f"Bearer {self.cfg.api_key.strip()}"
        for k, v in (self.cfg.extra or {}).items():
            if k.lower().startswith("header:"):
                h[k.split(":", 1)[1].strip()] = str(v)
        return h

    # ---------- 单次请求（HTTPError 不抛，返回状态码 + body） ----------
    def _raw(self, method: str, path: str, data: Optional[bytes]):
        req = urllib.request.Request(self._url(path), data=data,
                                     headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            return e.code, body

    def _timeout_error(self) -> AIError:
        return AIError(
            f"连接超时：服务器 {self.cfg.timeout:g}s 内没有响应\n"
            "→ 检查 base_url 是否可达；本地模型可把 timeout 调大后重试")

    # ---------- 带重试的调用 ----------
    def _call(self, method: str, path: str,
              payload: Optional[dict] = None) -> dict:
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_err: Optional[AIError] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                status, text = self._raw(method, path, data)
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    last_err = self._timeout_error()
                else:
                    last_err = AIError(
                        f"连接失败：{reason}\n"
                        "→ 检查 base_url 是否正确、网络/代理是否可达")
            except (socket.timeout, TimeoutError):
                last_err = self._timeout_error()
            else:
                if status < 400:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        raise AIError(
                            f"返回不是合法 JSON：{text[:200]}\n"
                            "→ 确认 base_url 指向 OpenAI 兼容接口，且以 /v1 结尾"
                        ) from e
                msg = _extract_error(text) or f"HTTP {status}"
                err = AIError(f"HTTP {status}：{msg}\n→ {status_hint(status)}")
                if status not in RETRY_STATUS:
                    raise err
                last_err = err
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * (2 ** attempt))
        if last_err is None:  # pragma: no cover - 逻辑上不可达
            last_err = AIError("请求失败\n→ 请核对 base_url / model / 网络")
        raise last_err

    def _post(self, path: str, payload: dict) -> dict:
        return self._call("POST", path, payload)

    def _get(self, path: str) -> dict:
        return self._call("GET", path)

    # ---------- 能力 ----------
    def chat(self, messages: List[Dict[str, str]],
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        if not self.cfg.model.strip():
            raise AIError("未配置模型名（model）\n→ 请到「设置」填写 model，或点「获取模型列表」")
        payload = {
            "model": self.cfg.model.strip(),
            "messages": messages,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "max_tokens": self.cfg.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        body = self._post("chat/completions", payload)
        try:
            return self._finish(body, payload)
        except (KeyError, IndexError, TypeError) as e:
            raise AIError(
                f"返回结构异常：{str(body)[:200]}\n"
                "→ 该端点可能不支持 /v1/chat/completions 协议"
            ) from e

    def _finish(self, body: dict, payload: dict) -> str:
        """取正文；推理型模型预算被思考吃光时，放大预算重来一次。"""
        text, reason, finish = self._split_message(body)
        if text.strip() or finish != "length":
            return text
        try:
            cur = int(payload.get("max_tokens") or 0)
        except (TypeError, ValueError):
            cur = 0
        bigger = min(max(cur * 3, 3000), 8192)
        if bigger > cur:
            retry = dict(payload)
            retry["max_tokens"] = bigger
            text, reason, finish = self._split_message(
                self._post("chat/completions", retry))
            if text.strip():
                return text
        if reason.strip():
            raise AIError(
                "模型把回复额度全花在「思考」上，没有输出正文"
                "（finish_reason=%s，思考 %d 字）。\n"
                "→ 到「设置」把「最大回复长度」调到 8192，或换非推理模型"
                % (finish or "?", len(reason)))
        raise AIError(
            "模型返回了空内容（finish_reason=%s）。\n"
            "→ 确认 model 是对话模型后重试" % (finish or "?"))

    @staticmethod
    def _split_message(body: dict):
        """返回 (正文, 思考内容, finish_reason)，兼容 reasoning_content。"""
        try:
            choice = body["choices"][0]
            msg = choice.get("message") or {}
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise AIError(
                "返回结构异常：%s\n→ 该端点可能不支持 /v1/chat/completions 协议"
                % str(body)[:200]) from e
        content = msg.get("content") or ""
        reason = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return str(content), str(reason), str(choice.get("finish_reason") or "")
    def list_models(self) -> List[str]:
        body = self._get("models")
        out = []
        for item in body.get("data", []) or []:
            if isinstance(item, dict) and item.get("id"):
                out.append(str(item["id"]))
        return sorted(out)

    def test(self) -> str:
        """连通性测试：优先列模型，失败再试最小对话。返回人类可读结果。"""
        try:
            models = self.list_models()
            if models:
                return f"连接成功，可用模型 {len(models)} 个（例如 {models[0]}）"
        except AIError:
            pass
        text = self.chat([{"role": "user", "content": "回复 OK 两个字母即可"}],
                         temperature=0.0, max_tokens=8)
        return f"连接成功，模型回复：{text.strip()[:40]}"


def _extract_error(body: str) -> str:
    try:
        d = json.loads(body)
        err = d.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:300]
        if isinstance(err, str):
            return err[:300]
        return str(d)[:300]
    except Exception:  # noqa: BLE001
        return body.strip()[:300]
