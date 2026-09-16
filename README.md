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

## 模型讲出了一条怎样的故事

以下叙事把六张机制卡按照模型中的传导顺序连接起来，方便理解整体含义。它不是对晚明历史过程的
复述，也不是一次端到端实验估计出的单一因果链；六个环节来自不同的结构对照，数字都是模型结果。
完整中文卡片位于 [`docs/mechanisms/v2_1/zh/`](docs/mechanisms/v2_1/zh/)。

故事从歉收造成的粮食缺口开始。参照运行的 60 个家庭队列中，有 16 个出现过粮食短缺，最长的一次
连续低于生存线 48 个月。这足以说明模型中的生计压力不是瞬时噪声，却还不能推出“有多少人因此
死亡”。现有证据只有人口下降的方向和灾荒先后次序，没有可用于约束县级死亡率的连续序列。因此
模型宁可让死亡规则保持空缺，也不使用一个看似合理但无法验证的数字。**M006 饥荒死亡因此是
`UNIDENTIFIED`**：模型看见了饥饿，却没有资格把饥饿换算为死亡。

当死亡这条路径被搁置后，生计压力主要沿着迁徙、抛荒和信贷向下传导。迁徙门保持基线设置时，
可评估税基收缩 0.064；把迁徙成本和资格门槛打开后，收缩达到 0.993，配对差为 **+0.929**。这说明
在这个模型里，冲击能否穿过人口流动这道“门”，比冲击是否存在更能改变税基结局。但这个幅度不能
直接理解成历史上的人口损失：门开臂累计记录的 179,769 次移动是同一批 60 个队列在 240 个月里的
反复流量，而且当前土地记账会让迁出地抛荒，却不给迁入队列补入土地，从而放大反复迁徙对税基的
侵蚀。更重要的是，把连续收缩压成“是否崩溃”的二值判断后，默认阈线只在 46.1% 的阈值组合中成立。
所以 **M002 危机闸门是 `CONDITIONAL`**：传导方向和差异很清楚，“已经崩溃”却取决于阈值和记账
假设。

信贷是这条传导链上的另一处分叉。它可以让缺粮家庭暂时留在土地上，也可以在长期违约后把土地
转给贷方。积累分支中出现了 2,127 次违约和 51 次没收，约 13,064 亩土地发生转移，说明模型确实
生成了“债务转为土地”的路径；可是与完全关闭信贷相比，它只让税基收缩多 **0.0081**，不到事先
规定的 0.02 最小实质效应。因此 **M004 精英中介分化仍是 `WEAK`**：没收现象存在，但现有实验
不足以把它说成这场系统性收缩的主要发动机。

随着土地和税基受压，地方财政会面对一个危险选择：为了补足短收而继续提高汲取，是否反而破坏
未来的收入来源？四个因子格给出了有条件的回答。采用递增征收时，两个价格设置都出现“征得更紧，
实收反而倒转”的形状；固定征收时，两个格都没有出现倒转。这把因果重心指向财政政策反馈，而不是
价格规则本身。不过每个格只有一条轨迹，没有重复样本，所以 **M001 财政汲取倒转是
`CONDITIONAL`**，不能泛化为“加税必然少收”。

财政压力接着进入军饷账户，但模型没有支持一条只升不降的“欠饷棘轮”。结算、豁免和恢复后追缴
分别触发了 380、636 和 161 次欠饷清理事件；规则关闭时则没有清理。欠款可以累积，也可以因制度
动作下降。因此 **M003 财政—军事棘轮被 `REJECTED`**。这里被否定的是“欠饷永远单调增加”这个
强命题，不是财政困难、欠饷和军事行为之间存在联系的可能性。

链条最后来到武装组织。危机环境本身不会自动把分散武装变成一个大集团：把合并门槛拉到最高时，
模型没有发生合并，最大集团占比约为 0.199；把门槛降到零后，约 4,094 名兵力进入合并链，最大集团
占比升至 0.341。也就是说，集中并不只是因为小集团消失，模型中明确的合并规则确实贡献了集中。
**M005 武装整并是六张卡中唯一的 `SUPPORTED`，也是目前最清楚的模型内部机制。**

把这些环节连起来，模型呈现的不是“灾荒一来，社会就自动崩溃”，而是一条受制度条件控制的传导
过程：粮食缺口先给家庭造成压力；迁徙和土地记账决定压力是否迅速转成抛荒与税基损失；信贷能够
缓冲生计，也可能通过没收转移土地，但在当前运行中只是较弱的放大器；财政若以递增汲取回应短收，
可能进一步损害收入基础；欠饷会积累，却能被清理；分散武装只有在合并条件允许时才明显集中。
这条叙事最重要的含义是，**决定结果的不是单独一次歉收，而是冲击能否连续穿过人口、土地、财政、
军饷和组织规则形成的多道闸门。**

V2.1 没有改变六张卡的状态。它补做了 M002 和 M004 的决定性对照，并纠正了样本数：P05 声明的
四个 seed 在同一 arm 内产生相同的 simulation digest，事件日志也没有 RNG draw，因此只是同一条
确定性轨迹的重复执行，不是四个独立过程样本。

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

这套模型目前最能支持的解释，可以浓缩为一句话：**歉收提供压力，制度闸门决定压力往哪里走，组织
规则决定压力最后以什么形态集中。** 它能够展示从缺粮到迁徙与抛荒、从税基受损到财政反馈、再到
军饷调整和武装整并的一组可能路径；它不能证明晚明历史必然沿着这条路径运行，也不能给出各环节在
真实历史中的准确强度。

六张卡共同划出了这套解释的可信边界。武装合并有最直接的正负对照；危机闸门有很大的连续效应，
但幅度受到迁徙和土地记账影响；财政倒转只在递增征收结构下出现；精英没收真实触发却没有达到实质
效应门槛；单调欠饷棘轮被反例否定；饥荒死亡因为缺少可校准的死亡序列而保持空白。支持、条件成立、
弱效应、否证和不可识别在这里都是有效结果，而不是必须调成同一个方向的六份证明。

校准与敏感性门没有通过，也限制了这条叙事可以走多远。继续增加粒子、seed 或县数，不会自动补上
缺失的观测目标，也不会让确定性重放变成独立样本。若继续升级，最有价值的工作是找到能够约束死亡、
迁徙和财政幅度的新数据，修正迁徙后的土地记账，并引入真正产生不同过程轨迹的随机性；在这些条件
出现以前，V2.1 更适合作为一个透明的机制论证和反事实实验平台，而不是一台已经校准好的晚明历史
复原器。

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
