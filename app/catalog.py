"""元件目录 / 测量项目录 / 界面术语表。

本模块是本软件的"命名体系"单一来源：
  * ELEMENT_CATALOG：已实现元件（代号 → 中文名 / 参数 / 内部模型）
  * PLANNED_ELEMENTS：规划中的元件（只描述，不参与计算）
  * MEASUREMENTS：测量项（中文名 / 状态 / 实现入口）
  * GLOSSARY：界面术语中英对照

代号规则：R/L/C = 集总电阻/电感/电容；TL = 理想传输线；MS = 微带线；
CX = 同轴线；PORT/GND = 端口与地。
"""
from __future__ import annotations

from typing import Dict, List, Optional

ELEMENT_CATALOG: Dict[str, Dict] = {
    "R":    {"name": "电阻", "params": "R (Ω)", "status": "ready", "kind": "R",
             "note": "理想电阻"},
    "L":    {"name": "电感", "params": "L (nH)", "status": "ready", "kind": "L",
             "note": "理想电感"},
    "C":    {"name": "电容", "params": "C (pF)", "status": "ready", "kind": "C",
             "note": "理想电容"},
    "RLCS": {"name": "串联 RLC", "params": "R, L, C", "status": "ready",
             "kind": "RLCS", "note": "串联谐振，谐振点呈短路"},
    "RLCP": {"name": "并联 RLC", "params": "R, L, C", "status": "ready",
             "kind": "RLCP", "note": "并联谐振，谐振点呈高阻"},
    "TL":   {"name": "理想传输线", "params": "Z0, 长度, εeff", "status": "ready",
             "kind": "TL", "note": "按物理长度与有效介电常数计算电长度"},
    "MS":   {"name": "微带线", "params": "W, L, h, εr", "status": "ready", "kind": "MS",
             "note": "准静态模型 + 一阶色散"},
    "CX":   {"name": "同轴线", "params": "d, D, εr", "status": "ready", "kind": "COAX",
             "note": "TEM 精确解析式"},
    "PORT": {"name": "端口", "params": "序号, Z0", "status": "ready", "kind": "PORT",
             "note": "参考阻抗按端口设置"},
    "GND":  {"name": "地", "params": "—", "status": "ready", "kind": "GND",
             "note": "用节点 0 表示"},
}

# 内部 kind ↔ 显示代号
KIND_CODE = {"R": "R", "L": "L", "C": "C", "RLCS": "RLCS", "RLCP": "RLCP",
             "TL": "TL", "MS": "MS", "COAX": "CX", "PORT": "PORT"}
KIND_NAME = {v["kind"]: v["name"] for v in ELEMENT_CATALOG.values()}

PLANNED_ELEMENTS: List[Dict] = [
    {"name": "带 Q 电感 / 电容", "params": "L/C, Q", "note": "需要损耗与品质因数模型"},
    {"name": "耦合电感", "params": "L1, L2, k", "note": "需要互感矩阵"},
    {"name": "空心线圈", "params": "圈径 / 圈数 / 线径", "note": "需要线圈几何模型"},
    {"name": "变压器", "params": "匝比", "note": "未实现"},
    {"name": "微带 T 型结 / 阶跃 / 十字交叉", "params": "几何尺寸",
     "note": "需要微带不连续性模型"},
    {"name": "耦合线", "params": "线宽 / 间距 / 长度", "note": "需要四端口耦合线模型"},
    {"name": "环形器", "params": "—", "note": "未实现"},
    {"name": "巴伦", "params": "—", "note": "未实现"},
    {"name": "带阻滤波器", "params": "—", "note": "向导目前只做低通/带通"},
    {"name": "片式电容（含 ESL/ESR）", "params": "C, ESL, ESR", "note": "需要封装寄生模型"},
    {"name": "键合线", "params": "直径 / 弧高", "note": "未实现"},
    {"name": "二极管", "params": "模型", "note": "需要谐波平衡引擎"},
    {"name": "放大器", "params": "增益 / S 参数", "note": "可用 S2P 元件扩展"},
    {"name": "运算放大器", "params": "—", "note": "未实现"},
    {"name": "混频器", "params": "—", "note": "需要谐波平衡引擎"},
]

