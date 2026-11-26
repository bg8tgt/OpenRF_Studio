# OpenRF Studio · AI 深度融合方案（v3.0 路线）

> 目标：让 AI 从「一个聊天框」变成「贯穿每个环节的操作员」——有技能、能动手、可复核。
> 状态：设计定稿待实施 · 2026-11-01

## 一、当前问题

- AI 只有一个聊天页签，和主界面是**两个世界**：它说的话要用户自己翻译成点击动作。
- `assistant.py` 里是 if/else 规则，能力写死在代码里，加一个能力就要改核心文件。
- 没有「AI 能做什么」的清单，模型只能猜，猜错就胡说。

## 二、核心设计：技能注册表（Skill Registry）

把 AI 的能力从「代码里的分支」变成「可插拔的技能模块」。

```
app/ai/skills/
  __init__.py        # 自动发现 + 注册表
  base.py            # Skill 基类、SkillContext、ActionResult
  build.py           # circuit.build     自然语言 → 电路拓扑
  sim.py             # sim.run           设扫描参数并跑仿真
  analyze.py         # plot.explain      解读 S 参数曲线
  match.py           # match.design      匹配网络综合（L/π/双短截线）
  optimize.py        # optimize.target   设目标并跑优化器
  report.py          # export.report     导出 CSV / 测试报告
  teach.py           # teach.smith       史密斯圆图讲解（新手模式）
```

### 每个技能是一个类

```python
class Skill:
    name = "circuit.build"          # 唯一标识
    title = "按指标生成电路"
    triggers = ["低通", "高通", "带通", "匹配", "生成电路"]
    params = {                       # 给模型看的 JSON Schema 子集
        "kind": {"type": "str", "enum": ["lowpass", "highpass", "bandpass"]},
        "fc_ghz": {"type": "float", "required": True},
        "order": {"type": "int", "default": 3},
    }
    def preview(self, ctx, **p) -> ActionResult:   # 只读：算出方案，不动界面
    def apply(self, ctx, **p) -> ActionResult:     # 用户点「应用」后才执行
```

### 三件事被严格分开

| 阶段 | 谁做 | 约束 |
|---|---|---|
| `preview` | AI 调用 | **只读**，只能读 ctx 里的状态，返回「打算做什么」的文字 + 参数 |
| 用户确认 | 人 | 界面上出现「应用」按钮，参数可改 |
| `apply` | 人点按钮后 | 只调用应用已有的公开方法，不 eval、不拼字符串 |

这条分界线是整个方案的安全底线：**模型永远不能直接改电路**，它只能提交一份提案。

## 三、贯穿每个环节（UI 触点）

| 环节 | AI 触点 | 用到的技能 |
|---|---|---|
| 电路编辑页 | 顶部「AI 生成」按钮 + 右键菜单 | `circuit.build` |
| 仿真页 | 跑完自动出现「解读这次仿真」 | `plot.explain` |
| 直角图 / 圆图 | 在频点打标记后「问 AI 这个点」 | `plot.explain` + `teach.smith` |
| 匹配设计 | 「帮我匹配到 50Ω」 | `match.design` |
| 优化页 | 目标用一句话描述 | `optimize.target` |
| 任意位置 | `Ctrl+K` 命令面板，自然语言 | 路由到所有技能 |
| 导出 | 「出一份测试报告」 | `export.report` |

## 四、模型怎么选技能（不靠它猜）

三级路由，逐级降级：

1. **关键词命中** —— 用户句子里出现 `triggers`，直接定位（离线可用、零成本）。
2. **模型选择** —— 把技能清单（name + title + params）作为工具定义发出去，让模型返回结构化 JSON：
   ```json
   {"skill": "circuit.build", "params": {"kind": "lowpass", "fc_ghz": 2.0, "order": 3}}
   ```
3. **兜底闲聊** —— 没匹配到任何技能，退回现在的普通对话。

关键：**技能清单是发给模型的唯一事实来源**。模型不再靠想象编能力，编出来的技能名会被注册表直接拒绝。

## 五、为什么这样能「形成实用助手」

- **可发现**：`registry.catalog()` 输出人可读清单，设置页能列出「这个 AI 现在会做什么」。
- **可扩展**：加能力 = 加一个文件，不改 `assistant.py`。
- **可验证**：`preview` 是纯函数，可以单测——不需要真的开窗口。
- **可离线**：关键词路由 + 本地综合算法，断网也能用（现在断网就只剩规则引擎）。

## 六、实施顺序

**P0（先让它转起来）**
1. `app/ai/skills/base.py` + `__init__.py` 注册表与自动发现
2. `circuit.build`（低通/高通/带通 LC 综合，纯参数计算）
3. `plot.explain`（读当前 sweep 结果，算出 fc/-3dB 带宽/回波损耗最小值/纹波）
4. `assistant.py` 接入三级路由；聊天里能识别并返回结构化提案
5. `tests/test_skills.py` 单测

**P1（接进界面）**
6. AI 面板的提案卡片 + 「应用」按钮接 `apply`
7. 仿真页「解读这次仿真」按钮
8. `Ctrl+K` 命令面板

**P2（补齐能力）**
9. `match.design` / `optimize.target` / `export.report` / `teach.smith`
10. 设置页「AI 能力清单」

## 七、风险与对策

- **模型乱调参数** → 每个参数有类型/枚举/范围校验，不合规直接拒绝并回显错误。
- **apply 改坏电路** → 应用前自动存快照；提供「撤销」；apply 只能调用既有公开 API。
- **推理模型慢** → 已修（max_tokens 4096 + 自动放大重试）；技能本身是本地纯计算，不走网络。
- **无网络** → 关键词路由 + 本地算法全通，只有「自然语言理解」降级。
