# Late Ming Mechanism Lab V2.1 — 短封口与项目交接计划

日期：2026-09-16  
工作目录：`<REPO_ROOT>`（本仓库根目录）
当前起点：`main` at `eb3cd99571136f27b4cc58b2c24419d9390434b3`  
执行方式：每次只给 OMP 一个 phase 的提示词；每个 phase 独立审查、提交并 `STOP`。

---

## 1. 为什么是 V2.1，而不是全面 V3

V2 已完成一个可信的研究性闭环：V1 冻结区无漂移，历史核心、验证协议、结构臂、机制卡、
artifact lineage 和 release bundle 都存在；但 `Calibration`、`Sensitivity`、`Policy` 三个跨阶段门
未通过，因此项目正确地没有创建 `v0.2.0-rc1`。

V2.1 不以“把 9 个 gate 全部跑绿”为目标。它只解决会妨碍项目诚实封存的三件事：

1. P05 的 4 个 `root_seed` 在每个机制臂内产生同一个 simulation digest，40 份历史核心日志中
   没有非空 `rng_draw`。必须确认这是有意的确定性历史重放，还是 RNG 接线缺陷；四个 seed 不能继续
   被写作四个独立过程重复。
2. M002 的历史核心闸门对照和 M004 自己声明的证伪比较尚未完成；两者都可以用很少的确定性运行
   直接回答。
3. P07 的最终代码修复晚于正式 artifact，P06/P07 也都明确不收敛；V2.1 应把它们作为冻结的 pilot
   结果封存，而不是再烧一小时以上算力追逐一个预设答案。

完成 V2.1 后，项目应进入 maintenance/frozen 状态，研究工作转向新的模拟项目。只有在明确决定把
本项目发展成论文或长期区域模型时，才另立 V3。

---

## 2. 总目标与非目标

### 总目标

- 让每个“重复数”准确对应独立随机实现、确定性重放或参数/结构样本。
- 用最多四条新确定性轨迹完成 M002、M004 的决定性比较。
- 从 typed artifacts 重算 V2.1 机制卡附录和封存报告。
- 明确保留 Calibration、Sensitivity、Policy 的未完成状态，不创建 RC tag。
- 形成可供下一个项目复用的 handoff：哪些设施成熟、哪些结论不可外推、哪些工作不值得继续。

### 非目标

- 不扩展全国 GIS，不增加节点或第三地理区。
- 不引入新依赖、surrogate、神经 SBI、更多 LLM agents 或 UI。
- 不运行 P06 calibration ladder，不运行 P07 Morris/Sobol/CRN/tipping 大批次。
- 不调用 runtime LLM，不读取 API key，不扩充 fixture corpus。
- 不改变历史 outcome、阈值带、hold-out 窗口或 V1 冻结文件。
- 不为了创建 `v0.2.0-rc1` 修改 gate 或降低停止标准。
- 不把 simulation support 写成 historical truth。

---

## 3. 时间与资源预算

以下是命令与模拟的机器墙钟预算，不含 OMP 阅读、编码和审查时间：

| Phase | 主要运行 | 预算上限 |
| --- | --- | ---: |
| V2.1-P10 | 读取既有 artifacts、replicate audit、窄测试 | 5–10 分钟 |
| V2.1-P11 | 优先复用日志；必要时最多 4 条 240-tick 确定性轨迹、窄测试 | 5–10 分钟 |
| V2.1-P12 | 重算卡片/封存 bundle 两次、窄测试、ruff/mypy/baseline verify | 5–10 分钟 |
| **合计** | 不含 full pytest | **15–30 分钟** |

硬预算：

- V2.1 最多新增 **4 条** 240-tick 模拟轨迹。
- 任一 phase 的模拟命令超过 10 分钟就停止，保留 checkpoint/日志并报告原因。
- 不运行约 56 分钟的 full pytest；只运行变更覆盖到的测试集合。现有 P09 已记录完整套件
  `1007 passed, 2 deselected`，V2.1 不改核心物理机制时无需重复。
- 不联网，不运行 `live_ustc`。

---

## 4. 统一执行纪律

每个 phase 都必须：

