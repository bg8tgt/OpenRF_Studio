"""AI 动作协议：模型返回的结构化修改指令，校验后应用到工程。

协议（JSON）：
    {"reply": "给用户看的说明",
     "actions": [ {...}, ... ]}

支持的 action：
    {"op":"set_z0","value":50}
    {"op":"set_analysis","start_ghz":1,"stop_ghz":4,"points":401,"sweep":"linear"}
    {"op":"clear"}
    {"op":"add","id":"L1","kind":"L","nodes":["n1","m0"],"params":{"l":4.2}}
    {"op":"update","id":"L1","params":{"l":4.5}}
    {"op":"delete","id":"L1"}
    {"op":"build_filter","topo":"lowpass|bandpass","order":3,"fc_ghz":3,
     "f1_ghz":2.3,"f2_ghz":2.7,"z0":50,"ripple_db":0.5,"kind":"chebyshev|butterworth"}
    {"op":"run"}          （由界面执行：跑一次仿真）

校验原则：只接受白名单 op / kind / 参数键；数值必须有限且为正（长度可 ≥0）；
元件总数上限 200；未知字段忽略并在报告里提示。
"""
from __future__ import annotations

import math
from typing import List, Tuple

from ..components import Component
from ..engine import Network
from ..project import Project
from ..synthesis import bandpass_lc, bandstop_lc, highpass_lc, lowpass_lc

ALLOWED_OPS = {"set_z0", "set_analysis", "clear", "add", "update",
               "delete", "build_filter", "run",
               # v1.4：让 AI 能调用软件的全部功能
               "calc", "switch_tab", "open_tool", "save_project",
               "export_touchstone", "report", "build_balun"}
CALC_WHAT = {"microstrip", "stripline", "coax", "lc", "retune", "l_match", "s11"}
TABS = {"plot", "smith", "smith_tool", "schematic", "table", "log", "ai"}
TOOLS = {"filter_wizard", "tline", "inverse", "smith_tool", "about", "help"}
KINDS = {"R", "L", "C", "TL", "MS", "COAX"}
PARAM_KEYS = {
    "R": {"r"},
    "L": {"l"},
    "C": {"c"},
    "TL": {"z0", "er", "len", "loss"},
    "MS": {"w", "h", "er", "len", "loss"},
    "COAX": {"d_in", "d_out", "er", "len", "loss"},
}
MAX_COMPONENTS = 200


def _num(v, name: str, errors: List[str], positive: bool = True) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        errors.append(f"{name} 不是数字：{v!r}")
        return 0.0
    if not math.isfinite(x):
        errors.append(f"{name} 不是有限数：{v!r}")
        return 0.0
    if positive and x <= 0:
        errors.append(f"{name} 必须 > 0：{x:g}")
    return x


