# 作者发布清单

当前公开示例已提供 `main.py`、本地 Ollama `llama3.1` 调用、两个完整任务输入和对应的桌面动作规则。安装和实测范围见 [README](../README.md) 与[运行检查](run-status.md)。示例启动时无需填写模型路径或创建 Python 包元数据。

下方保留论文原系统的交接清单，供作者决定是否补充其他模块或平台。公开示例的动作规则与场景为新编实现。

## 2. 需要补充的核心代码

- [ ] 模型加载、生成接口、消息格式、模型输出解析及异常处理。
- [ ] Command transformer：proxy planner 与 command sanitization 的实际实现。
- [ ] Intent obfuscator：dominant-action identifier、cover generator、chain fusion；确认是否包含论文 p.1062 的 chain extension。
- [ ] Rule-based verifier：scene graph、动作参数检查、完整 preconditions/effects、状态转移与失败反馈。
- [ ] Planner-verifier loop：失败反馈回到哪个阶段、是否重新生成、停止条件、重试上限和失败返回方式。
- [ ] 配置读取、日志、结果导出、包安装和 CLI 入口；已有脚本也可直接整理成清晰入口。
- [ ] 明确符号动作中的实体 ID 与经过指代替换的文本之间如何保持对应，避免 verifier 与导出指令失配。

## 3. 需要补充的运行资源 / 数据

| 资源 | 需要什么 | 建议位置 |
| --- | --- | --- |
| Action pool | 完整动作名称、参数及平台映射；不是只提供论文里的几个示例 | `assets/action_pool.json` |
| 动作规则 | 每个动作的前置条件、状态更新、容量/位置/容器等约束，格式以实际代码为准 | `assets/rules/` 或对应 Python 模块 |
| Scene schema | 节点/边、对象属性、agent 状态、初始场景及生成方式 | schemas 和一个最小场景文件 |
| Prompt templates | 已新增三份面向人工审查的英文模板，覆盖实体指代、物理后果和符号验证器结果。每份均有输入字段、输出格式与中性示例。论文各阶段的公开范围见清单。 | [模板清单](../prompts/README.md) |
| 类别定义 | dominant-action scoring 使用的类别与实际评分解析规则 | `assets/categories.json` |
| 最小使用样例 | 已提供两个可运行的任务包，字段与动作规则见 README | `assets/examples/task_bundle.json` |
| 模型资源 | 模型下载/获取步骤；如有改动权重，说明其获取或替代方式及授权 | 配置及说明文档；不默认将权重提交 Git |

现有 `scene.example.json` / `chain.example.json` 是为了说明拟议接口新写的中性示例，不是论文原始资源。需要与你的真实 schema 对齐后才能用于运行。

## 4. 可选平台接入

核心实现可以先独立发布。只有在公开相应适配器时，才需要补齐下面的接入材料。

**VirtualHome / ProgPrompt**

- [ ] 实际源码来源及 commit、Unity/VirtualHome build 与受支持系统。
- [ ] 仿真器启动命令、场景文件获取/加载、连接参数、对象 ID 与动作映射。
- [ ] ProgPrompt 目标系统的模板、目标模型配置与 API/响应解析代码。
- [ ] 从导出 action chain 到目标系统输入，再到 simulator API 的完整转换路径。

**xArm**

- [ ] xArm 6 的 SDK/固件版本、动作封装和坐标约定。
- [ ] 两台 RGB-D 相机的型号、SDK 和标定输入格式。
- [ ] 论文中提供给模型的对象坐标提示来自哪里，是否依赖手工输入，及其坐标变换代码。
- [ ] 设备连接配置模板和适配器启动步骤；个人设备地址及本地标定数据放在本地配置中。

## 5. 待确认的参数与发布决定

- [ ] 实际模型生成参数：temperature、top-p、max tokens、seed（若使用）、超时与后端重试策略。不要将论文参数敏感性分析中的候选值当作默认值。
- [ ] planner-verifier 最大轮数、解析失败处理、无法修复时的返回值。
- [ ] 哪些模板/数据/代码已做公开发布整理；如有省略，明确省略范围及其影响，不将受限版本写成完整实现。
- [ ] 代码许可证由作者选择；论文 CC BY 4.0 不等于源码许可证。
- [ ] 补齐源码后，实际验证安装命令、一个中性使用样例和输出字段，再将 README 状态更新为可运行。

## 6. 最简交接方式

先提供现有源码文件夹、一份可用配置、当前环境依赖导出，以及一个中性最小输入即可开始整理。确认核心 implementation 可运行后，再决定是否同时公开 VirtualHome 和 xArm 适配器。无需为此先整理实验材料。