1. 固定 cwd，并先读 `.omp/AGENTS.md`、`.omp/RULES.md`、本计划和上一 phase report。
2. 先写 `docs/exec-plans/V2.1-Pnn.md`，包含范围、非目标、输入、输出、失败条件和验收标准。
3. 只实现本 phase；不得提前开始下一 phase。
4. 新运行写入 `outputs/v2_1/`；不得覆写 `outputs/v2/`、V1 artifacts 或旧 phase reports。
5. 生成文档只能由生成器重写；不得手工改数字。
6. 使用至多一个普通 agent；结束前可用一个只读 `reviewer`。不得让多个 agent 重复扫描仓库。
7. 运行窄测试、必要的 ruff/mypy、`python -m late_ming_lab.release verify`，记录真实输出。
8. 写 `docs/phase-reports/V2.1-Pnn.md`，检查 `git diff`，做一个逻辑 commit，确认 clean tree，
   输出 completion summary，然后 `STOP`。

统一失败规则：

- 数据缺失不是零，未运行不是失败，重复执行不是独立样本。
- 发现既有 artifact 与报告不一致时，先报告并停止使用该结论；不得手工修 artifact。
- 若修复会改变核心状态转移、tick order、历史输入或冻结协议，超出 V2.1 范围；记录 blocker 并停止。

---

## 5. Phase 设计

## V2.1-P10 — Replicate Semantics & Pilot Freeze

### 核心问题

历史核心的多 seed 运行究竟是有意的确定性重放，还是应该随机却没有消费 RNG？P06/P07 的哪些结果
可以保留为 pilot，哪些字段或样本量表述必须降级？

### 工作内容

1. 建立只读 replicate audit，扫描：
   - `docs/v2/mechanism-variants.json`
   - `outputs/v2/p05/*/manifest.json`
   - `outputs/v2/p05/*/agent_events.parquet`
   - `outputs/v2/p06/posterior.json`
   - `outputs/v2/p07/sensitivity-manifest.json`
2. 对每个 P05 arm 输出：声明 seed 数、唯一 simulation digest 数、非空 `rng_draw` 行数、关键读数的
   唯一值数。结果写入 `docs/v2_1/replicate-audit.{json,md}`。
3. 检查 historical observed-forcing 路径是否按设计确定性：
   - 若所有会随机的机制在该 scenario 中都明确关闭，记录“deterministic replay by design”；
   - 若已有设计声明某个 subsystem 应消费 RNG 而实际没有，定为 blocker，不修核心机制，不进入 P11。
4. 建立 V2 pilot disposition：
   - P05 的四个 seed 改称一条确定性轨迹的重复执行；
   - P06 保持 `non-converged`，不得称 identified；
   - P07 记录最终代码与旧 artifact 的字段差异，保持 `pilot/non-converged`；
   - P08 保持 `pilot, 0 model decisions`。
5. 处理已知参数登记问题，但不发明新证据：
   - `interest_rate_monthly` 的 central `0.005` 位于声明 range `[0.01, 0.1]` 之外；
   - 19 个带 range 的参数未进入 calibration declaration 或 explicit exclusion。
   只允许通过显式 exclusion、移除无来源 range 或登记待办来恢复自洽；不得为了进入范围而静默改 central。
6. 增加防回归测试：报告不得把唯一 digest 数为 1 的多 seed 执行渲染成独立过程重复。

### 验收

- audit 数字全部由 artifact accessor/Polars 重算，人工不得填计数。
- 每个 P05 arm 的 seed、unique digest、RNG draw、关键输出唯一值均可追踪。
- 确定性是设计结论或 blocker，不能以“可能如此”结束。
- V2 原 artifacts 不变；`python -m late_ming_lab.release verify` 仍为 0 drift。
- 仅运行新增测试及相关 manifest/synthesis 测试；不跑模拟。
- phase report、只读 review、逻辑 commit、clean tree、`STOP`。

---

## V2.1-P11 — Two Decisive Contrasts

### 进入条件

只有 V2.1-P10 明确确认 historical core 的确定性是设计行为，才能执行本 phase。若 P10 是 blocker，
不得用更多运行掩盖它。

### 核心问题

1. 在 historical core 上打开危机/迁徙 gate，税基收缩是否仍比基线更大？
2. 精英积累/没收支是否比关闭精英信贷的 arm 造成更大的可评估税基收缩？

### 最小设计

先检查既有 P04/P05 日志能否精确实现预注册 contrast。只有配置、规则和 outcome 完全相同时才能复用；
相似 arm 不得改名冒充。

若必须新跑，最多四条、每臂一条确定性轨迹：

