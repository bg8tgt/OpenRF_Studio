"""AI 辅助设计测试：配置、客户端、协议解析、动作应用、本地规则、界面集成。

用本机 127.0.0.1 起一个假的 OpenAI 兼容服务，避免依赖外网与真实密钥。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai import actions as ai_actions
from app.ai.assistant import Assistant, parse_model_output
from app.ai.client import AIClient, AIError
from app.ai.executor import Executor
from app.ai.config import AIConfig, load_config, mask_key, save_config
from app.project import Project, new_demo_project

FAIL = []
LAST = {}


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


# ---------------------------------------------------------------- 假服务
class Handler(BaseHTTPRequestHandler):
    COUNT = 0

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        LAST["path"] = self.path
        LAST["auth"] = self.headers.get("Authorization")
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"data": [{"id": "mock-large"}, {"id": "mock-small"}]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n).decode("utf-8")
        LAST["body"] = json.loads(raw)
        LAST["auth"] = self.headers.get("Authorization")
        if "fail" in self.path:
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        msgs = LAST["body"].get("messages", [])
        text = " ".join(str(m.get("content", "")) for m in msgs)
        if "多轮" in text:
            Handler.COUNT += 1
            if Handler.COUNT == 1:
                payload = {
                    "reply": "先建滤波器并算一条微带线，然后跑仿真。",
                    "actions": [
                        {"op": "build_filter", "topo": "lowpass", "order": 3,
                         "fc_ghz": 2.4, "z0": 50, "ripple_db": 0.5},
                        {"op": "calc", "what": "microstrip", "z0": 50,
                         "h": 1.6, "er": 4.4, "f_ghz": 2.4},
                        {"op": "run"},
                        {"op": "switch_tab", "tab": "smith"},
                    ],
                }
            else:
                payload = {"reply": "已生成 3 阶低通并完成仿真，"
                                    "微带线宽 3.083 mm，看一下史密斯圆图即可。",
                           "actions": []}
        else:
            payload = {
                "reply": "已生成 3 阶低通。",
                "actions": [
                    {"op": "build_filter", "topo": "lowpass", "order": 3,
                     "fc_ghz": 2.4, "z0": 50, "ripple_db": 0.5},
                    {"op": "run"},
                ],
            }
        content = json.dumps(payload, ensure_ascii=False)
        self._send(200, {"choices": [{"message": {"role": "assistant",
                                                  "content": content}}]})


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


# ---------------------------------------------------------------- 1 配置
def test_config(base):
    print("== 1. AI 配置")
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ai.json")
    cfg = AIConfig(base_url=base, model="mock-large", api_key="sk-test-1234567890",
                   temperature=0.2, max_tokens=800, timeout=15)
    save_config(cfg, path)
    back = load_config(path)
    check("保存/读取往返", back.model == "mock-large" and back.base_url == base)
    check("密钥掩码", mask_key("sk-test-1234567890").endswith("7890")
          and "sk-test" not in mask_key("sk-test-1234567890"))
    check("enabled 判定", AIConfig(base_url=base, model="x").enabled)
    check("无模型时 disabled", not AIConfig(base_url=base, model="").enabled)
    os.environ["OPENRF_AI_MODEL"] = "env-model"
    try:
        check("环境变量覆盖模型", load_config(path).model == "env-model")
    finally:
        os.environ.pop("OPENRF_AI_MODEL", None)


# ---------------------------------------------------------------- 2 客户端
def test_client(base):
    print("== 2. 客户端")
    cfg = AIConfig(base_url=base, model="mock-large", api_key="sk-abc", timeout=10)
    cli = AIClient(cfg)
    models = cli.list_models()
    check("列出模型", models == ["mock-large", "mock-small"], str(models))
    check("鉴权头正确", LAST.get("auth") == "Bearer sk-abc", str(LAST.get("auth")))
    text = cli.chat([{"role": "user", "content": "hi"}])
    check("chat 返回内容", "已生成" in text, text[:40])
    body = LAST.get("body") or {}
    check("请求体含 model/messages",
          body.get("model") == "mock-large" and body.get("messages"), str(body)[:80])
    check("stream=False", body.get("stream") is False)
    bad = AIClient(AIConfig(base_url=base + "/fail", model="x", api_key="k", timeout=5))
    try:
        bad.chat([{"role": "user", "content": "x"}], temperature=0)
    except AIError as e:
        check("401 抛 AIError 且带原因", "401" in str(e) and "invalid" in str(e), str(e)[:60])
    else:
        check("401 抛 AIError", False)
    err_cli = AIClient(AIConfig(base_url="http://127.0.0.1:1/v1", model="x", timeout=2))
    try:
        err_cli.chat([{"role": "user", "content": "x"}])
    except AIError as e:
        check("连不上时抛 AIError", "连接失败" in str(e) or "超时" in str(e), str(e)[:60])
    else:
        check("连不上时抛 AIError", False)


# ---------------------------------------------------------------- 3 解析
def test_parse():
    print("== 3. 模型输出解析")
    txt = '{"reply":"ok","actions":[{"op":"set_z0","value":75}]}'
    reply, acts, errs = parse_model_output(txt)
    check("纯 JSON", reply == "ok" and acts[0]["value"] == 75.0 and not errs)
    fenced = "说明\n" + chr(96) * 3 + "json\n" + txt + "\n" + chr(96) * 3
    reply, acts, errs = parse_model_output(fenced)
    check("Markdown 代码块", reply == "ok" and len(acts) == 1)
    reply, acts, errs = parse_model_output("我不知道怎么写 JSON")
    check("非 JSON 退化为文字", acts == [] and "不知道" in reply)
    check("非 JSON 不再报错", errs == [], str(errs))
    reply, acts, errs = parse_model_output("   ")
    check("空回复给出提示", errs and not reply, str(errs))
    reply, acts, errs = parse_model_output('{"reply":"x","actions":[{"op":"nuke"}]}')
    check("未知 op 被拒", acts == [] and any("不支持" in e for e in errs), str(errs))


# ---------------------------------------------------------------- 4 动作
def test_actions():
    print("== 4. 动作校验与应用")
    good, errs = ai_actions.validate_actions([
        {"op": "clear"},
        {"op": "add", "id": "L1", "kind": "L", "nodes": ["n1", "m0"], "params": {"l": 4.2}},
        {"op": "add", "kind": "C", "nodes": ["m0", "0"], "params": {"c": 1.1}},
        {"op": "set_z0", "value": 75},
        {"op": "set_analysis", "start_ghz": 1, "stop_ghz": 4, "points": 201},
    ])
    check("合法动作全部通过", len(good) == 5 and not errs, str(errs))
    p = Project("测试")
    rep = ai_actions.apply_actions(p, good)
    check("清空后新增 2 个元件", len(p.network.components) == 2, str(len(p.network.components)))
    check("Z0 已改", p.network.z0 == 75)
    check("分析设置已改", p.analysis.start_ghz == 1 and p.analysis.points == 201)
    check("执行报告非空", len(rep) >= 5, str(rep)[:80])

    bad, errs = ai_actions.validate_actions([
        {"op": "add", "kind": "XYZ", "nodes": ["a", "b"], "params": {}},
        {"op": "add", "kind": "L", "nodes": ["a"], "params": {"l": 1}},
        {"op": "add", "kind": "L", "nodes": ["a", "b"], "params": {"l": -5}},
        {"op": "set_z0", "value": "abc"},
    ])
    check("非法动作被拒", bad == [] and len(errs) >= 4, str(errs)[:120])

    bf, errs = ai_actions.validate_actions([
        {"op": "build_filter", "topo": "lowpass", "order": 3, "fc_ghz": 2.4,
         "z0": 50, "ripple_db": 0.5},
    ])
    p2 = new_demo_project()
    ai_actions.apply_actions(p2, bf)
    check("build_filter 生成 3 个元件", len(p2.network.components) == 3,
          str(len(p2.network.components)))
    check("build_filter 端口为 P1/P2",
          [x.pid for x in p2.network.ports] == ["P1", "P2"])


# ---------------------------------------------------------------- 5 助手
def test_assistant(base):
    print("== 5. 助手（模型 / 本地规则）")
    cfg = AIConfig(base_url=base, model="mock-large", api_key="sk-abc", timeout=10)
    a = Assistant(cfg)
    p = new_demo_project()
    res = a.ask("设计 3 阶 2.4GHz 低通", p)
    check("模型来源", res["source"] == "model", res.get("source", ""))
    check("解析出 2 个动作", len(res["actions"]) == 2, str(res["actions"])[:80])
    ai_actions.apply_actions(p, [x for x in res["actions"] if x["op"] != "run"])
    check("应用后电路被替换为 3 元件", len(p.network.components) == 3)

    off = Assistant(AIConfig(model=""))
    p2 = new_demo_project()
    r1 = off.ask("设计 5 阶 900MHz 低通 纹波 0.1dB", p2)
    act = r1["actions"][0]
    check("本地规则：频段与纹波", abs(act["fc_ghz"] - 0.9) < 1e-9 and
          abs(act["ripple_db"] - 0.1) < 1e-9, str(act))
    r2 = off.ask("50Ω 微带线 FR4 1.6mm", p2)
    check("本地规则：微带线宽 ≈3.08mm", "3.08" in r2["reply"].replace(" ", ""), r2["reply"][:80])
    r3 = off.ask("匹配 50 到 100 2.4GHz", p2)
    check("本地规则：匹配给出两套解", "方案2" in r3["reply"])
    r4 = off.ask("改频到 2.5GHz", p2)
    check("本地规则：改频给出动作", any(x["op"] == "update" for x in r4["actions"]))
    rb = off.ask("设计 1:4 巴伦 2.4GHz", p2)
    check("离线识别巴伦", any(a["op"] == "build_balun" for a in rb["actions"]),
          str(rb["actions"])[:80])
    check("巴伦回复含 1:4/180°", "1:4" in rb["reply"] and "180" in rb["reply"],
          rb["reply"][:60])
    r5 = off.ask("帮我随便看看", p2)
    check("未知需求给出提示", "AI 设置" in r5["reply"] or "本地规则" in r5["reply"])

    # 模型失败 → 回落本地规则
    bad = Assistant(AIConfig(base_url="http://127.0.0.1:1/v1", model="x", timeout=2))
    r6 = bad.ask("设计 3 阶 2GHz 低通", new_demo_project())
    check("模型失败时回落本地规则", r6["source"] == "offline" and r6["actions"],
          r6["reply"][:60])


# ---------------------------------------------------------------- 5.5 执行器
def test_executor():
    print("== 5.5 执行器（AI 调用软件功能）")
    tmp = tempfile.mkdtemp()
    p = new_demo_project()
    ex = Executor(p, out_dir=tmp)
    res = ex.execute([
        {"op": "calc", "what": "microstrip", "z0": 50, "h": 1.6, "er": 4.4, "f_ghz": 2.4},
        {"op": "calc", "what": "lc", "f_ghz": 2.4, "l_nh": 10},
        {"op": "calc", "what": "l_match", "rs": 50, "rl": 100, "f_ghz": 2.4},
        {"op": "run"},
        {"op": "report"},
        {"op": "switch_tab", "tab": "schematic"},
        {"op": "open_tool", "name": "tline"},
    ])
    ok = [r for r in res if r["ok"]]
    check("执行器：全部动作成功", len(ok) == len(res), str([r["text"][:30] for r in res]))
    check("算微带线含 3.08", any("3.08" in r["text"] for r in res))
    check("算 LC 含 pF", any("pF" in r["text"] for r in res))
    check("L 型匹配给两方案", any("方案2" in r["text"] for r in res))
    check("run 产出结果", ex.result is not None and len(ex.result.freqs) > 0)
    check("report 含 dB", any("dB" in r["text"] for r in res))
    check("页签提示", ex.tab_hint == "schematic", str(ex.tab_hint))
    check("工具提示", ex.tool_hint == "tline", str(ex.tool_hint))
    ex.execute([{"op": "save_project"}])
    check("保存工程生成文件", any(f.endswith(".json") for f in ex.files), str(ex.files))
    ex.execute([{"op": "export_touchstone"}])
    check("导出 Touchstone 生成文件", any(f.endswith(".s2p") for f in ex.files), str(ex.files))

    # 失败动作不崩
    bad = ex.execute([{"op": "update", "id": "不存在", "params": {"l": 2.0}}])
    check("非法/缺失目标不崩", bad and bad[0]["ok"] is True, str(bad))


# ---------------------------------------------------------------- 5.8 多轮
def test_agent(base):
    print("== 5.8 多轮自动执行（模型→执行→分析）")
    Handler.COUNT = 0
    cfg = AIConfig(base_url=base, model="mock-large", api_key="sk-abc", timeout=10)
    a = Assistant(cfg)
    p = new_demo_project()
    ex = Executor(p, out_dir=tempfile.mkdtemp())
    res = a.run_agent("多轮：设计 3 阶 2.4GHz 低通，并分析结果", p, executor=ex)
    check("自动执行来源=模型", res["source"] == "model")
    check("执行了 >=3 个动作", len(res["results"]) >= 3, str(len(res["results"])))
    check("电路已生成 3 元件", len(p.network.components) == 3,
          str(len(p.network.components)))
    check("仿真结果已产生", ex.result is not None)
    check("页签切换建议", res["tab_hint"] == "smith", str(res["tab_hint"]))
    check("最终回复含分析", "史密斯" in res["reply"] or "分析" in res["reply"],
          res["reply"][:60])
    check("动作日志可见", any("dB" in (r.get("text") or "") for r in res["results"]))

    # 离线也能自动执行
    off = Assistant(AIConfig(model=""))
    p2 = new_demo_project()
    ex2 = Executor(p2, out_dir=tempfile.mkdtemp())
    r2 = off.run_agent("设计 3 阶 2GHz 低通", p2, executor=ex2)
    check("离线自动执行生成电路", len(p2.network.components) == 3)
    check("离线执行后有结果", ex2.result is not None)
    check("离线回复含结果分析", "S11" in r2["reply"] or "dB" in r2["reply"], r2["reply"][:60])


# ---------------------------------------------------------------- 6 界面
def test_ui():
    print("== 6. 界面集成")
    import time
    from app.ui.app import App
    from app.ui.ai_panel import AIPanel, AISettingsDialog

    app = App()
    app.withdraw()
    try:
        for _ in range(12):
            app.update()
            time.sleep(0.1)
            if app.result is not None:
                break
        check("AI 页签存在", isinstance(app.ai_panel, AIPanel))
        # 测试机可能已有真实配置；这里强制切到本地规则再断言
        # 出厂默认已预填 DeepSeek 配置，AIConfig() 不再等于"未配置"；
        # 这里显式构造空配置，才真正回到本地规则状态。
        blank = AIConfig(base_url="", model="", api_key="")
        app.ai_panel.cfg = blank
        app.ai_panel.assistant = Assistant(blank)
        app.ai_panel.refresh_status()
        check("默认本地规则状态", "未配置" in app.ai_panel.var_status.get(),
              app.ai_panel.var_status.get())
        res = app.ai_panel.ask_sync("设计 3 阶 2GHz 低通")
        check("界面内本地规则可用", "低通" in res["reply"] and res["actions"])
        n_before = len(app.project.network.components)
        report = app.ai_apply_actions(res["actions"])
        check("应用后元件变化", len(app.project.network.components) != n_before or report,
              str(report)[:60])
        check("应用后已重新仿真", app.result is not None)
        app.ai_panel._set_pending([{"op": "set_z0", "value": 60}])
        check("待应用列表显示", app.ai_panel.pending_list.size() == 1)
        app.ai_panel.discard_pending()
        check("丢弃后列表清空", app.ai_panel.pending_list.size() == 0)

        # 设置对话框按钮可见（不能被内容挤扁）
        app.deiconify(); app.update()
        dlg = AISettingsDialog(app, AIConfig())
        dlg.update_idletasks(); dlg.update()
        bar_h = dlg._btn_bar.winfo_height()
        texts = []
        def walk(w):
            for ch in w.winfo_children():
                try:
                    if ch.winfo_class() == "TButton":
                        texts.append(ch.cget("text"))
                except Exception:
                    pass
                walk(ch)
        walk(dlg)
        check("设置对话框按钮条高度 >= 30", bar_h >= 30, f"{bar_h}px")
        check("保存/取消按钮存在", "保存" in texts and "取消" in texts, str(texts))
        dlg.destroy(); app.withdraw()

        # 自动执行：离线 agent → 界面同步（结果/页签）
        ex = Executor(app.project, out_dir=tempfile.mkdtemp())
        r = app.ai_panel.assistant.run_agent("设计 3 阶 2GHz 低通", app.project,
                                             app.result, executor=ex)
        app.ai_finish_agent(r)
        check("自动执行后结果已更新", app.result is not None)
        check("自动执行后电路 3 元件", len(app.project.network.components) == 3,
              str(len(app.project.network.components)))
    finally:
        app.destroy()


def main():
    srv, base = start_server()
    try:
        test_config(base)
        test_client(base)
        test_parse()
        test_actions()
        test_assistant(base)
        test_executor()
        test_agent(base)
        test_ui()
    finally:
        srv.shutdown()
    print()
    if FAIL:
        print(f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
        return 1
    print("AI 测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())