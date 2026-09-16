# Late Ming Mechanism Lab V2 — OMP 分步骤对话提示词

## 使用方式

每次只复制一个 phase 的提示词给 OMP。OMP 完成、审查、提交并停止后，再进入下一 phase。

固定工作目录（替换为本机克隆路径）：

```bash
REPO_ROOT=/absolute/path/to/late-ming-mechanism-lab
cd "$REPO_ROOT"
```

计划和提示词已经随仓库保存在 `docs/`，无需从其他本机目录复制。

---

## Prompt 0 — V2-P00 Baseline Freeze & Scientific Audit

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P00 — Baseline Freeze & Scientific Audit。禁止开始 V2-P01。

先完整阅读：
- .omp/AGENTS.md
- .omp/RULES.md
- docs/OMP_ENGINEERING_PLAN.md
- docs/OMP_UPGRADE_PLAN_V2.md
- README.md
- docs/phase-reports/P08.md 至 P14.md
- outputs/reports/mechanism-synthesis.md

把 v0.1.0-rc1 当作只读科学基线。不要移动 tag，不要修改旧产物，不要修改机制、参数、
tick order 或历史数据。

任务：
1. 核对 HEAD、tag、git status、pyproject、uv.lock、所有正式 outputs manifests。
2. 生成机器可读的 V1 baseline manifest，记录代码、配置、数据卡、产物和报告的 SHA-256，
   同时记录每个产物的生成 commit，不得把旧 commit 静默写成当前 HEAD。
3. 逐项审计原计划的 Milestone M1、M2 和 12 条最终成功标准，标为 met / partial / unmet /
   not-testable，并给出文件与 artifact 证据。
4. 建立 docs/v2/scientific-readiness.md，明确工程 RC、合成机制实验和区域历史模型三者的边界。
5. 为 V2-P00 至 V2-P09 建立 phase report/exec plan 命名约定，不提前实现后续 phase。
6. 运行完整 pytest、ruff、format check、mypy、doctor；记录实际命令、环境和结果。
7. 用 reviewer 做只读反证审查：重点检查样本量、合成输入、阈值、runtime refusal 和 artifact lineage。

Acceptance：
- v0.1.0-rc1 保持不变；旧产物内容不变。
- baseline manifest 可重复验证且检测任一文件漂移。
- 每张 V1 机制卡都列出其数据集、气候模式、样本量、政策臂和外推限制。
- docs/phase-reports/V2-P00.md 完整；git diff 只含本阶段 docs/manifest/test 支撑。
- 逻辑 commit，working tree clean，输出 completion summary，然后 STOP。
```

---

## Prompt 1 — V2-P01 Evidence & Rights Spine

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P01 — Evidence & Rights Spine。禁止开始 V2-P02。

先读：.omp/AGENTS.md、.omp/RULES.md、docs/OMP_UPGRADE_PLAN_V2.md、
docs/phase-reports/V2-P00.md、docs/phase-reports/P08.md、docs/evidence/*、sources/registry/*、
data/normalized/evidence_ledger*.yaml、data/parameters/*。

本阶段是证据与权利核查，不改参数，不改机制，不跑校准。

任务：
1. 为 V2 建立 source snapshot manifest schema：source id、版本、locator、rights、acquisition method、
   download timestamp、SHA-256、redistribution status、derived-output rule。
2. 实际打开并核对 V2 会使用的公开来源，优先：CHGIS V6、REACHES、Chen et al. 2024，
   以及当前 13 条 unverified records。只因搜索到标题不得标 verified。
3. 把 institution/human-only 资料保留在 acquisition queue；不得代替人下载或绕过权限。
4. 按 decision relevance × sensitivity × evidence weakness 对证据任务排序：气候、价格、迁徙、
   赈济、军饷/逃兵、死亡、债务/土地、治理阈值。
5. 对许可不允许再分发的文件，只提交获取脚本/说明、schema、manifest 和允许发布的派生元数据；
   raw file 进入已忽略目录。
6. 更新 coverage/gaps/uncertainty 生成器，使 rights 和 verification 状态进入报告。
7. reviewer 抽查 locators、grade 上限、rights 判断和 claim aptness；不能只做引用完整性检查。

Acceptance：
- V2 实际引用的来源全部实际打开并核对 locator；未核实者不能升级 grade。
- 每个 raw snapshot 有 hash；受限和许可不明数据未进入 Git。
- source → claim → parameter/rule 链仍双向完整。
- pytest/ruff/mypy 通过；docs/phase-reports/V2-P01.md、逻辑 commit、clean tree、STOP。
```

