# Late Ming Mechanism Lab V2 升级计划

> 面向 OMP 的执行规格；审阅基线：`/Users/wahrfreiheit/OMP/late-ming-mechanism-lab`，
> HEAD `a81c223216f989150d69fe42bfe0a78f7eab1374`，tag `v0.1.0-rc1`，审阅日期 2026-09-14。

## 1. 结论与升级目标

V1 已经完成了一个优秀的、可复现的历史机制实验室骨架：确定性内核、分流 RNG、事件日志、
证据注册表、ABC/SMC 校准、消融与敏感性实验、制度决策接口、机制卡、批处理、HPC 和只读 UI
都已经具备。下一版不应重写工程底座，也不应扩张到全国。

V2 的核心任务是把项目从“合成空间上的机制原型”升级为：

> **在来源、空间、时间和观测误差都明确的陕西—河南历史核心数据上，能够区分替代机制，
> 对留出期失败保持诚实，并用收敛的实验设计给出可复核机制边界的区域历史机制模型。**

V2 成功不等于把更多机制卡改成 `SUPPORTED`。失败、拒绝和无法识别仍是有效结果。V2 的成功
标准是：真实历史输入已经接入；结果不再主要由任意阈值决定；统计结论在样本量加倍后稳定；
机制链的关键中间量可观察；所有历史主张都能回到具体来源和定位信息。

## 2. V1 审计结论

### 2.1 已经成熟，应直接保留

- 内核、月份时钟、子系统 RNG、运行清单、不可变 Parquet 产物和重放约束。
- 三张网络分离、参数卡/规则/证据的双向引用完整性、A/B/C/D/S 分级。
- 开发 LLM 与运行时 LLM 的边界；运行时默认关闭、无 fallback、可记录和离线重放。
- 共同随机数下的配对反事实、显式消融臂、失败任务不插值的批处理与 Slurm 数组。
- 机制卡的状态词表、干预证据要求、反例和可证伪预测字段。
- “Simulation is an argument, not evidence” 这一认识论边界。

### 2.2 科学升级的主要瓶颈

| 优先级 | 瓶颈 | 当前证据 | V2 必须达到的状态 |
| --- | --- | --- | --- |
| P0 | 真实空间与气候没有进入正式运行 | demo 使用 `medium` 合成夹具；节点、边、距离、容量、风险均为 S 级；气候为随机 synthetic forcing | 建立有来源、有许可、有覆盖报告的 `historical-core-v1`，正式实验使用 observed forcing |
| P0 | 参数证据过薄 | 102 个参数中 93 个为 S 级，70 个没有 claim；25 条来源中 13 条未核实 | 把高敏感参数、结局阈值和新机制参数作为定向证据任务；不能约束的参数继续明确为 S |
| P0 | “崩溃”读数受任意阈值支配 | 8 个治理阈值全为 S 级；P10 的 `indicators_crossed_end` 大量集中在 5–6，Sobol 对该输出为 NaN | 预注册连续结局向量和阈值带；二元 breakdown 只能作为派生读数，并报告阈值稳健性 |
| P0 | 推断样本量不能支撑定量指数 | 校准仅 32 particles、1 chain、2 个 sampler seed；Morris 2 trajectories；Sobol base N=4；tipping 每格 1 次；P10 消融每臂 4 次 | 使用逐级加倍和停止规则；在指数、排序、后验位置稳定前不发布定量主张 |
| P0 | 留出期存在系统失败 | 气候峰值、饥荒后期集中、价格峰值、赈济覆盖和陕西外流在若干窗口失败 | 把失败项作为模型鉴别任务；禁止只调参数把分数“修绿” |
| P1 | 关键机制链缺环 | M006 无死亡；M004 无累积支；M005 合并规则从未触发；M003 单调棘轮被否证 | 以结构替代模型和具名干预臂补齐；保留旧结构作对照 |
| P1 | 历史空间规模与实验规模不一致 | 正式机制综合主要来自 3 个县、32 个 cohort 的 toy sandbox；regional baseline 未跑 | 先完成有证据的 8–20 节点 historical core，再据覆盖和算力扩到更多节点 |
| P1 | 校准把过程噪声固定在一个 root seed | 每个 proposal 使用同一组共同随机数，便于比较但会把一个随机实现当成目标表面 | 对每个参数向量边际化多个过程 seed；CRN 仅用于成对比较，不代替过程不确定性 |
| P1 | 第二科学里程碑尚未完成 | USTC runtime arm 被配置门拒绝，P12 没有 runtime 结果 | 经人工确认 model id 后做小规模在线记录、离线重放和政策稳健性；没有确认就继续标记未完成 |
| P2 | 产物代际与发布状态需更清楚 | P09/P10/P12 产物记录的是生成时旧 commit；HEAD 还有中文译稿更新 | 建立 release bundle：代码、数据、配置、产物、报告各自 hash 与兼容关系 |

