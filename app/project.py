"""工程文件（JSON）：元件、端口、分析设置。"""
from __future__ import annotations

import json
from typing import Any, Dict

from .engine import Analysis, Network


SCHEMA_VERSION = 1


class Project:
    def __init__(self, name: str = "未命名工程", network: Network | None = None,
                 analysis: Analysis | None = None, path: str | None = None):
        self.name = name
        self.network = network or Network(50.0)
        self.analysis = analysis or Analysis()
        self.path = path
        self.freq_unit = "MHz"      # 输入框显示单位（MHz/kHz/Hz/GHz）
        self.smith = {}             # Smith 工具参数（可选，旧工程无此键）
        self.len_unit = "mm"        # 长度单位（mm/mil/inch）

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        return {"schema": SCHEMA_VERSION, "name": self.name,
                "freq_unit": self.freq_unit, "len_unit": self.len_unit,
                "analysis": self.analysis.to_dict(),
                "network": self.network.to_dict(),
                "smith": dict(self.smith or {})}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Project":
        p = Project(name=str(d.get("name", "未命名工程")))
        p.network = Network.from_dict(d.get("network", {}))
        p.analysis = Analysis.from_dict(d.get("analysis", {}))
        p.freq_unit = str(d.get("freq_unit", "MHz"))
        p.len_unit = str(d.get("len_unit", "mm"))
        p.smith = dict(d.get("smith") or {})
        return p

    def save(self, path: str | None = None) -> str:
        path = path or self.path
        if not path:
            raise ValueError("未指定保存路径")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        self.path = path
        return path

    @staticmethod
    def load(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = Project.from_dict(d)
        p.path = path
        return p


def new_demo_project() -> Project:
    """示例：3 阶切比雪夫低通（fc=3GHz, 0.5dB 纹波, Z0=50Ω），0.1–10GHz 线性扫。"""
    from .builders import ladder_to_network
    from .synthesis import lowpass_lc

    p = Project("示例 · 3 阶低通滤波器（3 GHz）")
    p.analysis = Analysis(0.1, 10.0, 401, "linear")   # 单位 GHz：0.1–10 GHz
    p.network = ladder_to_network(lowpass_lc(3, 3e9, 50.0, 0.5, "chebyshev"), 50.0)
    return p