---

## Prompt 2 — V2-P02 Historical Core Dataset

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P02 — Historical Core Dataset。禁止开始 V2-P03。

先读：.omp/AGENTS.md、.omp/RULES.md、docs/OMP_UPGRADE_PLAN_V2.md、
docs/phase-reports/V2-P01.md、docs/phase-reports/P02.md、
docs/adr/0001-node-and-catchment-geography.md、networks/adapter.py、networks/dataset.py、
systems/climate.py 和 data rights manifests。

目标：建立一个有来源的 historical-core-v1，而不是把 medium fixture 改名。

任务：
1. 从 1625–1644 有效的陕西—河南单位中选择 8–20 个证据覆盖较好的节点；记录选择规则和遗漏。
2. 接入有来源的历史单位身份、位置和上级关系；保留位置/有效期不确定性。
3. 分别构造 trade、migration、military candidate edges 和 accepted edges；每类图独立给出规则、
   provenance、cost/capacity/risk 的证据等级。空间邻近本身不能自动成为历史边。
4. 接入 observed climate forcing。保留原始年度/季节分辨率；如果模型需要月度分配，建立显式、
   可消融、带参数卡的 temporal allocator，不能制造月度“观测”。
5. 生成 node-year、edge-type、field-level coverage/missingness 报告。
6. 新增 historical scenario id 和 schema version；toy/medium 保留用于测试。
7. 运行 24-tick smoke 和 240-tick historical core run，检查 fail-closed coverage、provenance、
   event log、replay 和性能。正式 V2 报告不得使用 synthetic run 冒充历史 baseline。

Acceptance：
- historical-core-v1 每个事实字段有来源/locator/grade；未知值是显式 parameter band 或 missing。
- observed mode 完整覆盖时可重放，缺覆盖时指出精确 node-period 并拒绝。
- 三张图节点/边分离且可审计；raw 权利约束得到遵守。
- 如果不足 8 个可靠节点，交付 gap packet 和缩小范围建议，不静默填值。
- tests/invariants/regression、ruff、mypy 通过；V2-P02 report、review、commit、clean tree、STOP。
```

---

## Prompt 3 — V2-P03 Outcome & Validation Protocol

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P03 — Outcome & Validation Protocol。禁止开始 V2-P04，也不要先看新的正式结果再定规则。

先读：.omp/AGENTS.md、.omp/RULES.md、docs/OMP_UPGRADE_PLAN_V2.md、
docs/phase-reports/V2-P02.md、docs/calibration/*、docs/experiments/*、
analysis/governance.py、evidence 参数卡中 GovernanceIndicatorParameters。

任务：
1. 建立并冻结 validation-protocol-v2.yaml：primary/secondary outcomes、方向、窗口、聚合、
   缺失处理、最小实质效应和可用的历史比较层级。
2. 主结局使用连续多维向量：财政、赈济、军供、迁徙、市场、生计、武装集中；breakdown 只作派生读数。
3. 为 8 个治理阈值建立 threshold ensemble：来源、范围、normative/model-assumption 身份和采样规则。
4. 实现阈值稳健性报告：每个机制状态在阈值带中成立、改变和未定的份额。
5. 建立 model-comparison-register.yaml，预注册 V2-P04/P05 的替代结构、区分 observables 和 falsifiers。
6. 再次强制 calibration/hold-out/extrapolation 窗口双向隔离，协议版本改变使旧批次 fail closed。
7. reviewer 尝试通过改变单一任意阈值翻转核心结论；如能翻转，报告该依赖而不是选一个阈值。

Acceptance：
- 后续报告只能从冻结协议读取定义；协议有 hash/version。
- 任意阈值不再被写作历史事实；机制状态对 threshold ensemble 的依赖可见。
- 不改机制，不调参数，不跑正式 V2 calibration。
- tests/ruff/mypy、V2-P03 report、review、commit、clean tree、STOP。
```

