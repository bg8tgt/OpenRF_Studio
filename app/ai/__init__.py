"""AI 辅助设计：可自定义 OpenAI 兼容模型；未配置时使用本地规则引擎。"""
from .config import AIConfig, load_config, save_config, mask_key
from .client import AIClient, AIError
from .assistant import Assistant, build_context
from .actions import validate_actions, apply_actions

__all__ = ["AIConfig", "load_config", "save_config", "mask_key",
           "AIClient", "AIError", "Assistant", "build_context",
           "validate_actions", "apply_actions"]
