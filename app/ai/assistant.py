"""AI 助手：把电路上下文交给模型，解析其返回的修改建议；未配置模型时用本地规则。

设计原则：
  1. 模型只负责"建议"，真正改电路前要在界面上由用户点"应用"；
  2. 返回必须是 JSON（reply + actions），解析失败就只当普通文字回复；
  3. 没有配置模型时，本地规则仍能完成最常见的几件事（设计滤波器、算微带线、改频、看结果）。
"""
from __future__ import annotations

import json
import math
import re
from typing import Dict, List, Optional, Tuple

from .. import inverse, tline
from ..engine import SweepResult
from ..project import Project
from .actions import validate_actions
from .client import AIClient, AIError
from . import personas
from .config import AIConfig

SYSTEM_PROMPT = """你是射频/微波电路设计助手，嵌入在一个电路仿真软件里。
用户给你当前电路（元件、端口、分析设置）和最近一次仿真结果，你要给出可执行的建议。

只输出一个 JSON 对象，不要输出 Markdown 代码块或额外说明：
{"reply": "给用户看的中文说明", "actions": [ ... ]}

actions 可以为空数组。可用动作：
  {"op":"set_z0","value":50}
  {"op":"set_analysis","start_ghz":1,"stop_ghz":4,"points":401,"sweep":"linear"}
  {"op":"clear"}
  {"op":"add","id":"L1","kind":"L","nodes":["n1","m0"],"params":{"l":4.2}}
       kind 只能是 R/L/C/TL/MS/COAX；节点用字符串，地固定写 "0"；
       参数：R→r(Ω)，L→l(nH)，C→c(pF)，TL→z0/er/len/loss，
             MS→w/h/er/len/loss，COAX→d_in/d_out/er/len/loss
  {"op":"update","id":"L1","params":{"l":4.5}}
  {"op":"delete","id":"L1"}
  {"op":"build_filter","topo":"lowpass","order":3,"fc_ghz":3,"z0":50,"ripple_db":0.5}
  {"op":"build_filter","topo":"bandpass","order":3,"f1_ghz":2.3,"f2_ghz":2.7,"z0":50,"ripple_db":0.5}
  {"op":"build_balun","f_ghz":2.4,"z0":50}
       生成 1:4 巴伦（输出差分 200 Ω），端口参考阻抗 P1=50、P2/P3=100
  {"op":"run"}

规则：
* 不确定就不要编造参数；宁可 actions 为空、在 reply 里说明需要哪些信息；
* 一次最多 10 个动作；
* 只做电路层面的修改，不要声称能跑全波电磁或非线性分析；
* reply 用简体中文，简洁、给出关键数值与理由。"""

FENCE = chr(96) * 3


# ---------------------------------------------------------------- 上下文
def build_context(project: Project, result: Optional[SweepResult] = None) -> dict:
    net = project.network
    ctx = {
        "z0": net.z0,
        "ports": [{"id": p.pid, "node": p.node} for p in net.ports],
        "components": [
            {"id": c.cid, "kind": c.kind, "nodes": list(c.nodes),
             "params": {k: round(v, 6) for k, v in c.params.items()}}
            for c in net.components
        ],
        "analysis": {
            "start_ghz": project.analysis.start_ghz,
            "stop_ghz": project.analysis.stop_ghz,
            "points": project.analysis.points,
            "sweep": project.analysis.sweep,
        },
    }
    if result and result.freqs:
        n = result.n_ports()
        mid = len(result.freqs) // 2
        s11 = result.db(1, 1)
        ctx["metrics"] = {
            "ports": n,
            "freq_ghz_mid": round(result.freqs[mid] / 1e9, 6),
            "s11_db_mid": round(s11[mid], 3),
            "s11_db_worst": round(max(s11), 3),
            "s21_db_mid": round(result.db(2, 1)[mid], 3) if n >= 2 else None,
            "s21_db_min": round(min(result.db(2, 1)), 3) if n >= 2 else None,
        }
    return ctx