| Contrast | Arm A | Arm B | Primary reading |
| --- | --- | --- | --- |
| M002 | historical-core reference | 同输入、只打开卡片所指 gate | calibration/hold-out 各自的连续 `tax_base_contraction`；阈值 `breakdown` 仅作附加读数 |
| M004 | elite credit closed | foreclosure/accumulation enabled | `assessable_tax_base` 的窗口变化、foreclosure 数、土地转移量 |

约束：

- 使用同一确定性输入和配置；不把 seed 数当样本量。
- 每个 arm 保留 configuration diff、事件触发计数、no-op verdict 和完整 provenance。
- M002 先读连续结果，再将同一结果投射到冻结 threshold ensemble；不得先看阈值结论再选 arm。
- M004 必须直接实现卡片现有 falsifier；“51 次 foreclosure”只能证明分支存活，不能代替效应比较。
- 新 artifacts 写入 `outputs/v2_1/p11/`，汇总写入
  `docs/v2_1/decisive-contrasts.{json,md}`。

### 状态更新规则

- M002：只有 historical-core gate arm 的连续税基收缩稳定地区别于 reference，才保留
  `CONDITIONAL`；若无差异则降级为 `WEAK` 或 `REJECTED`，由预注册 falsifier 决定。
- M004：只有 accumulation arm 的可评估税基收缩大于 credit-closed arm，且 foreclosure/土地转移链
  非零，才允许从 `WEAK` 升级；否则保持 `WEAK` 或按 falsifier 降级。
- 不根据单个二值 `breakdown` 翻转状态。
- M001、M003、M005、M006 不在本 phase 改状态。

### 验收

- 复用或新增的每个 arm 都有精确 configuration diff；无效干预 fail closed。
- 最多 4 条新轨迹，总模拟墙钟不超过 10 分钟。
- 两个比较同时报告绝对值、配对差、触发链和阈值带读数。
- 测试覆盖 accessor、no-op detector、窗口隔离和两个状态判定；不得测试手写报告文本。
- phase report、只读 review、逻辑 commit、clean tree、`STOP`。

---

## V2.1-P12 — Closure Synthesis & Handoff

### 核心问题

在不伪装三个未通过 gate 已解决的前提下，怎样把项目封存成可复现、可引用、可转交的研究成果？

### 工作内容

1. 从 V2 原 artifacts、P10 replicate audit 和 P11 decisive contrasts 重算六张 V2.1 机制卡。
2. 每张卡必须给出：
   - `V2 status → V2.1 status`
   - 确定性/随机性语义和真实独立样本数
   - model evidence、historical support、historical challenge
   - falsifier、适用 dataset/window/policy/threshold band
   - source → normalized row → rule → run → statistic → card lineage
3. 生成：
   - `docs/mechanisms/v2_1/` 英文源卡与中文译卡
   - `docs/v2_1/closure-report.md`
   - `docs/v2_1/limitations.md`
   - `docs/v2_1/handoff.md`
   - `docs/v2_1/release-bundle.json`
4. handoff 明确区分：
   - 可复用基础设施：冻结协议、artifact lineage、no-op detector、历史核心构建器、链式中间量；
   - 已封存负结果：M003、P06/P07 non-convergence、P08 zero-decision pilot；
   - 未来只有新数据才能改变的事项：M006、历史死亡率、地区外推；
   - 不建议继续投入的事项：为了过 gate 重跑大梯度、扩大 runtime corpus、全国地理扩张。
5. bundle 绑定 code digest、commit、lock、V2+V2.1 artifacts、cards、reports 和翻译版本；连续生成两次
   必须 byte-identical。
6. 不创建 `v0.2.0-rc1` 或其他 release-candidate tag。若希望标记封存点，只在 phase report 中建议一个
   annotated archival tag，是否实际创建留给操作者另行决定。

### 最终验收

- 六张卡所有数字由 typed accessor 读取，不能从旧 Markdown 抄写。
- P05 的“4 seeds”不再被渲染成 4 个独立随机重复。
- Calibration、Sensitivity、Policy 继续显示 `unmet/frozen pilot`，不通过措辞漂白。
- V1 frozen verify 通过；targeted pytest、ruff、format check、mypy 通过。
- release generator 连续两次输出一致，仓库 clean。
- phase report、独立 review、逻辑 commit、`STOP`。至此 V2.1 结束。

---

## 6. 给 OMP 的分步骤对话提示词

### Prompt 1 — V2.1-P10 Replicate Semantics & Pilot Freeze