### 2.3 首轮结果应怎样解释

V1 的六张卡可以继续作为 V2 的先验问题清单，但不能直接当作历史结论：

- `M001 Fiscal Extraction Inversion`：政策依赖，下一步是做政策 × 汲取响应的因子实验。
- `M002 Crisis Gating`：在当前模型中有干预支持，但需排除合成迁徙网络、任意出口容量和阈值定义造成的门效应。
- `M003 Fiscal-Military Ratchet`：单调版本已被拒绝。V2 应改问欠饷的持续性、滞后和恢复，而不是调参救回“棘轮”。
- `M004 Elite Mediation Bifurcation`：只测到了信贷中介，没有建立两条分支；需要显式的中介/累积替代结构。
- `M005 Insurgent Consolidation`：结果稳健，但文档所称的 merger 链没有运行；需要区分形成、吸收、合并、分裂和解散的贡献。
- `M006 Famine Mortality`：完全未识别；只有在证据足以约束结构和范围时才实现，否则继续保持 `UNIDENTIFIED`。

## 3. 可复用的公开数据与工具

优先复用当前依赖。`pyproject.toml` 已有 GeoPandas、Shapely、PyProj、Polars、DuckDB、PyMC、
ArviZ、SALib、scikit-learn、joblib 和 Mesa，不需为 V2-P00–P03 新增框架。