def context_text(ctx: dict) -> str:
    lines = [f"参考阻抗 Z0 = {ctx['z0']:g} Ω",
             "端口：" + ("、".join(f"{p['id']}→{p['node']}" for p in ctx["ports"]) or "无"),
             "元件："]
    if not ctx["components"]:
        lines.append("  （空）")
    for c in ctx["components"]:
        params = "，".join(f"{k}={v:g}" for k, v in c["params"].items())
        lines.append(f"  {c['id']} {c['kind']} {'-'.join(c['nodes'])}  {params}")
    a = ctx["analysis"]
    lines.append(f"分析：{a['start_ghz']:g}–{a['stop_ghz']:g} GHz，{a['points']} 点，{a['sweep']}")
    if "metrics" in ctx:
        m = ctx["metrics"]
        extra = f"，|S21|={m['s21_db_mid']:g} dB" if m.get("s21_db_mid") is not None else ""
        lines.append(f"结果：中频 {m['freq_ghz_mid']:g} GHz，|S11|={m['s11_db_mid']:g} dB，"
                     f"最差 |S11|={m['s11_db_worst']:g} dB{extra}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 解析
def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(FENCE + r"(?:json)?\s*(.*?)" + FENCE, text, re.S)
    return m.group(1).strip() if m else text


def _first_json(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_model_output(text: str) -> Tuple[str, List[dict], List[str]]:
    raw = _strip_fences(text)
    blob = _first_json(raw)
    if not blob:
        reply = text.strip()
        if not reply:
            return "", [], ["模型返回为空"]
        # 模型没按 JSON 协议回答：当普通文字回复展示，不再报错
        return reply, [], []
    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        return raw, [], [f"JSON 解析失败：{e}"]
    reply = str(d.get("reply", "")).strip()
    actions, errors = validate_actions(d.get("actions") or [])
    return reply, actions, errors


# ---------------------------------------------------------------- 本地规则
_GHZ = re.compile(r"(\d+(?:\.\d+)?)\s*(GHz|ghz|G|MHz|mhz|kHz|khz)\b", re.I)
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MHz|mhz)?\s*[-–~至]\s*(\d+(?:\.\d+)?)\s*(MHz|mhz|GHz|ghz)", re.I)
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def _nums(text: str) -> List[float]:
    return [float(x) for x in _NUM.findall(text)]


def _ghz_numbers(text: str) -> List[float]:
    """把 GHz / MHz / kHz 统一换算成 GHz。"""
    out = []
    for m in _GHZ.finditer(text):
        v = float(m.group(1))
        u = m.group(2).lower()
        if u.startswith("khz"):
            v /= 1e6
        elif u.startswith("mhz"):
            v /= 1e3
        out.append(v)
    return out


def offline_plan(request: str, project: Project,
                 result: Optional[SweepResult] = None) -> Dict:
    """本地规则引擎：没配模型时也能完成常见任务。"""
    q = request.lower()
    nums = _nums(request)
    ghz = _ghz_numbers(request)

    if "巴伦" in request or "balun" in q:
        f = ghz[0] if ghz else 2.4
        note = ""
        mr = _RANGE.search(request)
        if mr:
            a1, a2, unit = float(mr.group(1)), float(mr.group(2)), mr.group(3).lower()
            if unit.startswith("m"):
                a1, a2 = a1 / 1000.0, a2 / 1000.0
            f = math.sqrt(max(a1, 1e-9) * max(a2, 1e-9))
            note = (f"（要求 {a1*1000:g}–{a2*1000:g} MHz 宽带；四分之一波长结构是窄带的，"
                    f"这里按几何中心 {f*1000:.1f} MHz 设计，全带需多节或变压器型）")
        actions = [{"op": "build_balun", "f_ghz": f, "z0": project.network.z0},
                   {"op": "run"}, {"op": "switch_tab", "tab": "plot"}]
        from ..balun import design_1to4
        d = design_1to4(f * 1e9, project.network.z0)
        return {"reply": f"本地规则：生成 1:4 巴伦（balun）@{f:g} GHz，"
                         f"输入 {project.network.z0:g} Ω，差分 {4*project.network.z0:g} Ω；"
                         f"分支线 {d['branch_z0']:.2f} Ω，λ/4={d['quarter_mm']:.3f} mm。"
                         f"预期 |S21|=|S31|=-3.01 dB，相位差 180°，可看 S11 曲线确认匹配。{note}",
                "actions": actions, "errors": [], "source": "offline"}

    if "低通" in request or "lowpass" in q or "low pass" in q:
        order = 3
        m = re.search(r"(\d+)\s*阶", request)
        if m:
            order = max(1, min(12, int(m.group(1))))
        fc = ghz[0] if ghz else 3.0
        ripple = 0.5
        mr = re.search(r"(?:纹波|ripple)\s*(?:dB)?\s*[=:：]?\s*(\d+(?:\.\d+)?)", request, re.I)
        if mr:
            ripple = float(mr.group(1))
        actions = [{"op": "build_filter", "topo": "lowpass", "order": order,
                    "fc_ghz": fc, "z0": project.network.z0,
                    "ripple_db": ripple, "kind": "chebyshev"},
                   {"op": "run"}]
        return {"reply": f"本地规则：生成 {order} 阶切比雪夫低通，截止 {fc:g} GHz，"
                         f"纹波 {ripple:g} dB，Z0={project.network.z0:g} Ω。"
                         f"点「应用」后会自动跑一次仿真。",
                "actions": actions, "errors": [], "source": "offline"}

    if "带通" in request or "bandpass" in q or "band pass" in q:
        order = 3
        m = re.search(r"(\d+)\s*阶", request)
        if m:
            order = max(1, min(12, int(m.group(1))))
        f1, f2 = (sorted(ghz[:2]) if len(ghz) >= 2 else (2.3, 2.7))
        if f1 == f2:
            f2 = f1 + 0.1
        actions = [{"op": "build_filter", "topo": "bandpass", "order": order,
                    "f1_ghz": f1, "f2_ghz": f2, "z0": project.network.z0,
                    "ripple_db": 0.5, "kind": "chebyshev"},
                   {"op": "run"}]
        return {"reply": f"本地规则：生成 {order} 阶带通 {f1:g}–{f2:g} GHz。",
                "actions": actions, "errors": [], "source": "offline"}

    if "微带" in request or "microstrip" in q or "线宽" in request:
        z0 = project.network.z0
        er, h = 4.4, 1.6
        mz = re.search(r"(?:Z0|z0)\s*[=:：]?\s*(\d+(?:\.\d+)?)", request)
        me = re.search(r"(?:εr|er|介电常数)\s*[=:：]?\s*(\d+(?:\.\d+)?)", request, re.I)
        mh = re.search(r"(?:h|厚度|板厚)\s*[=:：]?\s*(\d+(?:\.\d+)?)", request, re.I)
        if mz:
            z0 = float(mz.group(1))
        elif nums and 10 < nums[0] < 300:
            z0 = nums[0]
        if me:
            er = float(me.group(1))
        elif re.search(r"fr[- ]?4", request, re.I):
            er = 4.4
        elif re.search(r"氧化铝|alumina", request, re.I):
            er = 9.8
        else:
            cand = [x for x in nums if 1.0 < x < 20]
            if cand:
                er = cand[0]
        if mh:
            h = float(mh.group(1))
        else:
            cand_h = [x for x in nums if 0.05 < x < 5]
            if cand_h:
                h = cand_h[-1]
        f_hz = (ghz[0] if ghz else 2.4) * 1e9
        d = tline.microstrip_design(z0, h, er, f_hz)
        return {"reply": f"本地规则：{z0:g} Ω 微带线（εr={er:g}，h={h:g} mm）→ "
                         f"线宽 W={d['w_mm']:.4f} mm，εeff={d['eeff']:.4f}，"
                         f"λ/4={d['quarter_mm']:.4f} mm。",
                "actions": [], "errors": [], "source": "offline"}

    if "匹配" in request or "match" in q:
        if len(nums) >= 2:
            rs, rl = nums[0], nums[1]
            f = ghz[0] if ghz else 2.4
            m = inverse.l_network_match(rs, rl, f * 1e9)
            if m.get("identity"):
                return {"reply": "源与负载阻抗相同，不需要匹配网络。",
                        "actions": [], "errors": [], "source": "offline"}
            lines = [f"本地规则：{rs:g}→{rl:g} Ω，@ {f:g} GHz，Q={m['q']:.4f}。"]
            for i, s in enumerate(m["solutions"], 1):
                lines.append(f"方案{i} {s['name']}：{s['shunt']['element']} "
                             f"{s['shunt']['value']:.4g} {s['shunt']['unit']}，"
                             f"{s['series']['element']} {s['series']['value']:.4g} "
                             f"{s['series']['unit']}")
            lines.append("（提示：并联元件接在高阻一侧）")
            return {"reply": "\n".join(lines), "actions": [], "errors": [],
                    "source": "offline"}
        return {"reply": "请给出源阻抗与负载阻抗，例如：匹配 50 到 100，2.4 GHz",
                "actions": [], "errors": [], "source": "offline"}

    if "改频" in request or "调到" in request or "tune" in q or "retune" in q:
        ls = [c for c in project.network.components if c.kind == "L"]
        cs = [c for c in project.network.components if c.kind == "C"]
        target = ghz[0] if ghz else None
        if ls and cs and target:
            l, c = ls[0], cs[0]
            r = inverse.retune_lc(l.params.get("l", 1.0), c.params.get("c", 1.0),
                                  target * 1e9, keep="L")
            actions = [{"op": "update", "id": c.cid, "params": {"c": r["c_pf"]}},
                       {"op": "run"}]
            return {"reply": f"本地规则：当前 {l.cid}={l.params.get('l'):g} nH、"
                             f"{c.cid}={c.params.get('c'):g} pF，谐振 "
                             f"{r['f_now_hz']/1e9:.4g} GHz；调到 {target:g} GHz 需把 "
                             f"{c.cid} 改为 {r['c_pf']:.4g} pF（Δ{r['delta_pf']:+.4g} pF）。",
                    "actions": actions, "errors": [], "source": "offline"}
        return {"reply": "改频需要：目标频率 + 电路中至少一个电感与一个电容。"
                         "也可以直接用「反向计算 → 改频微调」。",
                "actions": [], "errors": [], "source": "offline"}

    if any(k in request for k in ("分析", "解释", "怎么样")) or \
            "analyze" in q or "explain" in q:
        if not result or not result.freqs:
            return {"reply": "还没有仿真结果，先点「运行仿真」。",
                    "actions": [], "errors": [], "source": "offline"}
        mid = len(result.freqs) // 2
        s11 = result.db(1, 1)
        txt = [f"当前 {len(result.freqs)} 个频点（{result.freqs[0]/1e9:g}–"
               f"{result.freqs[-1]/1e9:g} GHz），Z0={result.z0:g} Ω。",
               f"中频 {result.freqs[mid]/1e9:g} GHz：|S11|={s11[mid]:.2f} dB"
               + (f"，|S21|={result.db(2, 1)[mid]:.2f} dB" if result.n_ports() >= 2 else "")
               + f"；全带最差 |S11|={max(s11):.2f} dB。"]
        if result.n_ports() >= 2:
            s21 = result.db(2, 1)
            txt.append(f"插损范围 {min(s21):.2f}～{max(s21):.2f} dB；"
                       f"回波损耗最好 {min(s11):.2f} dB。")
        return {"reply": "\n".join(txt), "actions": [], "errors": [], "source": "offline"}

    return {"reply": "未配置 AI 模型，本地规则只支持：设计低通/带通、算微带线、"
                     "阻抗匹配、改频、分析当前结果。\n"
                     "要更自由的对话，请在「AI 设置」里填写模型端点与名称"
                     "（任意 OpenAI 兼容接口，如本地 Ollama / LM Studio）。",
            "actions": [], "errors": [], "source": "offline"}


# ---------------------------------------------------------------- 助手
class Assistant:
    def __init__(self, cfg: AIConfig, client: Optional[AIClient] = None,
                 persona: Optional[str] = None):
        self.cfg = cfg
        self.client = client or AIClient(cfg)
        self.persona = personas.resolve(
            persona or getattr(cfg, "persona", None))["id"]

    def _system_prompt(self) -> str:
        """系统提示词 = 角色专业前置 + 基础协议。

        角色段只影响分析视角与答复口径；personas.compose 已显式声明
        JSON 输出协议与动作格式优先于角色设定，改角色不会破坏自动执行。
        """
        return personas.compose(SYSTEM_PROMPT, self.persona)

    def ask(self, request: str, project: Project,
            result: Optional[SweepResult] = None,
            history: Optional[List[Dict[str, str]]] = None) -> Dict:
        request = (request or "").strip()
        if not request:
            return {"reply": "请输入需求。", "actions": [], "errors": [],
                    "source": "offline"}
        ctx = build_context(project, result)
        if not self.cfg.enabled:
            return offline_plan(request, project, result)

        messages = [{"role": "system", "content": self._system_prompt()}]
        for h in (history or [])[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])[:2000]})
        messages.append({"role": "user",
                         "content": f"当前电路：\n{context_text(ctx)}\n\n需求：{request}"})
        try:
            text = self.client.chat(messages)
        except AIError as e:
            plan = offline_plan(request, project, result)
            plan["reply"] = f"模型调用失败：{e}\n已改用本地规则：\n{plan['reply']}"
            plan["errors"] = [str(e)]
            return plan
        reply, actions, errors = parse_model_output(text)
        return {"reply": reply or "（模型没有给出文字说明）",
                "actions": actions, "errors": errors, "source": "model",
                "raw": text}

    # ------------------------------------------------------------ 自动执行
    def _ask_once(self, request: str, ctx: dict, transcript: List[str],
                  final: bool,
                  history: Optional[List[Dict[str, str]]] = None
                  ) -> Tuple[str, List[dict], List[str]]:
        messages = [{"role": "system", "content": self._system_prompt()}]
        turns = history if history is not None else getattr(self, "_history", None)
        for h in turns or []:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"],
                                 "content": str(h["content"])[:2000]})
        body = f"当前电路：\n{context_text(ctx)}"
        if transcript:
            body += "\n\n已执行的操作与结果：\n" + "\n".join(transcript)
        body += f"\n\n需求：{request}"
        if final:
            body += ("\n\n（这是最后一轮：请基于上面的执行结果给出最终分析与建议，"
                     "actions 必须为空数组。）")
        else:
            body += ("\n\n如果需要先执行计算或仿真，请把动作放进 actions；"
                     "执行结果会回传给你做下一步判断。")
        messages.append({"role": "user", "content": body})
        text = self.client.chat(messages)
        return parse_model_output(text)

    def run_agent(self, request: str, project: Project,
                  result: Optional[SweepResult] = None,
                  executor=None, max_rounds: int = 3,
                  history: Optional[List[Dict[str, str]]] = None) -> Dict:
        """多轮自动执行：模型下动作 → 执行器执行 → 结果回流 → 再分析。

        max_rounds=3 表示最多 3 次模型调用；最后一轮要求模型只总结、不再下动作。
        返回 {reply, actions, results, source, tab_hint, tool_hint, files, result}。
        """
        request = (request or "").strip()
        if not request:
            return {"reply": "请输入需求。", "actions": [], "results": [],
                    "source": "offline"}
        self._history = list(history or [])

        all_actions: List[dict] = []
        all_results: List[Dict] = []
        replies: List[str] = []
        transcripts: List[str] = []

        if not self.cfg.enabled:
            plan = offline_plan(request, project, result)
            replies.append(plan["reply"])
            all_actions = plan["actions"]
            if executor and all_actions:
                all_results = executor.execute(all_actions)
                transcripts = [f"{r['op']}: {r['text']}" for r in all_results]
            if executor and executor.result:
                replies.append(offline_plan("分析当前结果", project,
                                            executor.result)["reply"])
            return {"reply": "\n\n".join(x for x in replies if x),
                    "actions": all_actions, "results": all_results,
                    "source": "offline",
                    "tab_hint": getattr(executor, "tab_hint", None),
                    "tool_hint": getattr(executor, "tool_hint", None),
                    "files": list(getattr(executor, "files", [])),
                    "result": getattr(executor, "result", None)}

        cur_result = result
        errors: List[str] = []
        model_empty = True
        for rnd in range(max_rounds):
            final = (rnd == max_rounds - 1)
            ctx = build_context(project, cur_result if cur_result else result)
            try:
                reply, actions, errs = self._ask_once(request, ctx, transcripts, final)
            except AIError as e:
                replies.append(f"模型调用失败：{e}")
                errors.append(str(e))
                break
            errors.extend(errs)
            if reply.strip():
                replies.append(reply)
                model_empty = False
            if actions:
                model_empty = False
            if not actions:
                break
            all_actions.extend(actions)
            if executor:
                res = executor.execute(actions)
                all_results.extend(res)
                transcripts = [f"{r['op']}: {r['text']}" for r in all_results]
                cur_result = executor.result or cur_result
            if final:
                break
        if model_empty and not all_actions:
            # 模型返回空（超时/被截断/服务异常）：自动回落本地规则并执行
            plan = offline_plan(request, project, result)
            all_actions = plan["actions"]
            replies = [f"模型未返回内容，已按本地规则执行：\n{plan['reply']}"]
            if executor and all_actions:
                all_results = executor.execute(all_actions)
            if executor and executor.result:
                replies.append(offline_plan("分析当前结果", project,
                                            executor.result)["reply"])
            return {"reply": "\n\n".join(x for x in replies if x),
                    "actions": all_actions, "results": all_results,
                    "source": "offline", "errors": errors,
                    "tab_hint": getattr(executor, "tab_hint", None),
                    "tool_hint": getattr(executor, "tool_hint", None),
                    "files": list(getattr(executor, "files", [])),
                    "result": getattr(executor, "result", None)}
        return {"reply": "\n\n".join(x for x in replies if x),
                "actions": all_actions, "results": all_results,
                "source": "model", "errors": errors,
                "tab_hint": getattr(executor, "tab_hint", None),
                "tool_hint": getattr(executor, "tool_hint", None),
                "files": list(getattr(executor, "files", [])),
                "result": getattr(executor, "result", None)}