def validate_actions(raw) -> Tuple[List[dict], List[str]]:
    """校验并规范化动作列表；返回 (可用动作, 错误列表)。"""
    errors: List[str] = []
    if raw is None:
        return [], ["actions 为空"]
    if not isinstance(raw, list):
        return [], ["actions 必须是数组"]
    if len(raw) > 40:
        return [], ["actions 太多（>40）"]
    out: List[dict] = []
    for i, a in enumerate(raw):
        before_err = len(errors)
        if not isinstance(a, dict):
            errors.append(f"第 {i+1} 个动作不是对象")
            continue
        op = str(a.get("op", "")).strip()
        if op not in ALLOWED_OPS:
            errors.append(f"第 {i+1} 个动作 op 不支持：{op}")
            continue
        d = {"op": op}
        if op == "set_z0":
            d["value"] = _num(a.get("value"), "set_z0.value", errors)
        elif op == "set_analysis":
            for k in ("start_ghz", "stop_ghz"):
                if k in a:
                    d[k] = _num(a[k], f"set_analysis.{k}", errors)
            if "points" in a:
                try:
                    d["points"] = max(2, min(100000, int(float(a["points"]))))
                except (TypeError, ValueError):
                    errors.append(f"set_analysis.points 非法：{a.get('points')!r}")
            if "sweep" in a:
                sw = str(a["sweep"]).lower()
                if sw in ("linear", "log"):
                    d["sweep"] = sw
                else:
                    errors.append(f"sweep 只能是 linear/log：{a['sweep']}")
            if "single" in a:
                d["single"] = bool(a["single"])
        elif op == "add":
            kind = str(a.get("kind", "")).upper()
            if kind not in KINDS:
                errors.append(f"add.kind 不支持：{kind}")
                continue
            nodes = a.get("nodes")
            if not isinstance(nodes, list) or len(nodes) != 2:
                errors.append("add.nodes 必须是两个节点的数组")
                continue
            params = a.get("params") or {}
            if not isinstance(params, dict):
                errors.append("add.params 必须是对象")
                continue
            clean = {}
            for k, v in params.items():
                if k not in PARAM_KEYS[kind]:
                    errors.append(f"{kind} 不支持参数 {k}（已忽略）")
                    continue
                clean[k] = _num(v, f"add.params.{k}", errors,
                                positive=(k != "loss"))
            d.update({"kind": kind, "nodes": [str(x) for x in nodes],
                      "params": clean})
            if a.get("id"):
                cid = str(a["id"]).strip()[:32]
                if cid:
                    d["id"] = cid
        elif op == "update":
            if not a.get("id"):
                errors.append("update 缺少 id")
                continue
            params = a.get("params") or {}
            if not isinstance(params, dict):
                errors.append("update.params 必须是对象")
                continue
            d["id"] = str(a["id"]).strip()[:32]
            d["params"] = {k: _num(v, f"update.{k}", errors,
                                   positive=(k != "loss"))
                           for k, v in params.items()}
        elif op == "delete":
            if not a.get("id"):
                errors.append("delete 缺少 id")
                continue
            d["id"] = str(a["id"]).strip()[:32]
        elif op == "build_balun":
            d["f_ghz"] = _num(a.get("f_ghz", 2.4), "build_balun.f_ghz", errors)
            d["z0"] = _num(a.get("z0", 50), "build_balun.z0", errors)
        elif op == "calc":
            what = str(a.get("what", "")).lower()
            if what not in CALC_WHAT:
                errors.append(f"calc.what 不支持：{what}")
                continue
            d["what"] = what
            for k in ("z0", "h", "er", "f_ghz", "b", "t", "d_in", "l_nh", "c_pf",
                      "target_ghz", "rs", "rl", "mag", "phase_deg", "len"):
                if k in a:
                    d[k] = _num(a[k], f"calc.{k}", errors, positive=(k != "t"))
            if "keep" in a:
                d["keep"] = "C" if str(a["keep"]).upper() == "C" else "L"
        elif op == "switch_tab":
            tab = str(a.get("tab", "")).lower()
            if tab not in TABS:
                errors.append(f"switch_tab.tab 不支持：{tab}")
                continue
            d["tab"] = tab
        elif op == "open_tool":
            name = str(a.get("name", "")).lower()
            if name not in TOOLS:
                errors.append(f"open_tool.name 不支持：{name}")
                continue
            d["name"] = name
        elif op == "save_project":
            if a.get("path"):
                d["path"] = str(a["path"])[:260]
        elif op == "export_touchstone":
            if a.get("path"):
                d["path"] = str(a["path"])[:260]
        elif op == "build_filter":
            topo = str(a.get("topo", "lowpass")).lower()
            if topo not in ("lowpass", "highpass", "bandpass", "bandstop"):
                errors.append(
                    f"build_filter.topo 只能是 lowpass/highpass/bandpass/bandstop：{topo}")
                continue
            d["topo"] = topo
            d["order"] = max(1, min(12, int(float(a.get("order", 3))) if
                                    str(a.get("order", 3)).replace(".", "", 1).isdigit() else 3))
            d["z0"] = _num(a.get("z0", 50), "build_filter.z0", errors)
            d["ripple_db"] = _num(a.get("ripple_db", 0.5),
                                  "build_filter.ripple_db", errors, positive=False)
            fk = str(a.get("kind", "chebyshev")).lower()
            d["kind"] = fk if fk in ("chebyshev", "butterworth") else "chebyshev"
            if topo in ("lowpass", "highpass"):
                d["fc_ghz"] = _num(a.get("fc_ghz", 3.0), "build_filter.fc_ghz", errors)
            else:
                d["f1_ghz"] = _num(a.get("f1_ghz", 2.3), "build_filter.f1_ghz", errors)
                d["f2_ghz"] = _num(a.get("f2_ghz", 2.7), "build_filter.f2_ghz", errors)
                if d.get("f1_ghz", 0) >= d.get("f2_ghz", 1):
                    errors.append("build_filter 需要 f1 < f2")
        # 该动作有错就整条丢弃，避免把非法参数写进电路
        if len(errors) > before_err:
            continue
        out.append(d)
    return out, errors