---

## Prompt 4 — V2-P04 Failed Hold-out Mechanisms

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P04 — Failed Hold-out Mechanisms。禁止开始 V2-P05。

先读：docs/OMP_UPGRADE_PLAN_V2.md、docs/phase-reports/V2-P03.md、
docs/calibration/mismatch.md、docs/calibration/prediction.md、相关 historical patterns、
systems/climate.py、systems/markets.py、systems/migration.py、systems/fiscal.py、三张网络实现。

任务：
1. 对 V1 失败项逐个建立诊断：晚期气候/饥荒集中、local price extremes/dispersion、
   relief coverage、Shaanxi net outflow。每项分类为数据、观测函数、参数、结构或仍不可判定。
2. 在同一 historical-core-v1、同一 world seeds 下运行至少两个竞争结构版本。
3. 价格链至少记录库存、未成交需求、交易容量、运输成本和价格限制各自的约束。
4. 赈济链拆开库存、银两、物流、资格瓶颈；迁徙链拆开临时、永久、出界、目的地容量和旅途损失。
5. observed 与 synthetic forcing 只作声明清楚的对照，禁止调 observed series 追分。
6. 每个新增参数建 card；新增结构有具名 ablation 和中间量输出。
7. 用冻结的 V2-P03 协议评分，但不以“hold-out 变绿”作为唯一选择依据。

Acceptance：
- 每个旧失败项都有 artifact-backed 诊断和未解决边界。
- 结构比较能从 config diff、事件计数和中间量证明干预真实发生。
- 任何 no-op arm 使 phase 失败。
- tests/invariants/regression、ruff、mypy、V2-P04 report、independent review、commit、clean tree、STOP。
```

---

## Prompt 5 — V2-P05 Missing Mechanism Variants

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P05 — Missing Mechanism Variants。禁止开始 V2-P06。

先读：docs/OMP_UPGRADE_PLAN_V2.md、docs/phase-reports/V2-P04.md、六张 V1 机制卡、
actors/households.py、actors/elites.py、actors/military.py、systems/household_survival.py、
systems/elites.py、systems/military.py、docs/adr/0002-military-abstractions.md。

任务：
1. M006：只有在 V2-P01 证据足以给出结构和范围时，实现持续生计缺口下的 demographic/labour loss；
   区分死亡、永久迁出、招募，加入 NO_MORTALITY。证据不足则只交付接口、观测量和 gap report，
   状态继续 UNIDENTIFIED。
2. M004：实现可区分的 elite mediation 与 accumulation/foreclosure 结构臂，记录贷款、违约、
   土地转移、隐藏地和税基中间量。
3. M005：分别记录 formation、refugee intake、deserter intake、merger、split、dissolution 对集中度的贡献；
   设计能触发 merger 的正控制和阻止 merger 的负控制。
4. M003：建立 arrears persistence/hysteresis 候选，测试 settlement、remission、revenue recovery；
   不恢复已经被否证的单调主张。
5. M001/M002：建立 policy × structural lever 的最小因子实验设计。
6. 扩展 grain/silver/land/population/labour/military mass-balance invariants。

Acceptance：
- 每个具名臂实际触发事件/状态路径，正负控制符合预期；无空操作消融。
- 新规则没有年份、地名、人物或 1644 outcome hard-code。
- 所有中间量进入 event log 和 artifact schema，且可由 run 重算。
- tests/invariants/regression、ruff、mypy、V2-P05 report、review、commit、clean tree、STOP。
```

