# 合规与来源说明（NOTICE）

## 1. 独立实现声明

本项目（OpenRF Studio 射频工作台）为**独立实现**：

* 未复制、未链接任何商业 EDA 软件的二进制、源代码、资源、器件库或私有文件格式；
* 未使用任何破解补丁、许可证文件或替换系统库；
* 工程文件采用自定义 JSON 结构，数据交换只使用公开标准（Touchstone 1.0）。

## 2. 公式与标准出处（公开资料）

| 内容 | 出处 |
|---|---|
| 传输线 Y 参数、S 参数与 Z/Y 关系、二端口稳定性因子 | Pozar, *Microwave Engineering*, 4th ed., §4.3–4.4、§11 |
| 低通原型 g 值与切比雪夫/巴特沃斯综合 | Pozar §8.3；Matthaei, Young & Jones, *Microwave Filters, Impedance-Matching Networks, and Coupling Structures*, Ch.4 |
| 低通→带通变换 | Pozar §8.4 |
| 微带线准静态 Z0/εeff、色散修正 | Hammerstad & Jensen, "Accurate Models for Microstrip Computer-Aided Design", MTT-S 1980 |
| 带状线闭式近似 | IPC-2141（行业标准） |
| 同轴 Z0、群时延 | 同轴 TEM 解析式；τ = l·√εr / c |
| LC 谐振、L 型匹配网络、反射系数与阻抗 | 电路基础教材（串/并谐振、Q 值、Γ=(Z−Z0)/(Z+Z0)） |
| Touchstone 文件格式 | Touchstone File Format Specification v1.0（公开标准） |
| 基板预设（FR-4 / RO4350B / RO4003C / 氧化铝） | 各厂商公开数据手册的典型值 |

## 2.1 AI 辅助功能的数据说明

* 模型端点、模型名与密钥由用户自行填写；密钥仅保存在本机用户配置目录，不上传到任何第三方；
* 软件不含遥测、不含代理转发；只有用户点击「发送」时才向你配置的端点发起请求；
* 请求内容为当前电路摘要与提问，不含密钥；使用公开模型时请自行确认其数据条款，
  涉密设计建议使用本地模型（Ollama / LM Studio / vLLM）；
* 未配置模型时全部计算在本机完成（本地规则引擎 + 电路引擎）；
* AI 自动执行只修改本软件自己的工程与文件，不下载、不执行外部代码，不改系统设置。

## 3. 许可

代码以 **MIT License** 发布：可商用、可修改、可再分发，保留版权声明即可。

```
Copyright (c) 2026 OpenRF Studio contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
```

## 4. 免责

仿真结果为**准静态/集总近似**，不含全波效应、封装寄生、版图耦合与工艺涨落。
用于教学、方案预研与快速估算；量产前请用全波仿真与实测验证。作者不对因使用本软件造成的任何损失负责。

## 5. 授权引用说明

著作权人已确认：本项目功能设计所参考的软件（含圆图/匹配/优化相关工具）
均为其自有软件，并授权本项目参考其功能与行为。

* 参考范围：功能清单、交互行为、参数口径；
* 本项目实现为独立编写，未复制第三方源码；
* 相关模块注释标注“功能参考：著作权人自有软件（经授权）”；
* 如后续提供可合法使用的源码，将在 NOTICE 与文件头补充版权与许可信息。

## 6. 反编译参考记录

应著作权人要求，使用本机 dotnet 8 + ilspycmd 对自有 .NET 程序做了反编译参考
（产物保存在项目外的 _third_party_reference/decompiled_smith41，不随软件分发）。
仅用于提取功能清单与算法口径（元件类型、RLC 谐振、Q 圆、读数定义），
本项目代码为独立重写，未复制其源码；对应功能在文件头标注“功能参考（经授权）”。