def apply_actions(project: Project, actions: List[dict]) -> List[str]:
    """把动作应用到工程；返回人类可读的执行报告。"""
    from ..builders import ladder_to_network

    report: List[str] = []
    net: Network = project.network
    for a in actions:
        op = a["op"]
        if op == "set_z0":
            net.z0 = float(a["value"])
            report.append(f"参考阻抗 Z0 → {net.z0:g} Ω")
        elif op == "set_analysis":
            ana = project.analysis
            if "start_ghz" in a:
                ana.start_ghz = a["start_ghz"]
            if "stop_ghz" in a:
                ana.stop_ghz = a["stop_ghz"]
            if "points" in a:
                ana.points = a["points"]
            if "sweep" in a:
                ana.sweep = a["sweep"]
            if "single" in a:
                ana.single = a["single"]
            report.append(f"分析设置 → {ana.start_ghz:g}–{ana.stop_ghz:g} GHz，"
                          f"{ana.points} 点，{ana.sweep}")
        elif op == "clear":
            net.components.clear()
            report.append("已清空所有元件")
        elif op == "add":
            n = len(net.components)
            if n >= MAX_COMPONENTS:
                report.append(f"元件已达上限 {MAX_COMPONENTS}，跳过新增")
                continue
            kind = a["kind"]
            cid = a.get("id") or net.next_id(kind)
            if net.get(cid):
                cid = net.next_id(kind)
            net.components.append(Component(cid, kind, a["nodes"], a["params"]))
            report.append(f"新增 {cid}（{kind}，{'–'.join(a['nodes'])}）")
        elif op == "update":
            c = net.get(a["id"])
            if not c:
                report.append(f"未找到 {a['id']}，跳过更新")
                continue
            c.params.update(a["params"])
            report.append(f"更新 {a['id']} 参数")
        elif op == "delete":
            if net.get(a["id"]):
                net.remove(a["id"])
                report.append(f"删除 {a['id']}")
            else:
                report.append(f"未找到 {a['id']}，跳过删除")
        elif op == "build_filter":
            topo = a["topo"]
            if topo == "lowpass":
                items = lowpass_lc(a["order"], a["fc_ghz"] * 1e9, a["z0"],
                                   a["ripple_db"], a["kind"])
                desc = f"{a['order']} 阶低通 fc={a['fc_ghz']:g} GHz"
            elif topo == "highpass":
                items = highpass_lc(a["order"], a["fc_ghz"] * 1e9, a["z0"],
                                    a["ripple_db"], a["kind"])
                desc = f"{a['order']} 阶高通 fc={a['fc_ghz']:g} GHz"
            elif topo == "bandstop":
                items = bandstop_lc(a["order"], a["f1_ghz"] * 1e9,
                                    a["f2_ghz"] * 1e9, a["z0"],
                                    a["ripple_db"], a["kind"])
                desc = f"{a['order']} 阶带阻 {a['f1_ghz']:g}–{a['f2_ghz']:g} GHz"
            else:
                items = bandpass_lc(a["order"], a["f1_ghz"] * 1e9,
                                    a["f2_ghz"] * 1e9, a["z0"],
                                    a["ripple_db"], a["kind"])
                desc = f"{a['order']} 阶带通 {a['f1_ghz']:g}–{a['f2_ghz']:g} GHz"
            built = ladder_to_network(items, a["z0"])
            net.components = built.components
            net.ports = built.ports
            net.z0 = a["z0"]
            report.append(f"生成{desc}（{len(net.components)} 个元件）")
        elif op == "build_balun":
            from ..balun import build_network as build_balun_network
            built = build_balun_network(a["f_ghz"] * 1e9, a["z0"])
            net.components = built.components
            net.ports = built.ports
            net.z0 = a["z0"]
            f0 = a["f_ghz"]
            project.analysis.start_ghz = f0 * 0.5
            project.analysis.stop_ghz = f0 * 1.5
            project.analysis.points = max(401, project.analysis.points)
            report.append(f"生成 1:4 巴伦 @ {f0:g} GHz"
                          f"（{len(net.components)} 个元件，差分 {4*a['z0']:g} Ω；"
                          f"扫频已设为 {f0*0.5:g}–{f0*1.5:g} GHz）")
        elif op == "run":
            report.append("（需要运行仿真）")
    return report