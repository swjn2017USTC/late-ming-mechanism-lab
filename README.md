# Late Ming Mechanism Lab

一个研究 1625–1644 年陕西—河南危机的历史机制实验室。项目使用可审计的多层 agent-based model
（ABM），讨论家庭生计、土地与债务、粮食市场、地方精英、财政汲取、赈济、军饷、迁徙、逃兵和
武装集团如何相互作用。

> **Simulation is an argument, not evidence.**
>
> 模拟是一种可检查的论证，不是历史证据。这里的结论描述“这个模型在这些输入、规则和参数下会
> 发生什么”，不能直接改写成“历史上就是这样”。

当前状态：**V2.1 research closure**。六张机制卡已经从 artifacts 重算并封存；9 个跨阶段科学门中
6 个通过，校准、敏感性和 runtime policy 仍未通过，因此项目没有创建 `v0.2.0-rc1`。

## 这个项目在研究什么

晚明危机不能用一个“灾荒导致崩溃”的单变量故事解释。歉收能否转化成系统性失稳，取决于许多中间
环节：农户还能否获得粮食和信贷，税基是否继续被抽取，地方财政有没有赈济和军费空间，人口能否
迁移，军队是否因欠饷而流失，以及分散武装是否会合并为更大的组织。

本项目把这些环节写成明确的状态转移，并用反事实实验追问：

- 财政越用力，实收是否可能反而下降？
- 冲击本身足以造成危机，还是迁徙、信贷和治理条件决定冲击能否穿过系统？
- 军费欠款是否会形成只增不减的棘轮？
- 精英信贷是在危机中维持生产，还是会通过违约和没收加速土地集中？
- 分散武装的集中来自合并机制，还是仅仅来自其他集团消失？
- 饥荒死亡在现有史料下能否被定量识别？

目标不是复刻“明朝灭亡”，也不是计算一个“灭亡概率”。产物是六张带有适用条件、反例、证伪标准
和不确定性的机制卡。

## 方法

### 1. 多层模型

```text
宏观层        气候输入 / 中央财政军事压力
中观层        县政府 / 军队 / 市场 / 精英 / 武装集团
地方社会层    县域 / 市场 / 信贷 / 粮食库存
微观层        加权家庭队列 / 商人 / 士兵
```

模型按月运行，共 240 个 tick。家庭以“加权队列”表示，不假装拥有逐户史料。贸易、迁徙和军事移动
使用三张不同网络；tick order 明确、版本化并由测试约束。每次状态变化都进入 append-only event log，
包括触发条件、规则、地区、输入和结果。

### 2. 历史核心与证据分级

V2 historical core 包含陕西、河南 12 个县治节点，覆盖 1625–1644 年，共 240 个 node-years：

- 184 个 node-years 有气候记录，覆盖率 **76.7%**；
- 56 个 node-years 没有记录并显式记为未覆盖；
- 贸易、迁徙、军事网络分别建模；为保持连通而加入的 connector 会标为假设，不伪装成史实；
- 空间身份和线路来自 CHGIS 派生选择，气候输入来自 REACHES 聚合记录；原始受限数据不进入 Git。

证据按 A/B/C/D/S 分级。`S` 表示模型假设。参数值只有在参数卡声明范围时才允许进入校准或敏感性
设计；来源、claim、参数/规则、运行、统计量和机制卡之间保留可解析 lineage。

### 3. 实验与验证

- **结构干预**：为关键机制构造 positive/negative control 和 no-op detector。
- **阈值稳健性**：冻结 8 条治理 reading lines，枚举 50,625 个阈值组合。
- **校准与留出**：校准、hold-out、extrapolation 窗口在代码中隔离；未收敛 posterior 不允许打开
  reserved windows。
- **敏感性**：使用 Morris、Sobol 和 PAWN；不稳定结果保留原值，不发布定量重要性排名。
- **可复现性**：run、config、code、data、artifact 和报告以 digest 绑定；失败任务不被插值。
- **LLM 边界**：runtime LLM 只允许提出受限制度动作，不能决定收成、价格、死亡、迁徙、战斗等
  物理或经济状态；默认关闭，离线测试不需要 API key。

## 得到了什么结果