MEASUREMENTS: Dict[str, Dict] = {
    "S 参数":         {"code": "S", "status": "ok", "api": "SweepResult.s_ij / db"},
    "端口参数":       {"code": "Zin", "status": "partial", "api": "由 S 参数换算"},
    "线性增益":       {"code": "Gain", "status": "ok", "api": "20log10|S21|"},
    "回波损耗":       {"code": "RL", "status": "ok", "api": "-20log10|S11|"},
    "插入损耗":       {"code": "IL", "status": "ok", "api": "-20log10|S21|"},
    "驻波比":         {"code": "VSWR", "status": "ok", "api": "vswr()"},
    "稳定性":         {"code": "K", "status": "ok", "api": "Rollett K"},
    "群时延":         {"code": "GD", "status": "ok", "api": "group_delay_ns()"},
    "噪声系数":       {"code": "NF", "status": "missing", "note": "需要噪声模型"},
    "功率":           {"code": "P", "status": "missing", "note": "需要激励与谐波平衡"},
    "互调":           {"code": "IMD", "status": "missing", "note": "需要谐波平衡"},
    "增益压缩":       {"code": "P1dB", "status": "missing", "note": "需要谐波平衡"},
    "相位噪声":       {"code": "PN", "status": "missing", "note": "需要振荡器分析"},
    "负载牵引":       {"code": "LP", "status": "missing", "note": "需要谐波平衡 + 扫描框架"},
}


def code_for_kind(kind: str) -> str:
    return KIND_CODE.get(kind, kind)


def kind_for_code(code: str) -> Optional[str]:
    e = ELEMENT_CATALOG.get(code.strip().upper())
    return e.get("kind") if e else None


def ready_codes() -> List[str]:
    return [k for k, v in ELEMENT_CATALOG.items() if v["status"] == "ready"]


def measurement_status(name: str) -> str:
    return MEASUREMENTS.get(name, {}).get("status", "unknown")


GLOSSARY: List[Dict[str, str]] = [
    {"en": "Project Browser", "cn": "项目浏览器", "note": "左侧工程树"},
    {"en": "Element Catalog", "cn": "元件目录", "note": "可用元件清单"},
    {"en": "Schematic", "cn": "原理图", "note": "电路编辑区"},
    {"en": "Graph", "cn": "图表", "note": "结果曲线"},
    {"en": "Rectangular", "cn": "直角坐标图", "note": "幅度-频率"},
    {"en": "Smith Chart", "cn": "史密斯圆图", "note": "阻抗/导纳"},
    {"en": "Polar", "cn": "极坐标图", "note": "反射系数"},
    {"en": "Legend", "cn": "图例", "note": "曲线标识"},
    {"en": "Trace", "cn": "曲线", "note": "一条测量结果"},
    {"en": "X Axis", "cn": "横轴", "note": "频率轴"},
    {"en": "Left Axis", "cn": "纵轴", "note": "dB / VSWR 轴"},
    {"en": "Project Options", "cn": "工程选项", "note": "频率/单位设置"},
    {"en": "Sweep Type", "cn": "扫描类型", "note": "线性/对数"},
    {"en": "VSWR", "cn": "驻波比", "note": "由 |S11| 换算"},
    {"en": "Return Loss", "cn": "回波损耗", "note": "-20log|S11|"},
    {"en": "Insertion Loss", "cn": "插入损耗", "note": "-20log|S21|"},
    {"en": "Transmission Line Calculator", "cn": "传输线计算器",
     "note": "微带/带状线/同轴"},
    {"en": "Global Units", "cn": "全局单位", "note": "nH / pF / Ω / mm"},
    {"en": "Substrate", "cn": "基板", "note": "εr / 厚度"},
]