| 资源 | 用途 | 接入原则 |
| --- | --- | --- |
| [CHGIS V6](https://chgis.fas.harvard.edu/data/chgis/v6/) | 1625–1644 有效行政单位、地名、点位和上级关系 | 许可为学术研究免费，禁止商业使用、转售或再分发。原始数据放 `data/raw/private/`；先写 rights review，再决定哪些派生字段可提交 |
| [REACHES Climate Database](https://reaches.rcec.sinica.edu.tw/index.html) | 1368–1911 文献气候事件；可提取陕西、河南的干旱、饥荒及时间分布 | 保存原始快照 hash、下载时间、字段字典与引用；先验证具体下载文件的许可，不把“可下载”自动等同于“可再分发” |
| [Chen et al. 2024](https://doi.org/10.5194/cp-20-2287-2024) | 崇祯旱灾 1627–1644 的年度空间重建和灾荒传播，对 observed forcing 与 hold-out 很直接 | 优先使用论文公开补充材料；记录其空间分辨率，不能伪装成县—月观测 |
| [NOAA NCEI Paleoclimatology](https://www.ncei.noaa.gov/products/paleoclimatology/historical) | REACHES 和其他历史气候数据的长期归档、元数据与下载入口 | 数据集逐项记录权利、版本、下载 URL 与校验和 |
| [SALib Sobol sampler](https://salib.readthedocs.io/en/main/api/SALib.sample.html) | Morris/Sobol/PAWN；项目已经使用 | Sobol 的 N 用 2 的幂，逐级加倍；先稳定一阶/总效应，再决定是否付出二阶成本 |
| PyMC + ArviZ | ABC/SMC、posterior predictive、后验与跨 run 诊断 | 先保留现有实现；只有 checkpoint/resume 或自适应 population 明确不足时才评估 pyABC |
| GeoPandas + Pyogrio/Shapely + NetworkX | 历史点位、河流/道路的空间连接和可审计的图构造 | 图的每类边仍须独立；几何邻近不能自动成为贸易、迁徙或军事边 |
| DuckDB + Parquet | 跨批次查询、长表输出和 release bundle | 每个结论的查询应可保存为 SQL 或纯函数，并绑定 artifact hash |

不建议现在引入大型数据编排平台、全国 GIS、深度学习 surrogate 或更多 LLM agents。它们不能解决
当前最关键的来源、识别与样本量问题。

## 4. V2 不可破坏的原则

1. `v0.1.0-rc1` 永久保留为只读基线；V2 使用新分支、新场景 id、新 schema version 和新输出目录。
2. 不直接改写 V1 产物，也不把旧报告静默重生成为 V2 结果。
3. 历史数据、假设、模型生成值继续分层保存；缺失值不按“看起来合理”填充。
4. 任何 observed series 都保存原始分辨率；年度记录不得标成月度观测。季节分配必须作为有参数、有不确定性的转换模型。
5. 不以“更接近 1644”为结构选择标准。结构由留出期、干预辨识、外部证据和简约性共同评估。
6. 结局和判定规则必须在 V2 正式批次之前冻结。
7. 统计设计以收敛和精度停止规则为准，不以“跑完固定少量任务”为准。
8. runtime LLM 只做已有 bounded institutional decisions；不能决定产量、价格、死亡、迁徙人数、战果或招募人数。
9. 受限资料由人获取；agent 只处理明确授权、可访问的文件和公开元数据。
10. 每个 phase 结束于报告、审查、逻辑 commit、clean tree 和 STOP。

## 5. V2 路线图

| Phase | 名称 | 核心问题 | 主要 gate |
| --- | --- | --- | --- |
| V2-P00 | Baseline Freeze & Scientific Audit | V1 到底完成了什么，哪些主张暂不能外推？ | hash 清单、验收矩阵、V2 计划入库；不改机制 |
| V2-P01 | Evidence & Rights Spine | V2 的每个输入是否合法、可定位、可复核？ | 选中来源全部核实；权限与 acquisition gate 完整 |
| V2-P02 | Historical Core Dataset | 能否在真实空间与 observed forcing 上运行？ | 8–20 个有证据节点；覆盖/缺失报告；不静默插值 |
| V2-P03 | Outcome & Validation Protocol | 什么叫失稳，结论是否依赖任意阈值？ | 连续结局向量、阈值带、冻结 hold-out 和判定协议 |
| V2-P04 | Failed Hold-out Mechanisms | 当前气候、价格、赈济、外流失败来自哪里？ | 替代结构对照；至少一个失败被解释或明确保留 |
| V2-P05 | Missing Mechanism Variants | 死亡、精英分支、武装整合与欠饷持续性如何区分？ | 结构臂和中间量可观察；无空操作消融 |
| V2-P06 | Calibration V2 | 后验是否稳定，是否覆盖过程不确定性？ | 多 seed、多链/多次重复、ESS/稳定性/PPC gate |
| V2-P07 | Sensitivity & Counterfactual V2 | 敏感性指数和机制边界在样本量加倍后是否稳定？ | Morris/Sobol 收敛梯、足量配对重复、边界复验 |
| V2-P08 | Runtime Policy Completion | 机制对真实 bounded runtime policy 是否稳健？ | 人工确认模型、在线记录、离线重放；无确认则明确未完成 |
| V2-P09 | Mechanism Synthesis & RC2 | 哪些 V1 结论存活、改变、被拒绝或仍不可识别？ | 全卡重算、双语报告、release bundle、`v0.2.0-rc1` |

依赖顺序固定：`P00 → P01 → P02 → P03 → P04 → P05 → P06 → P07 → P08 → P09`。
P08 的人工 gate 不应阻塞 P00–P07；若 gate 仍关闭，P09 可以产出 RC2，但不能宣称完成 Milestone M2。

## 6. 分阶段执行规格

### V2-P00 — Baseline Freeze & Scientific Audit

**目标**

- 将 V1 的代码、配置、数据卡、产物和报告 hash 固定成 `baseline-v1.json`。
- 把本计划写入 `docs/OMP_UPGRADE_PLAN_V2.md`，建立 V2 phase report 模板。
- 逐条审计原计划 M1/M2 和最终成功标准，标记 `met / partial / unmet / not-testable`。
- 建立 `docs/v2/scientific-readiness.md`，明确“工程 RC”与“历史区域模型”的边界。

**验收**

- V1 tag 不移动；当前工作树干净；V1 产物 hash 可复查。
- 所有 V1 机制卡在矩阵中有 artifact、样本量、空间/气候模式和外推限制。
- 当前完整测试、lint、type check 的真实结果写入报告；环境限制导致的失败要逐项说明。
- 不修改任何机制、参数或历史数据。

### V2-P01 — Evidence & Rights Spine

**目标**

- 对 V2 会使用的来源逐条打开核实；优先处理 CHGIS、REACHES、Chen 2024 及当前 13 条未核实记录。
- 为每个数据文件增加 source id、版本、locator、rights、acquisition method、download timestamp、SHA-256。
- 建立 human-only queue：明实录、地方志、税粮册、赈济册、军饷册等仍由人决定获取。
- 按“结论影响 × 当前不确定性”排序证据任务，而不是平均填满 102 张卡。

**优先证据对象**

1. observed drought/famine timing and geography；
2. local grain-price level/dispersion；
3. migration direction/timing；
4. relief timing/capacity；
5. pay arrears and desertion；
6. mortality and abandonment；
7. credit, foreclosure and land transfer；
8. governance outcome thresholds。

**验收**

- V2 被引用的每条来源都达到“实际打开并核对 locator”；无法核对的不能升级 grade。
- 每个 raw snapshot 都能由 manifest 验证；受限数据和许可不明数据不提交。
- 提交的是转换脚本、schema、元数据与允许发布的派生表；许可不允许时只提交重建说明。
- 不改参数值，不运行校准。

### V2-P02 — Historical Core Dataset

**目标**

- 建立 `historical-core-v1`：以 1625–1644 有效的陕西—河南节点为核心，先做 8–20 个证据充分的节点。
- 接入真实点位/上级关系；分别建立 trade、migration、military 三张图。
- 建立 observed climate forcing；保留年度/季节分辨率和位置不确定性。
- 为边的存在、距离、成本、容量和风险分别赋 provenance；未知值以参数带表达，不得伪装为观察。

**实现建议**

- CHGIS 只负责历史单位和位置身份；道路/河流邻近只生成 candidate edge。
- 每一类图用独立规则和证据确认；候选边与采用边都保存，便于审计。
- 年度气候若需进入月度农业系统，以 `AnnualForcingAllocator` 等显式转换器按作物季节分配，
  并把分配权重纳入敏感性，不生成虚构“月观测”。
- synthetic/toy/medium 继续服务测试，不能作为 V2 historical baseline。

**验收**

- 覆盖报告列出每个 node-year、每类 edge 和每个字段的 grade/缺失。
- observed mode 在覆盖完整时可跑 240 ticks；缺值时 fail closed，并明确缺的 node-period。
- 与 V1 synthetic run 的差异来自声明的数据/配置变化，manifest 能复原。
- 如果不足以建立 8 个节点，phase 交付 gap packet 和最小可行替代范围，不静默填值。

### V2-P03 — Outcome & Validation Protocol

**目标**

- 在看 V2 正式结果之前冻结结局、窗口、判定规则和模型比较规则。
- 用连续多维结局替代把 `breakdown` 当唯一主结果：财政、赈济、军事供给、迁徙、市场连通、
  生计不足、武装集中各自报告。
- 将 8 个 S 级治理阈值变成有来源的范围或显式 normative band。
- 评估结论在阈值带上的稳健性，避免“跨了 5 条还是 6 条”主导机制判断。

**建议输出**

- `validation-protocol-v2.yaml`：primary/secondary outcomes、方向、时间窗、aggregation、缺失规则。
- `threshold-ensemble.yaml`：每个阈值的范围、来源/假设、采样规则。
- `model-comparison-register.yaml`：候选结构、先验预期、能区分它们的 observables 和 falsifier。
- 按节点、按月、按机制链的中间量，不只保留期末汇总。

**验收**

- 所有 V2 后续报告从冻结协议读定义；更改协议必须新版本并使旧批次不兼容。
- threshold ensemble 下的机制状态分布被报告；不允许只挑一个有利阈值。
- hold-out/extrapolation 不进入拟合，且代码双向拒绝窗口混用。

### V2-P04 — Failed Hold-out Mechanisms

**目标**

针对 V1 的失败项做结构诊断，而不是参数追分：

1. observed drought 的后期集中与空间传播；
2. local price extremes 和节点间 dispersion；
3. relief coverage 在需要峰值时下降；
4. Shaanxi net outflow 的时点和持续性。

**候选结构臂**

- 价格：库存约束、局地供需、贸易容量/中断、交易成本、价格上限规则分别消融；记录未成交需求。
- 赈济：库存、银两、物流和资格四个瓶颈分别记录，避免一个 coverage 比例掩盖机制。
- 迁徙：临时/永久/出界流分离，目的地容量与旅途损失显式；历史出口不做无限 sink。
- 气候：observed forcing 与 synthetic forcing 并列，不把 observed series 再调成目标。

**验收**

- 每个原失败项有“数据问题 / 观测函数问题 / 参数问题 / 结构问题 / 仍不可判定”分类及证据。
- 至少两个互相竞争的结构版本运行在同一历史输入和 seeds 上。
- 任何新增上限、阈值或转换参数都有 card；无法约束者是 S 并进入 V2 敏感性池。
- 不以是否“通过 hold-out”单独决定结构。

### V2-P05 — Missing Mechanism Variants

**目标**

- M006：持续生计缺口 → demographic loss/labour loss；区分死亡、永久迁出和招募。
- M004：显式区分 elite mediation 与 accumulation/foreclosure，记录贷款、违约、土地转移和税基效应。
- M005：把 formation、refugee intake、deserter intake、merger、split、dissolution 对集中度的贡献拆开。
- M003：将“单调棘轮”改为 arrears persistence/hysteresis 候选，并测试结清、减免和收入恢复。
- M001/M002：建立政策 × 结构的因子臂，判断条件性来自政策还是结构。

**验收**

- 每个具名机制至少有一个能实际改变代码路径的干预臂；启动前和运行后检查事件数，空操作即失败。
- 质量、人口、土地、银、粮、军队人数的 invariant 扩展并通过。
- 新机制不直接编码年份、地名或 1644 结果；历史信息只能进入 forcing、prior、pattern 和比较。
- 如死亡率证据不足，允许只交付接口、观测量和 gap report，M006 保持 `UNIDENTIFIED`。

### V2-P06 — Calibration V2

**目标**

- 只校准 V2-P03 预注册且证据支持的参数；S 级且无范围的参数不能靠任意宽 prior 混入。
- 每个参数向量使用多个过程 seed，估计条件输出分布；共同随机数用于结构/参数配对。
- 运行 population/particle 和 sampler-seed 收敛梯，而不是把 32 particles 当最终后验。
- 用 posterior predictive 检查分量，不只看总 distance。

**建议停止规则**

- 从可负担的 pilot 开始，按 `64 → 128 → 256 → 512` 或相应 2 倍梯度增加 particles；
  最终级别由预先声明的稳定性门决定，不强制跑到某个数字。
- 至少 4 个独立 sampler seeds；比较加权中位数、IQR、ESS、重复粒子率和 pattern-level PPC。
- 连续两个级别中：关键后验位置变化 < 0.10 prior range，关键机制预测变化 < 0.05，
  且 weighted ESS/particle、acceptance 和退化率达到预注册门槛，方可停止。
- 对无法稳定的参数报告 ridge/equifinality，不贴 `identified` 标签。

**验收**

- 过程 seed、sampler seed、particles、population stages、acceptance、ESS、重复率全部入 manifest。
- 每个 target 和 hold-out 的观测误差/可信度进入 scoring；低证据 pattern 不与高证据 pattern 等权而不说明。
- 对固定 CRN 校准与多 seed 边际化校准做对照。
- hold-out 仍严格隔离。

### V2-P07 — Sensitivity & Counterfactual V2

**目标**

- 将 V1 的探索性样本扩展为可收敛的全局敏感性和配对反事实。
- 对连续结局、机制链中间量和阈值稳健性做分析；不再依赖近乎常数的 crossed-line count。

**建议设计**

- Morris：从 20 trajectories 起步；通过 trajectory bootstrap 检查 top-k 排名，必要时增到 40。
- Sobol：N 取 2 的幂，按 `64 → 128 → 256` 加倍；先 `calc_second_order=false` 稳定 S1/ST，
  二阶只对有证据的交互候选运行。
- 非单调/高度偏态输出可使用 SALib PAWN 作为补充；不得把多方法一致当成因果证据。
- 消融/政策臂使用 paired CRN，预注册最少 16、最多 64 replicates；按区间宽度和最小实质效应停止。
- tipping surface 先做 5×5 × 8 seeds 粗网格，再在不确定边界自适应加点；新点必须用保留 seeds 复验。

**验收**

- 关键参数排名、S1/ST 和边界在样本量加倍后稳定；否则报告不收敛。
- NaN、负值和 >1 的有限样本估计保留原值与 CI，并阻止“定量重要性”措辞。
- 机制效应同时报告绝对量、配对差、区间、方向稳定率和最小实质效应。
- 每个自适应选择都有 manifest，不能事后只展示有利网格。

### V2-P08 — Runtime Policy Completion

**人工 gate**

操作者必须从 USTC 账户 `/v1/models` 确认准确 model id，并在未提交的 `.env` 中设置。API key
不得进入计划、日志、fixture 或 memory。如果无法确认，记录 gate 关闭并结束该 phase；禁止猜 id 或 fallback。

**目标**

- 构造覆盖各 role/action/trigger 的匿名 observation corpus。
- 在线记录最小必要决策，检查 schema、拒绝、延迟、429、模型回报 id 和成本。
- 对记录的响应做离线 deterministic replay；随后在 historical core 上跑 runtime policy arm。
- 与 rule/utility/random 使用共同 world seeds 比较；model response 本身由 fixture 固定。

**验收**

- live suite 通过；所有调用来自人工确认的唯一 id；零 fallback。
- observation corpus 不含朝代、地名、人物、日期或未来信息。
- 每条 fixture 有 prompt/response/model/schema hash；敏感字段清理完成。
- 运行时臂有足量重复和不确定性区间；若调用预算不足，报告 pilot，不升级 M2 状态。

### V2-P09 — Mechanism Synthesis & Release Candidate 2

**目标**

- 从 V2 artifacts 重算机制卡，禁止手抄 V1 数字。
- 每张卡给出 `V1 status → V2 status`、改变原因、适用数据集/政策/阈值带、历史支持与挑战。
- 发布 English source + Chinese translation，生成 artifact lineage 和 reproduction bundle。

**验收**

- 机制卡数字从 artifact accessor 读取；每条引用能解析到 source 或带 hash 的 batch。
- 报告明确区分 model support、historical support 和 unresolved evidence。
- 独立 reviewer 重算关键统计、检查卡片状态和许可边界。
- 完整 pytest、ruff、mypy、doctor、demo、benchmark 通过；historical demo 与 synthetic demo 分开。
- 只有全部 gate 满足才 tag `v0.2.0-rc1`；未完成项进入 release limitations，而不是隐去。

## 7. 跨阶段量化 gate

| Gate | 通过条件 |
| --- | --- |
| Data | V2 正式输入全部有 source/version/rights/hash；空间与时间覆盖显式；零静默插值 |
| Outcome | primary outcomes 和阈值带预注册；阈值选择不会单独翻转核心结论，或翻转被完整报告 |
| Calibration | 多过程 seed；至少 4 sampler seeds；后验与 PPC 达到预注册稳定性门 |
| Sensitivity | Morris/Sobol 排名与指数在 N 加倍后稳定；不稳定则降级措辞 |
| Intervention | 每个关键臂触发非零事件/状态路径；共同随机数和配置 diff 可验证 |
| Hold-out | 与拟合窗口代码隔离；所有失败保留并分类，不以单一总分遮蔽 |
| Policy | rule/utility/random 完整；runtime 只在人工确认后加入；拒绝臂不插值 |
| Provenance | source → normalized row → parameter/rule → run → statistic → mechanism card 全链可解析 |
| Release | bundle manifest 绑定代码、lock、data、config、artifacts、reports 和翻译版本 |

## 8. 资源与运行预算

先用 V1 benchmark 约 10 秒/240 ticks 估算，再以 V2 historical core 实测更新。任何 HPC 计划都从实际
benchmark 推导，不沿用 V1 的每任务成本。

- 本机：数据转换、单元/集成测试、1–2 个 pilot、报告生成。
- HPC：多 seed calibration、Morris/Sobol、反事实和 tipping batches；compute node 禁网、禁 key、禁 runtime LLM。
- 在线环境：只生成经审计的 runtime fixtures；HPC 仅 replay。
- 每个大批次先跑 1%、5% smoke，验证运行时间、内存、输出 schema、非空干预和 merge。

## 9. 暂不做的升级

- 不扩展到整个明朝或全国县级网格。
- 不把 UI 美化、3D 地图或动画当作科学升级。
- 不训练端到端神经网络预测“明亡概率”。
- 不让 LLM 控制物理/经济状态，也不增加大量 LLM actors。
- 不因为 M003 被拒绝而调参恢复它；不因为 M006 未识别而无证据硬加死亡率。
- 不把更多来源条目数量当作证据质量；优先解决高影响参数和失败模式。

## 10. V2 的最终判定

V2 完成后，应能回答以下问题，并允许答案为“否”或“无法识别”：

1. 在有来源的陕西—河南历史核心空间和 observed climate 下，V1 的机制状态是否仍成立？
2. 结论是否跨阈值带、参数后验、过程 seeds 和制度政策稳定？
3. 价格、赈济、迁徙、死亡、精英行为、欠饷和武装整合的关键中间量是否被真实测量？
4. 留出期失败来自数据、观测函数、参数还是结构？
5. 哪些新史料最能区分仍然竞争的机制？
6. 哪些反事实在模型中有效，却没有足够历史证据支持外推？
7. 任一机制卡能否从文字一路回溯到批次 hash、run、规则、参数和来源 locator？

只有这些问题得到可复核回答，V2 才应从“工程 RC”升级为“区域历史机制 RC”。