```text
你现在位于：
<REPO_ROOT>

只执行 V2.1-P10 — Replicate Semantics & Pilot Freeze。禁止开始 V2.1-P11。

先完整阅读：
- .omp/AGENTS.md
- .omp/RULES.md
- docs/OMP_UPGRADE_PLAN_V2_1.md
- docs/v2/phase-conventions.md
- docs/phase-reports/V2-P05.md 至 V2-P09.md
- docs/v2/limitations-v2.md

先写 docs/exec-plans/V2.1-P10.md，明确非目标、输入、输出、失败条件和 10 分钟机器运行预算。

任务：
1. 只读扫描 docs/v2/mechanism-variants.json、outputs/v2/p05 manifests/events、
   outputs/v2/p06/posterior.json、outputs/v2/p07/sensitivity-manifest.json。
2. 建立可重复的 artifact accessor/audit，生成 docs/v2_1/replicate-audit.json 和 .md。
   对每个 P05 arm 报告 declared seeds、unique simulation digests、非空 rng_draw 行数、
   关键读数的唯一值数。
3. 判断 historical observed-forcing 路径是“按设计确定性”还是“已有声明应随机但 RNG 未接通”。
   不能以含糊措辞结束。若是 RNG 接线 blocker，不修核心机制，写报告、commit、STOP，禁止进入 P11。
4. 将 P05 四 seed 语义、P06 non-converged、P07 final-code/stale-artifact 差异、
   P08 0 model decisions 写入 pilot disposition。
5. 核查 interest_rate_monthly central/range 冲突，以及带 range 参数未进入 calibration/exclusion 的问题。
   只允许显式 exclusion、移除无来源 range 或登记待办；不得静默移动 central 迎合 range。
6. 增加防回归测试：unique digest=1 的多 seed 执行不得显示为独立过程重复。

边界：
- 不跑任何模拟，不重写 outputs/v2，不改 V1，不跑 P06/P07，不调用 runtime LLM。
- 不新增依赖，不改变模型机制、tick order、协议或阈值。
- 使用至多一个普通 agent；结束前可用一个只读 reviewer。

验证：
- 运行新增 audit 测试和相关 manifest/synthesis 窄测试。
- 运行 ruff/format check；仅在改动触及类型接口时运行 mypy。
- 运行 python -m late_ming_lab.release verify，确认 V1 0 drift。

写 docs/phase-reports/V2.1-P10.md，记录真实命令和结果；reviewer 复核数字与结论；
检查 git diff，做一个逻辑 commit，确认 working tree clean，输出 completion summary，然后 STOP。
```

### Prompt 2 — V2.1-P11 Two Decisive Contrasts

```text
你现在位于：
<REPO_ROOT>

只执行 V2.1-P11 — Two Decisive Contrasts。禁止开始 V2.1-P12。

先读：
- .omp/AGENTS.md
- .omp/RULES.md
- docs/OMP_UPGRADE_PLAN_V2_1.md
- docs/phase-reports/V2.1-P10.md
- docs/phase-reports/V2-P03.md、V2-P04.md、V2-P05.md、V2-P09.md
- data/protocol/validation-protocol-v2.yaml
- data/protocol/model-comparison-register-v2.yaml
- docs/mechanisms/v2/M002.md、M004.md

进入门：V2.1-P10 必须确认 historical core 的确定性是设计行为。若 P10 报告 RNG 接线 blocker，
本 phase 不得执行，直接说明依赖未满足并 STOP。

先写 docs/exec-plans/V2.1-P11.md，冻结两个 contrast、连续 outcome、falsifier、最多四条新轨迹和
10 分钟模拟预算，再看结果。

任务：
1. 先检查 P04/P05 现有日志能否精确回答以下对照；配置或机制不完全相同就不得复用或改名：
   - M002 historical-core reference vs 只打开卡片所指 gate；读取连续 tax_base_contraction。
   - M004 elite-credit-closed vs foreclosure/accumulation；读取 assessable_tax_base 变化、
     foreclosure 和土地转移。
2. 若现有日志不足，最多新跑四条 240-tick 确定性轨迹，每 arm 一条；写到 outputs/v2_1/p11/。
3. 每个 arm 保存 configuration diff、触发事件、no-op verdict、完整 provenance。
4. M002 先比较连续税基收缩，再投射冻结 threshold ensemble；breakdown 只是附加读数。
5. M004 必须直接计算卡片 falsifier；不能用“分支触发 51 次”替代效应比较。
6. 生成 docs/v2_1/decisive-contrasts.json 和 .md，数字全部来自 typed accessor。
7. 按 docs/OMP_UPGRADE_PLAN_V2_1.md 的预注册规则给出 M002/M004 状态建议；不改其他四张卡。

边界：
- 不改 outcome、阈值带、hold-out 窗口、历史输入或核心状态转移。
- 不把 seed 当独立重复，不跑 calibration/sensitivity/runtime LLM，不新增依赖。
- 模拟累计超过 10 分钟即停止，保留已完成 artifact 并报告。

验证：
- 测试 accessor、configuration diff、no-op detector、窗口隔离、状态判定。
- 运行与改动直接相关的 pytest、ruff、format check、mypy；不跑 full pytest。
- 运行 python -m late_ming_lab.release verify。

写 docs/phase-reports/V2.1-P11.md，记录真实运行数、时间、结果和任何拒绝；只读 reviewer 重算两项
配对差并挑战状态；检查 git diff，做一个逻辑 commit，确认 clean tree，输出 summary，然后 STOP。
```