以下数字是模型结果，不是历史事实。完整中文卡片位于
[`docs/mechanisms/v2_1/zh/`](docs/mechanisms/v2_1/zh/)。

| 机制 | V2.1 状态 | 人能读懂的结论 |
| --- | --- | --- |
| M001 财政汲取倒转 | `CONDITIONAL` | 倒转随征收政策变化：递增汲取的两个价格结构都出现倒转，固定征收的两个格都不出现。模型把原因更多归到政策反馈，而不是价格规则。四个格各只运行一次。 |
| M002 危机闸门 | `CONDITIONAL` | 在 historical core 中，基线税基收缩为 0.064，打开迁徙/危机 gate 后为 0.993，配对差 **+0.929**。连续效应很大，但“是否已经崩溃”的二值结论依赖阈值：默认 reading line 下只在 46.1% 的阈值组合中成立。 |
| M003 财政—军事棘轮 | `REJECTED` | “欠饷永远只增不减”的强命题不成立。结算、豁免和恢复后追缴都能使欠款下降。这里拒绝的是强单调命题，不是否认财政与军事之间存在反馈。 |
| M004 精英中介分化 | `WEAK` | 没收支确实发生：51 次 foreclosure 转移约 13,064 亩土地；但它相对关闭信贷只多造成 **0.0081** 的税基收缩，低于预注册的 0.02 最小实质效应，所以仍不足以支持“明显分化”。 |
| M005 武装整并 | `SUPPORTED` | 这是最清楚的模型机制。合并门槛拉到最高时没有合并；门槛降为零时约 4,094 名兵力经过合并链，最大集团占比升到 0.341。合并规则确实对集中产生作用。 |
| M006 饥荒死亡 | `UNIDENTIFIED` | 模型测到持续粮食短缺，但证据登记册没有县级死亡率或 unmet-need series 可以约束死亡规则。项目因此拒绝凭空加入一个死亡率。 |

六张卡在 V2.1 中都没有改变状态。V2.1 的作用是补完 M002、M004 的决定性对照，并更正样本语义：
P05 所谓“四个 seed”在每个 arm 内产生同一个 simulation digest，事件日志也没有 RNG draw，因此它们
是同一确定性轨迹的重复执行，不是四个独立过程样本。

## 科学验收状态

| Gate | 状态 | 含义 |
| --- | --- | --- |
| Data | 通过 | 正式输入有来源、版本、rights 和 hash，缺失与 connector 显式可见。 |
| Outcome | 通过 | 9 个 primary outcomes、4 个窗口和阈值带已冻结。 |
| Calibration | **未通过** | posterior location 移动 0.449 prior range，超过 0.1 门槛；acceptance 为 1.000。 |
| Sensitivity | **未通过** | Morris top-4 bootstrap agreement 为 0.00/0.01；Sobol S1 最大移动为前一级的 12.07 倍。 |
| Intervention | 通过 | 干预有 configuration diff；no-op/ablation 可检测。 |
| Hold-out | 通过 | 四个 V1 hold-out 失败均保留并分类，reserved windows 仍被隔离。 |
| Policy | **未通过** | runtime arm 在 historical core 上作出 0 次模型决策，只能称 pilot。 |
| Provenance | 通过 | 六张卡的 source → statistic → card 链可解析。 |
| Release | 通过 | bundle 绑定 code、lock、artifacts、reports 和翻译版本。 |

这意味着项目可以作为透明、可复现的研究原型使用，但不能被描述成已经校准并验证的晚明区域模型。

## 结论

模型给出的主要解释不是“灾荒自动导致崩溃”，而是：冲击进入社会系统后，会被财政政策、迁移条件、
信贷关系、军费清理和武装组织规则放大、吸收或改道。其中最可靠的模型内部结论是武装合并确实能够
制造集中；财政汲取倒转和危机闸门都依赖制度条件；精英没收分支存在但效应很小；单调欠饷棘轮被
反例否定；饥荒死亡仍缺少可识别的数据。

没有通过的校准和敏感性门同样是结果：继续增加粒子或扩大地理范围不会自动解决观测目标缺乏辨识力
的问题。项目在 V2.1 封存，后续工作应从新数据和新问题出发，而不是继续调参使留出窗口变绿。

## 快速开始

