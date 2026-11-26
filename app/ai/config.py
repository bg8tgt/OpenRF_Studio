"""AI 配置：自定义模型端点、密钥、采样参数。

默认读 %APPDATA%/OpenRF_Studio/ai.json（可用环境变量 OPENRF_AI_CONFIG 覆盖路径）。
也支持环境变量覆盖单项：
    OPENRF_AI_BASE_URL / OPENRF_AI_MODEL / OPENRF_AI_KEY / OPENRF_AI_TIMEOUT
    OPENRF_AI_DISABLE=1  → 强制只用本地规则引擎

安全说明：密钥以明文保存在本机用户配置目录，仅用于向用户自己配置的端点发请求；
界面只显示掩码；日志与提示词都不会包含密钥。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

APP_DIR_NAME = "OpenRF_Studio"


def default_config_path() -> str:
    override = os.environ.get("OPENRF_AI_CONFIG")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME, "ai.json")


# 本地私有默认值（不入库）；文件不存在时留空，由设置界面填写
try:
    from ._secrets import API_KEY as _DEFAULT_API_KEY
except Exception:  # noqa: BLE001
    _DEFAULT_API_KEY = ""


@dataclass
class AIConfig:
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    api_key: str = _DEFAULT_API_KEY
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: float = 60.0
    persona: str = "rf_engineer"
    extra: Dict[str, object] = field(default_factory=dict)

    # ---------- 状态 ----------
    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip() and self.model.strip()) and \
            os.environ.get("OPENRF_AI_DISABLE", "") not in ("1", "true", "True")

    def masked_key(self) -> str:
        return mask_key(self.api_key)

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AIConfig":
        return AIConfig(
            base_url=str(d.get("base_url", AIConfig.base_url)),
            model=str(d.get("model", "")),
            api_key=str(d.get("api_key", "")),
            temperature=float(d.get("temperature", 0.3)),
            max_tokens=int(d.get("max_tokens", 1200)),
            timeout=float(d.get("timeout", 60.0)),
            persona=str(d.get("persona", AIConfig.persona)),
            extra=dict(d.get("extra", {}) or {}),
        )


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return "（未设置）"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:3] + "…" + key[-4:]


def _apply_env(cfg: AIConfig) -> AIConfig:
    if os.environ.get("OPENRF_AI_BASE_URL"):
        cfg.base_url = os.environ["OPENRF_AI_BASE_URL"]
    if os.environ.get("OPENRF_AI_MODEL"):
        cfg.model = os.environ["OPENRF_AI_MODEL"]
    if os.environ.get("OPENRF_AI_KEY"):
        cfg.api_key = os.environ["OPENRF_AI_KEY"]
    if os.environ.get("OPENRF_AI_TIMEOUT"):
        try:
            cfg.timeout = float(os.environ["OPENRF_AI_TIMEOUT"])
        except ValueError:
            pass
    return cfg


def load_config(path: Optional[str] = None) -> AIConfig:
    path = path or default_config_path()
    cfg = AIConfig()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = AIConfig.from_dict(json.load(f))
    except Exception:
        cfg = AIConfig()
    return _apply_env(cfg)


def save_config(cfg: AIConfig, path: Optional[str] = None) -> str:
    path = path or default_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    return path