### Prompt 3 — V2.1-P12 Closure Synthesis & Handoff

```text
你现在位于：
<REPO_ROOT>

只执行 V2.1-P12 — Closure Synthesis & Handoff。这是 V2.1 最后一个 phase。

先读：
- .omp/AGENTS.md
- .omp/RULES.md
- docs/OMP_UPGRADE_PLAN_V2_1.md
- docs/phase-reports/V2.1-P10.md、V2.1-P11.md
- docs/v2_1/replicate-audit.json
- docs/v2_1/decisive-contrasts.json
- docs/phase-reports/V2-P06.md 至 V2-P09.md
- docs/mechanisms/v2/cards.yaml
- docs/v2/release-bundle.json、limitations-v2.md、unresolved-v2.md

先写 docs/exec-plans/V2.1-P12.md。目标是诚实封存和交接，不是把未通过 gate 跑绿。

任务：
1. 从 V2 artifacts、P10 audit、P11 contrasts 用 typed accessors 重算全部六张 V2.1 机制卡。
2. 生成 docs/mechanisms/v2_1/ 英文源卡与中文译卡。每卡写 V2→V2.1 状态、真实独立样本数、
   dataset/window/policy/threshold band、model/historical evidence、falsifier、uncertainty 和完整 lineage。
3. 生成 docs/v2_1/closure-report.md、limitations.md、handoff.md、release-bundle.json。
4. handoff 分开列出：可复用设施、封存负结果、只有新数据才能改变的事项、不建议继续投入的事项。
5. 明确保留 Calibration、Sensitivity、Policy 为 unmet/frozen pilot；P05 的四 seed 不得再写成四个
   独立随机重复。
6. bundle 绑定 code、commit、uv.lock、V2/V2.1 artifacts、cards、reports、翻译版本；连续生成两次，
   断言 byte-identical。
7. 不创建 v0.2.0-rc1 或任何 RC tag。可以在报告中建议 archival tag，但不得自动创建。

验证：
- 运行 V2.1 release/card/accessor 测试，以及受改动影响的旧 V2 synthesis tests。
- 运行 ruff check、ruff format --check、mypy、python -m late_ming_lab.release verify。
- 不跑 full pytest，不跑新的模型批次，不调用网络或 runtime LLM。

使用一个只读 reviewer，从原始 JSON/Parquet 重算关键数字，检查六张卡状态、replicate 语义、许可边界、
lineage 和 bundle determinism。修复审查发现后重跑对应窄测试。

写 docs/phase-reports/V2.1-P12.md，记录实际结果与仍未通过的 gates；检查 git diff，做一个逻辑 commit，
确认 clean tree，输出最终 completion summary，然后 STOP。V2.1 至此结束，禁止自行开始 V3。
```

---

## 7. 完成后的决策

V2.1-P12 完成后默认执行以下决定：

- 将本项目标记为 frozen/maintenance，保留为历史 ABM 方法与机制实验基础设施。
- 新研究问题另开项目，不继续向本仓库追加地理范围、LLM 行为或大规模敏感性批次。
- 若未来获得县级死亡、迁徙、价格、赈济或财政连续数据，再另写 V3 proposal；V3 必须先证明新数据
  能改变可识别性，而不是先扩大模型。
- 若没有新数据，M006 保持 `UNIDENTIFIED`、P06/P07 保持 `non-converged` 都是最终有效结果。
