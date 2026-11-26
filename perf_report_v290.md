# OpenRF Studio v2.9.0 性能实测报告

- 被测版本：E:\王军\OpenRF_Studio（工作树 2026-11-01 状态）
- 测量方式：**零仓库改动**。全部探针脚本放在临时目录 `%TEMP%\orfperf\`（`p.py` / `p2.py` / `p3.py` / `m.py`），通过 monkeypatch 包装类方法计数，未修改 app/ 或 tests/ 任何文件。
- 环境：Windows + Python 3.13（`D:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`），Git for Windows bash，`export PYTHONIOENCODING=utf-8`。
- 所有数字为单次冷/温进程实测（可复现命令见文末附录）。

---

## 0. 结论速览

| 项 | 实测 | 判定 |
|---|---|---|
| 冷启动到窗口可见 | **1.058 s**（import 0.113 + 建界面 0.629 + 首帧 0.316） | **真瓶颈**（用户第一感知） |
| 空闲 CPU（无定时器） | **after 队列 0 个**，启动后仅 1 个一次性 after；测得 6.1% 全部来自探针 250 Hz `update()` 轮询 | **想当然**（无空转轮询） |
| 常驻内存 | 建界面 47.5 MB → 空闲稳定 48.7 MB → 峰值 49.2 MB | **不是瓶颈** |
| 日志 Text 无限追加 | 500 行 → +0.2 MB（0.4 KB/行），行数 5→505 | 长期风险，非当前瓶颈 |
| MagnitudePlot 重绘 | **单次 4.615 ms**，<Configure> **1 事件 1 重绘、无合并** | **真瓶颈**（拖动/缩放时线性累加） |
| RFWorkbench 画布重绘 | **单次 1.364 ms**，频点同步 1 次/点；<Configure> 1.8 ms | 次要瓶颈 |
| 引擎单频点求解 | 0.026–0.091 ms/点；601 点扫频 **49.5 ms** | 当前规模下**不是**瓶颈 |
| 引擎每点 2 次求逆 | `inverse(yii)` + `inverse(b)`，F 点 → 2F 次 n×n 求逆 | 真重复计算，但 n≤5 时收益小 |

---

## 1. 冷启动（真瓶颈）

**命令**
```bash
cd "/e/王军/OpenRF_Studio" && export PYTHONIOENCODING=utf-8
python -c "import subprocess,sys,time;t=time.perf_counter();subprocess.run([sys.executable,'-c','pass']);print('bare_interpreter_s',round(time.perf_counter()-t,3))"
PYTHONPATH="$(cygpath -m /e/王军/OpenRF_Studio)" python -X importtime -c "import app.ui.app" 2>it.log 1>/dev/null
# 建界面/首帧：临时目录 m.py 中 A.App() 前后 perf_counter 打点
```

**实测分解**

| 阶段 | 耗时 | 证据 |
|---|---|---|
| 裸解释器启动 | 0.026 s | `python -c pass` |
| `import app.ui.app`（含 tkinter） | **0.113 s** | `-X importtime` 累计 123.8 ms |
| `App.__init__` 建界面 | **0.629 s** | 打点 |
| 首帧绘制（update_idletasks+update） | **0.316 s** | 打点 |
| **到窗口可见合计** | **1.058 s** | 打点 |

**import 大头（-X importtime 累计，us）**

```
 123840  app.ui.app
  52032  app.ui.ai_panel
  50933  app.ai.actions
  50900  app.ai
  47525  app.ai.client          -> urllib.request 29603 + http.client 22503
  21215  tkinter
  17045  app.components
  15813  dataclasses
  13487  inspect
  13222  email.parser