---

## Prompt 6 — V2-P06 Calibration V2

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P06 — Calibration V2。禁止开始 V2-P07。

先读：docs/OMP_UPGRADE_PLAN_V2.md、docs/phase-reports/V2-P05.md、
validation-protocol-v2.yaml、model-comparison-register.yaml、calibration/*、experiments/calibration.py。

任务：
1. 冻结 calibration-v2 配置：只纳入有 evidence-backed range 且对目标可识别的参数；
   S 级无范围参数不得用任意宽 prior 混入。
2. 修改 simulator，使一个 parameter vector 对多个 process seeds 求条件分布/距离；
   记录 seed 集，不把固定 CRN 表面当作过程不确定性。
3. 建立 particle/population ladder 和至少 4 个 sampler seeds；pilot 先跑，按计划的稳定性门决定加倍。
4. 记录 stages、acceptance、weighted ESS、duplicate fraction、simulation count、缓存命中和运行成本。
5. 输出 parameter-level posterior、pattern-level PPC、结构版本对照、equifinality/ridge 和固定-CRN对照。
6. hold-out/extrapolation 保持完全隔离，直到 posterior 冻结后才运行预测。
7. 大批次使用现有 batch/HPC；compute node 禁网、禁 key、禁 runtime LLM。

停止门：
- 连续两个 ladder 级别关键后验位置变化 < 0.10 prior range；
- 关键机制预测变化 < 0.05；
- ESS/particle、acceptance、duplicate fraction 达到预注册门；
- 未达到就报告 non-converged，不称 identified。

Acceptance：
- 多 process seeds、多 sampler seeds 和全部诊断写入 manifest。
- posterior freeze hash 产生后才运行 hold-out；窗口混用测试 fail closed。
- 结果可 checkpoint/resume；失败 task 不被合并成粒子。
- tests/ruff/mypy、V2-P06 report、review、commit、clean tree、STOP。
```

---

## Prompt 7 — V2-P07 Sensitivity & Counterfactual V2

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P07 — Sensitivity & Counterfactual V2。禁止开始 V2-P08。

先读：docs/OMP_UPGRADE_PLAN_V2.md、docs/phase-reports/V2-P06.md、冻结 posterior、
validation protocol、experiments/sensitivity.py、experiments/counterfactual.py、batch/HPC 实现。

任务：
1. 在证据范围/冻结 posterior 支持域内建立 Morris ladder：20 trajectories 起，bootstrap 检查 top-k，
   必要时 40；记录每级排名稳定性。
2. Sobol N 使用 2 的幂，按 64→128→256 加倍；先 calc_second_order=false 稳定 S1/ST。
   只有预注册交互候选才运行二阶。
3. 对非单调/偏态连续输出可增加 SALib PAWN，并明确它不是因果证据。
4. 消融与政策臂使用 paired CRN，最少 16、最多 64 replicates；按区间宽度和最小实质效应停止。
5. tipping 先跑 5×5×8 seeds 粗网格；自适应边界点使用新 seeds，并用保留 seeds 复验。
6. 分析连续 primary outcomes、机制链中间量和 threshold ensemble；近常数输出不做定量 Sobol 解读。
7. 报告所有 NaN、负值、>1 估计和 CI，不裁剪成看似合理指数。

Acceptance：
- 排名、S1/ST、关键机制效应和边界在 N 加倍后稳定；否则明确 non-converged。
- 每个 adaptive choice 和停止决定写入 manifest；不存在事后挑网格。
- artifact 查询可重算报告数字；HPC merge 不插值失败任务。
- tests/ruff/mypy、V2-P07 report、independent review、commit、clean tree、STOP。
```

---

## Prompt 8 — V2-P08 Runtime Policy Completion

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P08 — Runtime Policy Completion。禁止开始 V2-P09。

先读：.omp/RULES.md、docs/architecture/runtime-llm-boundary.md、
docs/phase-reports/P11.md、P12.md、V2-P07.md、policies/*、tests/policies/*。

人工 gate：操作者必须已经从 USTC 账户 /v1/models 确认准确 DeepSeek V4.1 model id，
并在未提交的 .env 中启用。不要读取、打印、记录或提交 API key。若 model id 未确认或 gate 未开，
记录 refused，保持 M2 未完成，完成本阶段报告后 STOP。禁止猜 id、改成 flash/pro、或 fallback。

gate 打开时执行：
1. 建立覆盖 role/action/trigger 的匿名 observation corpus；审计地名、朝代、人名、日期和未来信息。
2. 先跑 live suite 和少量 recording smoke；验证 model-reported id、schema refusal、timeout、429、成本。
3. 清理并保存 prompt/response/model/schema hashes 和可重放 fixtures；rationale 仍不得改变状态。
4. 在 historical-core-v1 上用 fixture replay 跑 runtime arm；world seeds 与 rule/utility/random 配对。
5. 使用 V2-P07 的重复数/停止规则比较政策稳健性；预算不足时只称 pilot。
6. reviewer 检查无 fallback、无工具、无凭证泄露、匿名化、未来信息和 action-to-lever 完整性。

Acceptance：
- 唯一人工确认模型，零 fallback；live/record/replay 链可审计。
- fixture miss fail closed；online 与 offline replay 状态变化一致。
- runtime arm 有区间和样本量说明；拒绝臂仍不插值。
- tests（default offline + opt-in live）、ruff、mypy、V2-P08 report、commit、clean tree、STOP。
```

---

## Prompt 9 — V2-P09 Mechanism Synthesis & Release Candidate 2

```text
你现在位于：
<REPO_ROOT>

只执行 V2-P09 — Mechanism Synthesis & Release Candidate 2。没有后续 phase。

先读：docs/OMP_UPGRADE_PLAN_V2.md、全部 V2 phase reports、冻结协议、data/rights manifests、
V2 calibration/sensitivity/counterfactual/policy artifacts、V1 与 V2 mechanism cards。

任务：
1. 从 typed artifact accessors 重算全部机制卡，不手抄数字，不继承旧状态。
2. 每张卡写 V1→V2 status、改变原因、适用 dataset/forcing/policy/threshold band、
   model evidence、historical support、historical challenge、counterexample、falsifier、uncertainty。
3. 增加 provenance chain：source locator → normalized row → parameter/rule → run hash → statistic → card。
4. 生成英文原稿、中文译稿、综合报告、失败/未识别清单、data rights notice 和 reproduction guide。
5. 建立 release bundle manifest，绑定 code SHA、uv.lock、data/config hashes、artifact schemas、reports、翻译版本。
6. reviewer 用 Polars/DuckDB 重算关键数字，重生报告并 diff，逐卡挑战状态、外推和许可。
7. 运行 full pytest、ruff、format check、mypy、doctor、synthetic demo、historical demo、benchmark。
8. 只有全部 gate 满足才创建 v0.2.0-rc1；否则发布 limitation report，不勉强 tag。

必须明确：
- simulation support 不是 historical truth；
- failed/rejected/unidentified 是有效结果；
- 如果 V2-P08 gate 未开，Milestone M2 仍未完成；
- synthetic demo 与 historical core 结果不可混称。

Acceptance：
- 所有卡片数字可解析到有 hash 的 artifact/source；英文与中文状态一致。
- release bundle 可在无网络、无 runtime LLM、无受限 raw 数据时验证允许发布的部分；
  需要私有原始数据的步骤有明确 acquisition/rebuild 说明。
- final review、full gates、logical commits、clean tree；符合条件才 tag；输出 final completion summary，STOP。
```
