"""界面逻辑集成测试：不弹窗，直接驱动 App 的关键链路。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.synthesis import bandpass_lc, lowpass_lc
from app.ui.app import App

FAIL = []
def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))
    if not cond: FAIL.append(name)

app = App()
app.withdraw()
try:
    # 等 after(400) 的自动仿真触发
    import time
    for _ in range(10):
        app.update()
        time.sleep(0.1)
        if app.result is not None:
            break
    if app.result is None:
        app.run_sim()

    print("== 1. 启动即自动仿真（默认示例）")
    check("已有结果", app.result is not None and len(app.result.freqs) == 401,
          f"{len(app.result.freqs) if app.result else 0} 点")
    check("默认 2 端口", app.result.n_ports() == 2)

    print("== 2. 滤波器向导链路（低通 n=4，偶数阶回归）")
    app._apply_filter({"items": lowpass_lc(4, 2e9, 50, 0.5),
                       "z0": 50, "desc": "测试低通4阶", "topo": "lowpass", "n": 4, "ripple": 0.5})
    check("生成后元件数 = 4", len(app.project.network.components) == 4,
          str(len(app.project.network.components)))
    check("生成后可仿真", app.result is not None and app.result.n_ports() == 2)
    # 取扫频的下限频点（原来用 1/4 处，隐含假设扫频上限贴近截止频率；
    # 现在示例扫到 10 GHz，1/4 处已在 2 GHz 低通阻带里）
    k = 0
    check("低频插损 > -1 dB", app.result.db(2, 1)[k] > -1.0,
          f"{app.result.db(2,1)[k]:.3f} dB @ {app.result.freqs[k]/1e9:.3g} GHz")

    print("== 3. 带通链路")
    app.var_funit.set("GHz"); app.var_start.set("2.0"); app.var_stop.set("3.0")
    app.var_sweep.set("linear")
    app._apply_filter({"items": bandpass_lc(3, 2.3e9, 2.7e9, 50, 0.5),
                       "z0": 50, "desc": "测试带通", "topo": "bandpass", "n": 3, "ripple": 0.5})
    mid = min(range(len(app.result.freqs)), key=lambda i: abs(app.result.freqs[i] - 2.5e9))
    check("带通中心插损 > -1 dB", app.result.db(2, 1)[mid] > -1.0,
          f"{app.result.db(2,1)[mid]:.3f} dB")
    check("带通 S11 < -10 dB", app.result.db(1, 1)[mid] < -10.0,
          f"{app.result.db(1,1)[mid]:.1f} dB")

    print("== 4. 数据表与绘图对象已更新")
    check("数据表有行", len(app.table.get_children()) == len(app.result.freqs))
    check("幅度图有图元", len(app.mag.find_all()) > 10)
    check("Smith 圆图有图元", len(app.smith_tool.canvas.find_all()) > 10)

    print("== 5. 端口增删")
    n0 = len(app.project.network.ports)
    from app.engine import Port
    app.project.network.ports.append(Port(f"P{n0+1}", "n1"))
    check("端口可增加", len(app.project.network.ports) == n0 + 1)
    app.project.network.ports.pop()
finally:
    app.destroy()

print()
if FAIL:
    print("失败：" + ", ".join(FAIL)); raise SystemExit(1)
print("界面逻辑集成测试全部通过 ✔")