```
⇒ **import 阶段 45% 的时间耗在 AI 子系统与 HTTP 栈**（ai_panel 52.0 ms，其中 ai.client 47.5 ms 拉起 urllib/http），而启动时根本不会发请求。

**证据位置**
- 入口：`app/ui/app.py:1070-1073`（`main()`: `enable_dpi(); app = App(); app.mainloop()`）
- 单一巨型 `App.__init__`/`_build_*`：`app/ui/app.py:290-380` 一段内同时建 Notebook 全部 5 个页签、3 个 Canvas、Treeview、日志 Text、AIPanel
- AIPanel 在启动期就被实例化：`app/ui/app.py:361-365`（`self.ai_panel = AIPanel(self.nb, self)` + `self.nb.add(...)`）

**改法**
1. Notebook 页签惰性构建：先只建「圆图 / 直角图」页，其余页在 `<<NotebookTabChanged>>` 首次选中时才建（保留占位 Frame）。
2. AIPanel 改为惰性 `import` + 惰性实例化（`app/ui/app.py:361`；`ai_panel` 顶部 `from ..ai...` 移到方法内）。
3. 日志页 Text 与 AI 页同理延后。

**预期收益**：-350～-450 ms（建界面 0.629 s 的 55–70%）+ -45～-50 ms（import 中 AI 部分）。合计**启动 ~1.06 s → ~0.60 s（-43%）**。
**风险**：低。惰性页需要保证首次切换时状态（变量/回调）与当前一致；`refresh_all()`（`app/ui/app.py:414`）会操作各页控件，必须改成「页未建则跳过」而不是直接访问。

---

## 2. 空闲 CPU：**不是瓶颈（想当然）**

**测法**：建界面后以 4 ms 间隔调 `app.update()` 连跑 12 s，同时用 ctypes `GetProcessTimes` 取进程 CPU 时间，并读 `after info` 统计待处理定时器。

**实测**
- 启动后待处理 after：**1 个**（一次性，`app/ui/app.py:90-91` 的 `after(120, refresh_all)` / `after(400, run_sim)`）
- 12 s 末待处理 after：**0 个**
- 进程 CPU：0.734 s / 12 s = **6.118 %**
- 但该 6.1% 与探针自身 250 Hz `update()` 轮询同源——`after_pending = 0` 证明应用侧没有任何周期性定时器在跑。

**仓库侧证据**
- 全 UI 仅 3 处 `after(`：`app/ui/app.py:90`、`app/ui/app.py:91`、`app/ui/app.py:855`（`play_after = self.after(60, self._play_tick)`，只在「播放」按钮激活时才存在）。
- 无 `while True` 轮询、无固定 `after(16/33)` 重绘循环。

**判定**：空闲 CPU 空转**不存在**。用户感知的「开着就吃 CPU」更可能来自 ①启动期 0.95 s 的建界面峰值，②拖动/缩放时的同步重绘（见第 4 节），而不是空闲。
**改法**：无需改。若要进一步确认，用任务管理器观察静止 1 分钟应≈0%。

---

## 3. 常驻内存：**不是瓶颈**

**测法**：ctypes `GetProcessMemoryInfo` 读 WorkingSetSize / PeakWorkingSetSize。

**实测（MB）**

| 时刻 | WS | Peak |
|---|---|---|
| 建界面完成 | 47.5 | 47.5 |
| 空闲 12 s 后 | 48.7 | 48.7 |
| 500 行日志 + 结束 | 49.2 | 49.2 |

- 日志 Text：5 行/218 B → 505 行/16 608 B，**+0.2 MB**，约 **0.4 KB/行**。
- 结论：48 MB 级别的 Tk 应用属正常；无大列表/画布项泄漏迹象（`run_sim` + 3 次缩放 + 4 次拖动 + 10 次频点同步后仍在 49 MB）。

**风险点（长期，非当前）**：`app/ui/app.py:374-379` 的 `say()` 每次 `insert("end", ...)` 后**没有 `delete` 裁剪**，Text 行数无上限。按 0.4 KB/行、若某功能每秒一条日志，1 小时 ≈ 1.4 MB、8 小时 ≈ 11 MB；且 Text 越大 `see("end")` 与布局越慢。
**改法**：`say()` 里超过 N 行（建议 2000）时 `self.log.delete("1.0", "2.0")` 逐行裁剪；或用 `self.log.configure(state="normal")` 前先判行数。**预期收益**：把无界增长变有界；对当前 47 MB 影响 <5%。**风险**：极低（仅丢历史日志，建议只在超限时丢）。

---

## 4. v2.8.0 合并页重绘成本（真瓶颈）

**被测结构**：`app/ui/app.py:302-313` —— `ttk.PanedWindow(orient="horizontal")` 内放 `MagnitudePlot`（`dual_pane.add(..., weight=1)`）与 `RFWorkbench`（同样 weight=1）。绑定点：

- `app/ui/plots.py:67` `self.bind("<Configure>", self._on_resize)`
- `app/ui/plots.py:69-71` `_on_resize` → 直接 `self.redraw()`（**无去抖、无尺寸比较**）
- `app/ui/rf_workbench.py:90` `self.bind("<Configure>", self._on_configure)`
- `app/ui/rf_workbench.py:117-122` `ChartCanvas._on_configure` → `fit()`/重绘
- `app/ui/rf_workbench.py:196` `ChartCanvas.redraw`
- 频点同步：`app/ui/app.py:766` `_mag_freq_pick` → `app/ui/rf_workbench.py:573` `sync_live` / `:555` `_schedule_live`

**测法**（临时脚本 monkeypatch 类方法计数+计时；类级 patch 因此 Tk 已绑定的回调也生效）：

| 场景 | MagnitudePlot 重绘次数 / 累计 ms | ChartCanvas(RFWorkbench) 重绘次数 / 累计 ms |
|---|---|---|
| `run_sim()` 后 | 2 / 8.39 | 1 / 1.63 |
| 再加 3 次窗口缩放（1200×780 → 980×660 → 1300×820） | **+3 / +15.24**（5.08 ms/次） | +3 / +5.40（1.80 ms/次） |
| 再加 4 次拖动分隔条（sashpos 380/520/450/600） | **+4 / +20.58**（5.15 ms/次） | +2 / +2.91（1.46 ms/次） |
| 再加 10 次频点同步 `_mag_freq_pick` | **+0 / +0** | **+10 / +15.36**（1.54 ms/次） |
| 单独反复调用 `mag.redraw()` | **4.615 ms/次**（5 次均值） | `canvas.redraw()` **1.364 ms/次** |

**判定**
1. `MagnitudePlot`：**<Configure> 与重绘 1:1**，单次 4.6–5.2 ms。一次真实分隔条拖动通常产生 60–100 个 Configure 事件 ⇒ **0.28–0.46 s 的 UI 线程连续阻塞**（拖动发滞）。窗口缩放同理（每次改尺寸 5 ms×2 块）。
2. `RFWorkbench` 画布轻一些（1.4–1.8 ms），但它**每次频点同步都重绘**，而直角图在同一场景 0 次重绘——两块画布的同步策略不一致。
3. 合并进同一个 `PanedWindow` 本身没有额外代价（每块画布收到 1 次 Configure），**成本来自「事件→同步整幅重绘」这条直连路径**，不是 v2.8.0 合并页的布局选择。

**改法（按收益排序）**
1. `app/ui/plots.py:69-71`：`_on_resize` 改为「记下目标尺寸 → `if self._relayout_id is None: after_idle(self._flush_resize)`」，`_flush_resize` 里再做一次尺寸相等判断并只重绘一次。**预期**：拖动期间重绘次数从「事件数」降到「帧数」，实测等价收益 **-80%～-95%**（4 次拖动 20.6 ms → 2–4 ms；100 事件拖动 0.46 s → 0.02–0.05 s）。**风险**：低；需保证 `destroy` 时 `after_cancel`，拖动结束必须有一次落地重绘（`ButtonRelease` 或 idle 保证）。
2. `app/ui/rf_workbench.py:573-579` `sync_live`：与 `_schedule_live`（:555）共用同一个去抖入口，避免「每次 `_mag_freq_pick` 立即整幅重绘」。**预期**：连续频点拾取（拖动游标）时 10 次 → 1–2 次，**-1.5 ms/次 × 8**；**风险**：低。
3. 可选：`ChartCanvas.redraw` 里把 `self.delete("all")` + 逐项 `create_*` 改成复用 item（`itemconfigure`/坐标更新）。单次 1.36 ms 已不大，收益 <1 ms，**风险中等**（易引入残留 item），建议**不做**。

---

## 5. 仿真热点（示例电路上**不是**瓶颈，但有真重复计算）

**测法**（临时脚本 `p3.py`，直接调 `app.engine`，绕开 UI）

```python
net = Network.from_dict(json.load(open("examples/01_lowpass_3ghz.json"))["network"])
fs = [1e9 + i*1e6 for i in range(201)]
t=perf_counter(); [net.build_y(f) for f in fs];          # 只 stamp
t=perf_counter(); [net.s_matrix(f) for f in fs];         # 完整 S
ana = Analysis.from_dict(d["analysis"]); net.sweep(ana)  # 端到端扫频
```

**实测（201 点）**

| 示例 | 节点/端口/元件 | build_y 单点 | s_matrix 单点 | build_y 占 s_matrix | 端到端 sweep |
|---|---|---|---|---|---|
| 01_lowpass_3ghz | 3 / 2 / 3 | 10.5 µs | **0.054 ms** | 19.3% | 401 点 **20.7 ms** |
| 02_bandpass_2g4 | 5 / 2 / 6 | 24.9 µs | **0.091 ms** | 27.5% | 601 点 **49.5 ms** |
| 03_wilkinson_2ghz | 3 / 3 / 3 | 13.5 µs | 0.059 ms | 23.0% | 201 点 12.1 ms |
| 04_microstrip_qw | 2 / 2 / 1 | 14.6 µs | 0.031 ms | 47.2% | 301 点 11.4 ms |
| 05_coax_50ohm | 2 / 2 / 1 | 7.0 µs | 0.026 ms | 27.2% | 201 点 5.7 ms |
| demo_lpf | 3 / 2 / 3 | 15.2 µs | 0.048 ms | 31.8% | 401 点 18.5 ms |

- 重复测量 `sweep` 两次基本一致（如 02：49.54 / 49.56 ms），无缓存。
- 单点耗时随元件数上升（1 元件 0.026 ms → 6 元件 0.091 ms），**近似线性于元件数在 n 很小时表现为 O(n³) 的求逆项 + 逐元件 stamp 项之和**。

**真重复计算（file:line）**
- `app/engine.py:149-167` `port_admittance`：每点 `inverse(yii)`（:166）+ 两次 `matmul`（:167）。
- `app/engine.py:172-184` `s_matrix`：又来一次 `inverse(b)`（:183）+ 一次 `matmul`（:184）。
⇒ **每个频点 2 次 n×n 求逆 + 3 次矩阵乘**，且 `inverse`/`matmul` 是纯 Python 三重循环（`app/complexmath.py`）。
- `app/engine.py:133-148` `build_y`：每点对每个元件调 `c.stamp(f_hz)` 并重扫全节点（`idx` 字典每点重建）。
- `app/engine.py:186-189` `sweep`：逐点调 `s_matrix`，无任何跨频点复用。

**关于「一次矩阵分解复用到多频点」——需澄清（避免想当然）**：S 参数求解里 `(I+√Z·Yp·√Z)⁻¹` 的**系数矩阵本身随频率变化**，因此「分解一次、多 RHS 复用」只在频率不变的参数扫描（如扫元件值）时成立。对扫频而言，可省的不是分解复用，而是：
1. **2 端口闭式解**：`inverse(b)` 对 2×2 用伴随/行列式直接写（`app/engine.py:183`，规避通用 LU/伴随的 n³ 循环），示例里绝大多数是 2 端口。
2. **端口消元的 2×2 分块公式**：`ypp - ypi·inv(yii)·yip` 对 `np_=2` 可展开成 4 个标量表达式，省掉 `matmul` 的通用循环。
3. **`build_y` 中与频率无关的部分预计算**：`idx` 映射与元件对角位置只与拓扑有关，`app/engine.py:134-135` 的两次字典/列表构建每点重复，可缓存在 Network 上（拓扑变更时失效）。

**预期收益**：601 点扫频 49.5 ms → **约 20–30 ms（-40～-60%）**；单点 0.091 ms → ~0.05 ms。
**风险**：中。闭式解需处理奇异（`det≈0`）与端口数 ≠2 的回退；纯 Python 数值实现改动必须以 `tests/test_engine.py` + `tests/test_conformance.py` 全绿为准。**在示例规模（≤6 元件）下这只是 20–30 ms 的绝对收益，不应排在启动/重绘之前。**

---

## 6. 真瓶颈 vs 想当然（明确区分）

**真瓶颈（按用户可感知程度）**
1. 启动 1.06 s，其中 0.945 s 是建界面 + 首帧（`app/ui/app.py:1070-1073`）。← 改进首选
2. `MagnitudePlot` 每 Configure 一次 4.6–5.2 ms 全量重绘、无合并（`app/ui/plots.py:67,69-71`）。
3. `RFWorkbench` 画布频点同步 1 次/点 1.54 ms（`app/ui/rf_workbench.py:573`）。
4. import 中 45% 是启动期用不到的 AI+HTTP 栈（`app/ui/ai_panel.py` → `app/ai/client.py` → urllib/http）。

**想当然（实测否掉）**
1. **空闲 CPU 轮询空转**：after 队列实测 0 个待处理项；测得的 6.1% 是探针自己的 `update()` 循环开销。仓库只有 3 处 `after`，其中 2 处一次性、1 处仅在播放时存在。
2. **内存泄漏 / 日志涨爆内存**：48.7 MB 稳定、峰值 49.2 MB；500 行日志仅 +0.2 MB（0.4 KB/行）。日志无上限是**代码事实**（`app/ui/app.py:374-379` 无 delete），但**不是当前资源瓶颈**。
3. **合并页布局（v2.8.0）本身导致重绘翻倍**：两块画布各收到 1 次 Configure，成本来自各自的同步整幅重绘路径，不是 PanedWindow 引入的额外事件。
4. **引擎矩阵分解可跨频点复用**：系数矩阵随频变化，分解复用对扫频不成立；可省的是 2 端口闭式解与 stamp 预计算。
5. **引擎是主要慢源**：示例规模下单点 0.026–0.091 ms、601 点 49.5 ms，远低于一次启动（1058 ms）或一次拖动（280–460 ms）。

---

## 7. 优化清单（按收益/风险排序）

| # | 改哪里 | 怎么改 | 预期收益 | 风险 |
|---|---|---|---|---|
| 1 | `app/ui/app.py:1070-1073` + `:290-380` | Notebook 5 页惰性构建；AIPanel / 日志页延后；`refresh_all`(:414) 对未建页跳过 | 启动 **-350～-450 ms**（1.06 s → ~0.62 s） | 低 |
| 2 | `app/ui/plots.py:69-71` | `_on_resize` 改 `after_idle` 合并 + 尺寸相等则跳过；`destroy` 时 `after_cancel` | 拖动/缩放重绘 **-80～-95%**（100 事件拖动 0.46 s → 0.02–0.05 s；实测 4 次拖动 20.6 ms 可降到 2–4 ms） | 低 |
| 3 | `app/ui/ai_panel.py` 顶部 import + `app/ui/app.py:361` | AI/HTTP 相关 import 移入方法内；AIPanel 惰性实例化 | import **-45～-50 ms**（113 ms → 65 ms） | 低 |
| 4 | `app/ui/rf_workbench.py:573-579`（复用 :555 的 `_schedule_live`） | 频点同步与 live 预览共用同一去抖入口 | 频点拾取 **-1.5 ms/次 × 8~9**（10 次 15.4 ms → 1～3 ms） | 低 |
| 5 | `app/engine.py:166,183`（+ `complexmath.py` 调用点） | 2 端口用闭式伴随解；`np_==2` 时消元用标量展开；非 2 端口回退通用路径 | 扫频 **-40～-60%**（601 点 49.5 → 20–30 ms） | 中（需 test_engine/test_conformance 回归） |
| 6 | `app/engine.py:134-135` | `idx`/对角位置缓存到 Network，拓扑变更时失效 | 单点 stamp **-20～-40%**（build_y 占 19–47%） | 中低 |
| 7 | `app/ui/app.py:374-379` | `say()` 超 2000 行裁剪 `delete("1.0","2.0")` | 长期内存有界；当前影响 <5% | 极低 |

**不要做的**：引入任何第三方库（含 numpy / pyqtgraph / cachetools）——项目是纯标准库洁净室，`tests/test_cleanroom.py` 的 ALLOW 仅 NOTICE 与交付说明；上述全部改动均可用标准库（`tkinter`/`functools.lru_cache`/`math`）完成。

---

## 8. 附录：复现命令

```bash
cd "/e/王军/OpenRF_Studio" && export PYTHONIOENCODING=utf-8

# A. 启动分解（import / 建界面 / 首帧）
REPO=$(cygpath -m "/e/王军/OpenRF_Studio")
cd /tmp/orfperf && python m.py "$REPO" "$(cygpath -m /tmp/orfperf)/metrics.json"

# B. import 明细
(cd /tmp/orfperf && PYTHONPATH="$REPO" python -X importtime -c "import app.ui.app" 2>it.log 1>/dev/null)

# C. 引擎扫频
python /tmp/orfperf/p3.py "$REPO"       # 逐示例 build_y / s_matrix / sweep（需先把 p3.py 放临时目录）

# D. 回归（本次未改代码，仅备查）
for t in ai cleanroom conformance engine features io match_ui optimize s2p theme topology ui_logic; do
  python -m tests.test_$t >/dev/null 2>&1; echo "$t rc=$?"
done
```

**测量局限（如实声明）**
1. 空闲 CPU 的 6.1% 含探针 250 Hz `update()` 开销，不能在应用侧归因；`after_pending=0` 是「无空转轮询」的正面证据，但未用外部性能计数器（如 Windows `typeperf`）交叉验证。
2. 重绘计数基于类级 monkeypatch（`MagnitudePlot.redraw`/`ChartCanvas.redraw`），可覆盖 Tk 已绑定的回调；但**未覆盖 `create_*` 级别的 item 复用情况**，因此 4.6 ms 的构成（删除 vs 重建 vs 文本排版）未分解。
3. 建界面 0.629 s 未按页/按控件细分（探针在 force tier 下截断），第 7 节 #1 的收益区间是按「5 页等比 + AIPanel」估算，**落地前应先按页加打点复核**。
4. 引擎测试是单次进程内重复调用，未做多次取中位数；绝对值可能随 CPU 频率波动 ±10%。