要求：Python 3.12、[`uv`](https://docs.astral.sh/uv/)。默认流程完全离线，不需要 API key。

```bash
git clone https://github.com/swjn2017USTC/late-ming-mechanism-lab.git
cd late-ming-mechanism-lab
uv sync --frozen

# 检查 Python、lock、artifacts 和 secret boundary
uv run late-ming-lab doctor

# 运行可复现的演示场景
uv run late-ming-lab run --scenario data/scenarios/demo.yaml

# 运行 12 节点 historical core
uv run late-ming-lab run --scenario data/scenarios/historical-core-v1.yaml

# 离线测试；默认排除 live_ustc
uv run pytest
```

常用命令：

| 命令 | 用途 |
| --- | --- |
| `late-ming-lab run` | 运行一次模型并保存 artifacts |
| `late-ming-lab analyze` | 读取已有 run/batch 并生成统计 |
| `late-ming-lab experiment` | 运行已登记的实验 family |
| `late-ming-lab protocol` | 查看冻结协议和阈值稳健性 |
| `late-ming-lab replay` | 使用 fixture 离线重放制度决策 |
| `late-ming-lab doctor` | 检查环境、lock、artifacts 和 secret boundary |
| `late-ming-lab bench` | 运行 benchmark |
| `late-ming-lab batch` | 规划、运行和合并批任务 |
| `late-ming-lab ui` | 本地浏览 artifacts；UI 不运行模型 |

## 复核 V2.1

封存报告和限制：

- [`docs/v2_1/closure-report.md`](docs/v2_1/closure-report.md)
- [`docs/v2_1/limitations.md`](docs/v2_1/limitations.md)
- [`docs/v2_1/handoff.md`](docs/v2_1/handoff.md)
- [`docs/v2_1/release-bundle.json`](docs/v2_1/release-bundle.json)

验证冻结区和 V2.1 生成器：

```bash
uv run python -m late_ming_lab.release verify
uv run pytest -q \
  tests/unit/test_v2_1_closure.py \
  tests/unit/test_v2_1_replicate.py \
  tests/unit/test_v2_release.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

完整离线测试在 V2-P09 记录为 1007 passed、2 个 live tests deselected；V2.1 又对新增 accessor、
contrast、translation 和 bundle 做了窄测试。具体命令与真实输出保存在 `docs/phase-reports/`。

## 数据与许可

代码和原创文档使用 MIT License。这个许可证**不替第三方数据授权**。

- `data/raw/private/` 和付费文献不进入 Git。
- CHGIS 原始 layer 禁止再分发；仓库只保留带强制引用和变更说明的派生选择。
- REACHES 原始记录不进入 Git；仓库保留聚合事件序列，但上游许可状态仍记录为 `unknown`。
- 若要重新构建 historical core，请自行从权利人或公开 locator 获取上游文件，并遵守其条款。

详细说明见 [`NOTICE.md`](NOTICE.md)、
[`docs/v2/data-rights-notice.md`](docs/v2/data-rights-notice.md) 和
[`sources/snapshots/`](sources/snapshots/)。仓库中的第三方名称、坐标、派生表和引文不因 MIT License
而获得新的许可。

## 仓库结构

```text
src/late_ming_lab/       模型、实验、协议、分析、存储、CLI 与本地 UI
data/                    参数卡、历史 patterns、协议、scenarios 和允许提交的派生输入
sources/                 来源登记、snapshot manifest 和获取规则
docs/mechanisms/v2_1/    最终机制卡；英文源稿与中文译稿
docs/v2_1/               V2.1 封存报告、limitations、handoff 和 bundle
docs/phase-reports/      每个 phase 的真实运行记录
tests/                   unit、integration、invariant、regression 和 policy tests
outputs/                 可再生运行目录；大部分由 .gitignore 排除
```

## 贡献

提交 issue 或 pull request 前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。任何新历史主张都必须附
来源、locator、证据等级和适用范围；任何新增数据都必须说明权利状态；测试不得依赖 live LLM。

## 引用与许可

引用信息见 [`CITATION.cff`](CITATION.cff)。软件代码和原创文档采用
[`MIT License`](LICENSE)；第三方材料和派生数据的边界见 [`NOTICE.md`](NOTICE.md)。
