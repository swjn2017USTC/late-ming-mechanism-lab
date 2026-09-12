# Late Ming Mechanism Lab  
## 晚明陕西—河南危机多层历史机制模拟

**OMP Engineering Plan v1.0**  
日期：2026-09-12  
项目建议目录名：`late-ming-mechanism-lab`  
Python package：`late_ming_lab`

---

# 0. 项目定位

本项目不是“明末历史游戏”，也不是“让一群 LLM 扮演历史人物聊天”。

它是一个：

> **Historical Mechanism Laboratory / 历史机制实验室**

目标是用可解释、可复现、可校准、可做干预实验的 Agent-Based Model，研究：

> **1625–1644 年陕西—河南地区，在持续农业冲击下，家庭生存、土地与债务、粮食市场、地方精英、财政汲取、赈济、军饷、人口迁移、逃兵与武装组织化如何发生跨尺度反馈，并在什么条件下使地方治理从“困难但尚可维持”跨越到自我强化的系统性失稳。**

核心认识论原则：

```text
Simulation is an argument, not evidence.
```

模拟不能代替史料。

模拟能够做的是：

```text
historical evidence
→ explicit assumptions
→ formal mechanism
→ simulation
→ emergent pattern
→ intervention / ablation
→ sensitivity
→ counterfactual
→ return to historical evidence
```

最终成果不是“明朝灭亡概率 = 83.7%”，而应是一批带条件、边界、反例和可证伪预测的：

```text
Mechanism Cards
```

例如：

- Fiscal Extraction Inversion
- Crisis Gating
- Fiscal-Military Ratchet
- Elite Mediation Bifurcation
- Insurgent Consolidation

---

# 1. 第一原则：不要模拟“整个明朝”

## 1.1 模拟窗口

```text
1625-01 → 1644-12
```

共：

```text
240 monthly ticks
```

1625–1626：

```text
warm-up / baseline stabilization
```

1627以后：

```text
historical shock period
```

---

## 1.2 空间范围

核心：

```text
Shaanxi + Henan
```

必要时增加边缘连接节点：

```text
Shanxi
Huguang
Sichuan
Beizhili
```

但这些不是完整模拟区，只作为：

- 人口迁移出口；
- 粮食贸易连接；
- 军事移动连接；
- 财政/军事外部条件。

第一版不模拟全国。

---

# 2. 模型层级

整个世界采用四层结构：

```text
MACRO
│
│ climate / central fiscal-military pressure
│
▼
MESO-ORGANIZATION
│
│ county government / army / market / elite / armed bands
│
▼
LOCAL SOCIAL SYSTEM
│
│ county / market / credit / grain stock
│
▼
MICRO
    household cohorts / merchants / soldiers
```

---

# 3. 不使用“一户一 Agent”的假精确

史料不允许我们合理地重建数十万户具体家庭。

因此核心 population unit 使用：

## Weighted Household Cohort

例如：

```text
county A
 ├─ landless labourer × 820 households
 ├─ poor smallholder × 1,450
 ├─ middle smallholder × 1,010
 ├─ wealthy farmer × 270
 └─ tenant household × 650
```

每一个 `HouseholdCohortAgent`：

```text
weight
land
labour
grain
silver
debt
rent
tax burden
social ties
coping state
migration state
```

而不是虚构：

```text
张三家有 1.47 石粮
```

---

# 4. 推荐规模

## Development scale

```text
3–5 counties
200–500 weighted household cohorts
5–20 elites
5–10 merchants
1–3 armies
0–10 armed bands
```

用于：

```text
unit / integration / debugging
```

## Regional baseline

```text
50–100 county nodes
2,000–5,000 household cohorts
100–300 elites
100–300 merchant actors
dozens of military / rebel organizations
```

这一规模应首先能够在 MacBook Air 上运行。

如果后期证明 cohort 模式不足，再考虑：

```text
Mesa-Frames + Polars
```

进行向量化。

禁止一开始制造：

```text
100,000 LLM peasants
```

---

# 5. 核心技术栈

```text
Mesa 3 stable
│
├── ABM engine
│
NetworkX
│
├── trade network
├── migration network
└── military movement network
│
Polars + Arrow
│
├── simulation tables
└── vectorized analysis
│
DuckDB
│
└── run warehouse / cross-run queries
│
Parquet
│
└── immutable simulation outputs
│
SALib
│
├── Morris screening
└── Sobol sensitivity
│
PyMC
│
└── ABC / SMC calibration
│
scikit-learn
│
└── mechanism / tipping-surface analysis
│
Mesa Solara
│
└── interactive visualization
│
USTC DeepSeek V4.1
│
└── bounded institutional decision layer
│
OpenCode Go
│
└── engineering only
│
Git
└── code + config + provenance
```

Mesa 当前 stable 分支仍是 Mesa 3，官方建议 Python ≥3.12，并可直接安装 `"mesa[rec]"`，其中包含可视化、绘图与网络相关推荐依赖。不要使用 Mesa 4 alpha。

---

# 6. 开发 LLM 与运行时 LLM 必须严格分离

这是本项目最重要的架构纪律之一。

## 6.1 Development-time

所有 coding：

```text
OpenCode Go
```

默认主模型：

```text
opencode-go/deepseek-v4.1-flash
```

OpenCode 当前官方 model ID 明确为：

```text
deepseek-v4.1-flash
```

OMP 中使用：

```text
opencode-go/deepseek-v4.1-flash
```

---

## 6.2 Runtime historical decision LLM

仅：

```text
USTC 次元计划
DeepSeek V4.1
```

不得使用：

```text
DeepSeek V4 Pro
DeepSeek V4 Flash legacy
Qwen
GLM
OpenCode Go
OpenAI
```

作为 runtime institutional policy。

如果：

```text
USTC V4.1 unavailable
```

则：

```text
FAIL CLOSED
```

或者明确切换：

```text
rule-based policy
```

不得 silently fallback 到其他 LLM。

---

# 7. USTC V4.1 的职责非常有限

LLM 不负责世界物理。

LLM 不决定：

```text
harvest
grain price
tax revenue
death
migration
battle outcome
rebel recruitment count
```

LLM 只能承担：

## Institutional Decision Policy

例如：

```text
Central Fiscal Authority
Shaanxi Provincial Authority
Henan Provincial Authority
selected county authorities
selected rebel leadership
```

而且只在：

```text
major decision event
```

触发。

不是每月每个 agent 调一次。

---

# 8. LLM 输入必须匿名化，阻止历史 hindsight

禁止：

```text
你是崇祯十二年的陕西巡抚……
李自成正在……
```

使用：

```text
Actor: GOV-P3

Region:
R17

Observed harvest:
-0.28

Observed tax arrears:
0.37

Military arrears:
4 months

Known armed groups:
3

Refugee inflow:
high

Available policy actions:
A. maintain extraction
B. partial remission
C. relief transfer
D. military reinforcement
E. request central aid
```

模型不知道：

```text
Ming
Chongzhen
Li Zicheng
1644
```

---

# 9. LLM 输出必须 constrained

返回：

```json
{
  "action": "PARTIAL_REMISSION",
  "intensity": 0.35,
  "priority": "STABILIZE_TAX_BASE",
  "rationale": "..."
}
```

其中：

```text
action
intensity
priority
```

必须通过 Pydantic schema。

`rationale`：

只保存用于解释；

不直接改变 simulation state。

---

# 10. LLM 完全没有工具权限

Runtime LLM：

```text
NO shell
NO browser
NO filesystem
NO Python execution
NO network tools
NO MCP
NO retrieval
```

唯一接口：

```text
structured state
↓
API
↓
structured action
```

simulation engine 才能改变世界。

---

# 11. 五个核心机制模块

## M1 Household Survival

家庭资源：

```text
land
labour
grain
silver
debt
credit
social ties
```

核心 coping ladder：

```text
stored grain
→ reduce discretionary consumption
→ borrow
→ sell movable assets
→ sell land
→ temporary migration
→ household migration
→ army / armed-band recruitment
```

禁止：

```text
anger > 0.7 → rebel
```

---

## M2 Market / Credit / Elite

县域：

```text
grain inventory
grain price
market access
transport cost
violence risk
credit supply
```

Local Elite：

```text
land
grain
silver
credit network
tax mediation
relief capacity
political protection
```

允许：

```text
lend
buy land
relieve
hide taxable resources
mediate tax
organize local defense
```

---

## M3 Fiscal / Governance

地方政府不是一个：

```text
state_capacity = 0.62
```

而拆成：

```text
TaxCollectionCapacity
InformationCapacity
ReliefCapacity
CoercionCapacity
LogisticsCapacity
```

税制至少拆：

```text
quota
collection effort
collection cost
actual receipts
arrears
```

---

## M4 Fiscal-Military

军队：

```text
strength
food
pay_due
pay_received
arrears
morale
cohesion
desertion
```

关键 feedback：

```text
unrest
→ military demand
→ fiscal demand
→ extraction
→ household stress

AND

fiscal shortage
→ military arrears
→ desertion
→ recruitment pool
→ armed groups
```

---

## M5 Armed Organization

开始时没有：

```text
LiZichengAgent
```

只有：

```text
ArmedBand
```

属性：

```text
size
food
arms
mobility
cohesion
local support
network ties
territorial access
```

允许：

```text
split
merge
recruit
move
raid
avoid
fight
negotiate
```

最终观察：

```text
diffuse violence
→ organizational consolidation
```

是否自行出现。

---

# 12. 三张网络

NetworkX 分别维护：

```text
G_trade
G_migration
G_military
```

绝不能只有一个：

```text
county adjacency graph
```

同两地之间：

```text
trade_cost
migration_cost
military_cost
```

必须可以不同。

NetworkX 当前 stable 版本要求 Python 3.11–3.14，因此 Python 3.12 与 Mesa 配置兼容。

---

# 13. 时间调度

每个 tick：

```text
1 month
```

推荐 step order：

```text
01 climate update
02 agricultural state
03 grain production / harvest if relevant
04 household consumption
05 market clearing
06 credit / debt
07 taxation
08 relief
09 migration
10 military finance
11 desertion
12 armed-group recruitment
13 armed-group movement/actions
14 violence consequences
15 institutional decisions
16 bookkeeping
17 data collection
```

step order 必须：

```text
explicit
versioned
tested
```

不能由 Mesa 默认顺序偶然决定。

---

# 14. Randomness 必须分流

禁止：

```python
random.seed(42)
```

全世界共用一个随机流。

使用：

```text
root SeedSequence
├── climate_rng
├── household_rng
├── market_rng
├── migration_rng
├── military_rng
├── rebel_rng
└── decision_rng
```

从而支持：

```text
common random numbers
```

用于反事实比较。

---

# 15. 每一个 run 都必须可重放

保存：

```text
run_id
git_sha
engine_version
config_hash
parameter_hash
root_seed
subsystem_seeds
scenario_id
policy_id
llm_enabled
llm_model_id
llm_prompt_version
start_timestamp
```

输出：

```text
outputs/runs/<run_id>/
├── manifest.json
├── config.snapshot.yaml
├── parameters.snapshot.parquet
├── county_timeseries.parquet
├── macro_timeseries.parquet
├── agent_events.parquet
├── decision_trace.jsonl
└── summary.json
```

---

# 16. Event Log 是一级公民

重大状态改变必须可解释：

```json
{
  "tick": 87,
  "event": "HOUSEHOLD_MIGRATION",
  "agent_id": "...",
  "region": "...",
  "trigger": {
    "subsistence_gap": 0.31,
    "debt_ratio": 1.8
  },
  "rule_version": "migration-v3",
  "rng_draw": 0.184,
  "outcome": "MIGRATE_R17_R19"
}
```

---

# 17. 关键 invariant

至少：

## Resource invariants

```text
grain cannot become negative
silver cannot appear without explicit source
```

## Population invariants

```text
population_previous
=
population_current
+ deaths
+ net_outmigration
± explicit external flows
```

## Military invariants

```text
deserters must leave army population
rebel recruitment must come from eligible population pool
```

## Fiscal invariants

```text
actual receipts <= collectible base under defined rule
```

## Reproducibility

```text
same code
same config
same seed
same policy
→ same output
```

除 live LLM 外。

Live LLM decision traces必须能够：

```text
record → replay
```

---

# 18. 数据认识论

沿用：

```text
A / B / C / D / S
```

## A

直接、高质量历史证据。

## B

多个可靠来源交叉支持。

## C

由历史数据或成熟研究推算。

## D

弱证据机制参数 / plausible prior。

## S

纯模型假设。

每个 parameter card：

```yaml
id:
name:
definition:
unit:
mechanism:
level:
evidence_grade:
central:
range:
distribution:
sources:
reasoning:
uncertainty:
sensitivity_priority:
version:
```

---

# 19. Historical Grounding 与 modern scholarship

历史资料流：

```text
raw source
→ normalized evidence
→ evidence ledger
→ parameter / rule claim
→ simulation rule
```

禁止：

```text
论文说 X
→ agent.py 写死 X
```

现代研究可以提出 mechanism。

但：

```text
mechanism claim
```

必须和：

```text
code implementation
```

之间保留 ledger。

项目可以复用此前 Academic Literature Pipeline 的：

```text
registry
digest
ledger
claim-delta
human acquisition gate
```

但不可直接复制旧项目的具体历史结论、私人 PDF 或项目特定 claim。此前 handoff 已经明确区分 COPY / CONFIGURE / REBUILD / DO NOT COPY。

---

# 20. 校准原则

绝对不要寻找：

```text
best parameter set
```

目标：

```text
P(theta | historical patterns)
```

优先：

```text
Approximate Bayesian Computation
+
Sequential Monte Carlo
```

PyMC `Simulator` 就是为 simulator-based ABC 与 `sample_smc()` 准备的。

---

# 21. Pattern-oriented calibration

不能只拟合：

```text
1644 collapse
```

同时匹配多个 pattern，例如：

```text
drought spatial pattern
famine timing
grain-price volatility
migration proxy
tax arrears
rebel-event spatial spread
armed-group concentration
military arrears
```

一个机制必须同时解释多个 pattern。

---

# 22. Historical Hold-out

建议：

```text
1625–1634
training / calibration
```

```text
1635–1642
hold-out
```

```text
1643–1644
hard extrapolation
```

不得：

```text
看完 1644 → 调参数 → 宣布预测成功
```

---

# 23. Sensitivity

第一层：

```text
Morris screening
```

从几十个参数筛：

```text
~10–15 influential parameters
```

第二层：

```text
Sobol
```

研究：

```text
first-order effect
interaction effect
total effect
```

SALib 官方直接支持 Morris、Sobol、FAST、PAWN 等全局敏感性方法。

---

# 24. Ablation

至少：

```text
NO_DROUGHT
NO_EXTRACTION_ESCALATION
FULL_MILITARY_PAY
HIGH_RELIEF
NO_ELITE_CREDIT
NO_TRADE_DISRUPTION
NO_BAND_MERGER
LOW_REPRESSION
OPEN_MIGRATION_EXIT
```

---

# 25. Counterfactual 绝不能只跑一个 seed

每个：

```text
scenario × policy
```

运行：

```text
ensemble
```

输出：

```text
distribution
confidence interval
tipping probability
```

而不是：

```text
一条戏剧化 timeline
```

---

# 26. 最终机制卡 Schema

```yaml
mechanism_id:
name:
status:
micro_conditions:
meso_conditions:
trigger:
causal_chain:
macro_outcome:
necessary_conditions:
facilitating_conditions:
counterexamples:
time_lag:
parameter_region:
ablation_evidence:
sensitivity_evidence:
historical_evidence:
holdout_performance:
novel_prediction:
falsification_test:
uncertainty:
```

---

# 27. Repository 结构

```text
late-ming-mechanism-lab/
│
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env.example
│
├── .omp/
│   ├── AGENTS.md
│   ├── RULES.md
│   ├── config.yml
│   └── agents/
│       ├── repo-scout.md
│       ├── architect.md
│       ├── implementer.md
│       ├── reviewer.md
│       └── plan-critic.md
│
├── docs/
│   ├── OMP_ENGINEERING_PLAN.md
│   ├── architecture/
│   ├── adr/
│   ├── epistemics/
│   ├── mechanisms/
│   ├── exec-plans/
│   └── phase-reports/
│
├── src/
│   └── late_ming_lab/
│       ├── core/
│       │   ├── model.py
│       │   ├── clock.py
│       │   ├── rng.py
│       │   ├── events.py
│       │   └── config.py
│       │
│       ├── actors/
│       │   ├── households.py
│       │   ├── elites.py
│       │   ├── merchants.py
│       │   ├── government.py
│       │   ├── military.py
│       │   └── armed_groups.py
│       │
│       ├── systems/
│       │   ├── agriculture.py
│       │   ├── households.py
│       │   ├── markets.py
│       │   ├── credit.py
│       │   ├── taxation.py
│       │   ├── relief.py
│       │   ├── migration.py
│       │   ├── military_finance.py
│       │   ├── insurgency.py
│       │   └── violence.py
│       │
│       ├── networks/
│       │   ├── trade.py
│       │   ├── migration.py
│       │   └── military.py
│       │
│       ├── policies/
│       │   ├── base.py
│       │   ├── rules.py
│       │   ├── utility.py
│       │   ├── random_policy.py
│       │   └── ustc_v41.py
│       │
│       ├── evidence/
│       │   ├── registry.py
│       │   ├── parameters.py
│       │   └── provenance.py
│       │
│       ├── calibration/
│       ├── experiments/
│       ├── analysis/
│       ├── storage/
│       ├── cli/
│       └── ui/
│
├── data/
│   ├── raw/
│   │   ├── public/
│   │   └── private/
│   ├── normalized/
│   ├── parameters/
│   ├── historical_patterns/
│   └── scenarios/
│
├── sources/
│   ├── registry/
│   ├── primary/
│   └── literature/
│
├── experiments/
│   ├── ablations/
│   ├── sensitivity/
│   ├── counterfactuals/
│   └── calibration/
│
├── outputs/
│   ├── runs/
│   ├── analysis/
│   └── reports/
│
├── scripts/
│   ├── data/
│   ├── experiments/
│   └── hpc/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── invariants/
    ├── regression/
    ├── policies/
    └── fixtures/
```

---

# 28. OMP 模型配置

## 28.1 原则

OpenCode Go 是：

```text
coding provider
```

不是：

```text
runtime simulation intelligence
```

推荐：

```text
default / task / implementer / architect
→ DeepSeek V4.1 Flash via OpenCode Go
```

便宜任务：

```text
MiMo-V2.5
```

独立审查：

```text
GLM-5.3-Flash
Qwen3.8-Flash
```

这样避免：

```text
same-family correlated review
```

---

## 28.2 推荐 `.omp/config.yml`

**写入之前必须运行：**

```bash
omp config list
```

确认当前 OMP schema。

建议形态：

```yaml
modelRoles:
  default: opencode-go/deepseek-v4.1-flash
  smol: opencode-go/mimo-v2.5
  tiny: opencode-go/mimo-v2.5
  task: opencode-go/deepseek-v4.1-flash
  plan: opencode-go/deepseek-v4.1-flash
  slow: opencode-go/deepseek-v4.1-flash
  advisor: opencode-go/glm-5.3-flash
  commit: opencode-go/mimo-v2.5

cycleOrder:
  - smol
  - default
  - slow

advisor:
  enabled: false
  subagents: false

task:
  agentModelOverrides:
    repo-scout: opencode-go/mimo-v2.5
    implementer: opencode-go/deepseek-v4.1-flash
    architect: opencode-go/deepseek-v4.1-flash
    plan-critic: opencode-go/qwen3.8-flash
    reviewer: opencode-go/glm-5.3-flash
```

如果 schema 有变化：

```text
以 omp config list 为准
```

绝不能让 agent 自己猜。

写完 `.omp/config.yml`：

```text
停止当前 OMP session
重新启动
```

---

# 29. OMP Agent Roles

## repo-scout

职责：

```text
locate files
inspect narrow context
find existing interfaces
report only
```

禁止修改代码。

---

## architect

只处理：

```text
cross-module interfaces
state transition architecture
RNG architecture
event sourcing
calibration interface
policy abstraction
storage schema
```

不得用于普通 bug。

---

## implementer

主要 coding agent。

职责：

```text
implement scoped issue
write tests
run tests
update narrowly relevant docs
```

---

## plan-critic

只负责：

```text
challenge assumptions
scope creep
missing failure modes
identifiability problems
```

---

## reviewer

独立读：

```text
git diff
tests
invariants
acceptance criteria
```

返回：

```text
BLOCKER
MAJOR
MINOR
```

---

# 30. OpenCode Go 成本纪律

官方当前 Go 文档已经改成：

```text
model-specific monthly limits
5-hour = monthly limit × 20%
weekly = monthly limit × 50%
```

而且额度可能变化，所以：

```text
console > hard-coded old numbers
```

为权威。

工程纪律：

```text
ordinary issue:
0–1 subagent

complex issue:
<=2 subagents

phase gate:
最多 3，但职责不能重复
```

禁止：

```text
3个agent同时读整个repo
```

禁止：

```text
architect → reviewer → critic → advisor
```

无意义链式 fan-out。

---

# 31. Advisor

默认：

```text
advisor.enabled = false
advisor.subagents = false
```

只有：

```text
真实复杂 bug
或 milestone architecture audit
```

才临时启用。

---

# 32. 手工初始化：系统工具

Mac 上先运行：

```bash
git --version
python3 --version
uv --version
opencode --version
omp --version
```

如果没有 `uv`：

```bash
brew install uv
```

如果 Git 不存在：

```bash
xcode-select --install
```

建议：

```text
Python 3.12
```

执行：

```bash
uv python install 3.12
```

---

# 33. 创建 repo

```bash
mkdir -p ~/OMP/late-ming-mechanism-lab
cd ~/OMP/late-ming-mechanism-lab

git init -b main
```

如果你的项目习惯不是 `~/OMP`，换成自己的目录即可。

---

# 34. 初始化 Python

```bash
uv init --python 3.12
uv venv --python 3.12
source .venv/bin/activate
```

---

# 35. 安装核心包

```bash
uv add \
  "mesa[rec]" \
  "networkx[default]" \
  numpy \
  scipy \
  polars \
  pyarrow \
  duckdb \
  pydantic \
  pydantic-settings \
  pyyaml \
  typer \
  rich \
  openai \
  httpx \
  tenacity \
  SALib \
  pymc \
  arviz \
  matplotlib \
  scikit-learn \
  joblib
```

DuckDB 当前 Python client 支持 Python ≥3.9；这里采用 Python 3.12 与其余栈兼容。

---

# 36. 安装开发依赖

```bash
uv add --dev \
  pytest \
  pytest-cov \
  pytest-xdist \
  hypothesis \
  ruff \
  mypy \
  jupyterlab
```

---

# 37. GIS 依赖

先装：

```bash
uv add \
  geopandas \
  shapely \
  pyproj
```

暂时不要：

```text
GDAL source build
```

除非后续真实数据格式迫使我们使用。

---

# 38. 创建最低目录

```bash
mkdir -p \
  .omp/agents \
  docs/{architecture,adr,epistemics,mechanisms,exec-plans,phase-reports} \
  src/late_ming_lab \
  tests/{unit,integration,invariants,regression,policies,fixtures} \
  data/{raw/public,raw/private,normalized,parameters,historical_patterns,scenarios} \
  sources/{registry,primary,literature} \
  experiments/{ablations,sensitivity,counterfactuals,calibration} \
  outputs/{runs,analysis,reports} \
  scripts/{data,experiments,hpc}
```

---

# 39. `.gitignore`

人工创建：

```bash
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.py[cod]

.pytest_cache/
.hypothesis/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

.env
.env.*
!.env.example

.DS_Store

outputs/runs/
outputs/analysis/

data/raw/private/
sources/literature/private/
sources/literature/inbox/

*.duckdb
*.duckdb.wal

.ipynb_checkpoints/
EOF
```

---

# 40. USTC `.env.example`

```bash
cat > .env.example <<'EOF'
USTC_LLM_BASE_URL=https://api.llm.ustc.edu.cn/v1
USTC_LLM_API_KEY=
USTC_LLM_MODEL=
USTC_LLM_ENABLED=0
EOF

cp .env.example .env
chmod 600 .env
```

API Key 不得 commit。

科大官方指南同样明确要求 API Key 不上传 GitHub、不写入前端。

---

# 41. 手工获取 USTC V4.1 的准确 model ID

由于平台公告新于公开 guide，**这一步以你账户 `/v1/models` 为唯一权威。**

Mac zsh：

```bash
read -s "USTC_LLM_API_KEY?USTC LLM API key: "
echo
export USTC_LLM_API_KEY

export USTC_LLM_BASE_URL="https://api.llm.ustc.edu.cn/v1"
```

查看全部：

```bash
curl -s \
  "$USTC_LLM_BASE_URL/models" \
  -H "Authorization: Bearer $USTC_LLM_API_KEY" \
  | python3 -m json.tool
```

筛选 DeepSeek：

```bash
curl -s \
  "$USTC_LLM_BASE_URL/models" \
  -H "Authorization: Bearer $USTC_LLM_API_KEY" \
  | python3 -c '
import sys, json
x=json.load(sys.stdin)
for m in x.get("data", []):
    mid=m.get("id","")
    if "deepseek" in mid.lower():
        print(mid)
'
```

然后：

> **手工确认平台公告中新上线 V4.1 对应的准确 ID。**

写入：

```text
.env
```

例如：

```text
USTC_LLM_MODEL=<平台实际返回的V4.1模型ID>
```

不要根据本文猜。

不要写：

```text
deepseek-v4-pro
```

做 fallback。

---

# 42. USTC 最小 smoke test

填好 `.env` 后：

```bash
set -a
source .env
set +a
```

运行：

```bash
curl \
  "$USTC_LLM_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $USTC_LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$USTC_LLM_MODEL\",
    \"messages\": [
      {
        \"role\": \"user\",
        \"content\": \"Return only: V41_OK\"
      }
    ],
    \"temperature\": 0
  }"
```

确认成功以后：

```text
USTC_LLM_ENABLED=0
```

仍保持关闭。

直到 P11。

---

# 43. OpenCode Go 手工确认

在 OpenCode：

```text
/connect
```

选择：

```text
OpenCode Go
```

然后：

```text
/models
```

确认存在：

```text
DeepSeek V4.1 Flash
```

model ID：

```text
deepseek-v4.1-flash
```

OpenCode 官方当前文档还特别要求 agentic client 保持稳定 session identity；如果再次出现你以前遇到的 `x-opencode-session` 类错误，优先升级 OpenCode/OMP 并检查 session forwarding，而不是怀疑模型额度。

---

# 44. 初始 Git commit

把本计划保存为：

```text
docs/OMP_ENGINEERING_PLAN.md
```

然后：

```bash
git add .
git status
git commit -m "chore: bootstrap late-ming mechanism lab"
```

此时要求：

```bash
git status
```

显示：

```text
working tree clean
```

然后才启动 OMP。

---

# 45. Git 工作纪律

每一个 Phase：

```text
one phase
→ one or several logical commits
→ phase report
→ final clean tree
→ STOP
```

禁止：

```text
P03还没验收 → 自动开始P04
```

每个 phase 结束建议：

```bash
git log --oneline -5
git status
```

---

# 46. Phase Roadmap

```text
P00  Bootstrap / Constitution
P01  Simulation Kernel / Reproducibility
P02  Historical Space / Time / Climate
P03  Household Survival / Agriculture
P04  Market / Credit / Local Elite
P05  Fiscal Extraction / Governance / Relief
P06  Military Finance / Armed Organization
P07  Integrated Crisis Engine
P08  Historical Evidence / Parameter Registry
P09  Calibration / Historical Hold-out
P10  Ablation / Sensitivity / Counterfactual
P11  USTC V4.1 Institutional Decision Layer
P12  Decision-Policy Robustness
P13  Mechanism Discovery / Mechanism Cards
P14  Visualization / HPC / Release Candidate
```

---

# 47. 每个 Phase 的固定工作流

每个 phase：

```text
1. read this plan
2. read relevant phase report
3. inspect narrow repo context
4. write <=1-page phase scope
5. state non-goals
6. define acceptance criteria
7. implement smallest valid version
8. unit tests
9. invariants
10. regression seeds
11. independent review if needed
12. docs
13. PHASE_PXX_REPORT.md
14. git diff
15. commit
16. STOP
```

---

# 48. P00 — Bootstrap / Constitution

## 目标

建立：

```text
project skeleton
OMP rules
role routing
domain vocabulary
epistemic rules
coding standards
CI-like local checks
```

不建立实际历史模型。

## Acceptance

必须：

```text
pytest passes
ruff passes
mypy baseline passes
OMP routing documented
USTC runtime disabled
repo clean
```

---

# 49. P00 对话提示词

```text
你现在位于 late-ming-mechanism-lab repo。

先完整阅读：
docs/OMP_ENGINEERING_PLAN.md

只执行 P00 — Bootstrap / Constitution。
禁止开始 P01。

本阶段任务：

1. 检查当前 repo、pyproject、uv.lock 和 Git 状态。
2. 运行 `omp config list`，核实当前 OMP schema；不要凭记忆猜配置键。
3. 建立最小 `.omp/`：
   - AGENTS.md
   - RULES.md
   - config.yml
   - agents/repo-scout.md
   - agents/architect.md
   - agents/implementer.md
   - agents/plan-critic.md
   - agents/reviewer.md
4. Coding 主模型固定为 OpenCode Go DeepSeek V4.1 Flash。
5. repo-scout 使用 MiMo-V2.5。
6. reviewer 使用 GLM-5.3-Flash。
7. plan-critic 使用 Qwen3.8-Flash。
8. advisor 默认 disabled；subagents 默认 <=2。
9. 建立：
   - docs/architecture/system-overview.md
   - docs/epistemics/model-epistemics.md
   - docs/epistemics/evidence-grades.md
   - docs/architecture/runtime-llm-boundary.md
10. 明确：
    OpenCode Go = development only；
    USTC DeepSeek V4.1 = runtime institutional policy only。
11. USTC API key 不得读取、打印、commit。
12. 运行时 LLM 默认关闭。
13. 建立 minimal package import 与 CLI smoke test。
14. 建立 pytest / ruff / mypy 最小配置。
15. 生成 docs/phase-reports/P00.md。

P00 禁止：
- 写 household simulation；
- 写 market；
- 接 CHGIS；
- 调 live USTC；
- 做 UI；
- 做 calibration；
- 添加没有当前用途的大型 framework。

完成后：
- 跑 tests/lint/type checks；
- 查看 git diff；
- 做一个或多个逻辑清晰的 commit；
- 确保 working tree clean；
- 输出 P00 completion summary；
- STOP，不得开始 P01。
```

---

# 50. P01 — Simulation Kernel / Reproducibility

建立：

```text
SimulationConfig
Clock
RNGStreams
Event
RunManifest
state snapshots
storage interface
```

以及：

```text
same seed → same run
```

不要加入历史内容。

---

# 51. P01 提示词

```text
阅读：
docs/OMP_ENGINEERING_PLAN.md
docs/phase-reports/P00.md
相关 architecture docs。

只执行 P01。

目标：建立历史无关的 deterministic simulation kernel。

必须实现：

1. SimulationConfig（Pydantic）。
2. monthly Clock。
3. root SeedSequence + subsystem RNG streams。
4. immutable event representation。
5. event logger。
6. RunManifest：
   git SHA / config hash / seed / engine version / policy id。
7. Parquet output 基础。
8. DuckDB query helper。
9. replay-compatible event structure。
10. CLI：
    `late-ming-lab smoke-run`
11. 固定 regression seed。
12. tests：
    deterministic reproducibility；
    RNG stream independence；
    manifest round-trip；
    config validation；
    event serialization。

不要实现：
- historical counties；
- agents；
- markets；
- USTC；
- calibration。

要求：
同 config + seed 必须 byte-level 或 semantic-level reproducible。

生成：
docs/phase-reports/P01.md

完成、commit、clean tree 后 STOP。
```

---

# 52. P02 — Historical Space / Time / Climate

实现：

```text
CountyNode
three NetworkX graphs
external nodes
climate shock interface
agricultural season calendar
```

不要模拟农户。

地理采用：

```text
historical administrative seats
+
approximate catchments
```

不要制造假精确县界。

---

# 53. P02 提示词

```text
只执行 P02。

目标：
建立 1625–1644 的空间—时间—外生环境骨架。

必须：

1. CountyNode schema。
2. Shaanxi / Henan county-node representation。
3. trade / migration / military 三张独立 NetworkX 图。
4. edge 分别保存：
   distance/cost/capacity/risk。
5. external boundary nodes。
6. monthly agricultural calendar。
7. ClimateShock interface：
   baseline / observed-historical / synthetic modes。
8. 数据 provenance 字段。
9. toy fixture：
   5 county nodes。
10. regional fixture schema：
   可以扩展到 50–100 nodes。
11. tests：
   graph separation；
   connectivity；
   no invalid edge cost；
   climate replay；
   monthly calendar。

真实历史数据暂时只建立 adapter/schema；
不要未经 provenance 大规模填数据。

不要：
- households；
- market clearing；
- rebels；
- LLM。

写 ADR：
为什么使用 node/catchment 而非假精确 historical polygons。

生成 P02 report、commit、STOP。
```

---

# 54. P03 — Household Survival / Agriculture

首次产生微观动态。

实现：

```text
WeightedHouseholdCohort
yield
consumption
assets
debt
coping ladder
migration eligibility
```

但暂不真正迁移。

---

# 55. P03 提示词

```text
只执行 P03。

目标：
让 weighted household cohorts 在农业冲击下产生可解释的生存策略。

实现：

1. HouseholdCohortAgent。
2. weight 表示 cohort 对应户数。
3. land/labour/grain/silver/debt。
4. harvest production function。
5. subsistence requirement。
6. household balance sheet。
7. coping ladder：
   stored grain
   consumption reduction
   borrowing request
   movable asset sale
   land sale
   temporary migration eligibility
   permanent migration eligibility
   recruitment eligibility
8. 禁止 anger/rebellion scalar。
9. 每个 transition 写 event log。
10. mass-balance invariants。
11. property tests：
   无负粮；
   无无来源资产；
   同 seed 可复现。
12. toy shock experiment：
   normal harvest vs severe shock。

不要：
- actual migration；
- rebels；
- sophisticated market；
- LLM。

输出一个小型分析：
shock severity → cohort distress distribution。

P03 report、review、commit、STOP。
```

---

# 56. P04 — Market / Credit / Local Elite

建立：

```text
grain market
merchant flows
elite credit
land transfer
relief-like private buffering
```

---

# 57. P04 提示词

```text
只执行 P04。

实现：

1. county grain inventory。
2. endogenous local grain price。
3. intercounty trade。
4. transport cost + violence-risk placeholder。
5. MerchantAgent 或 aggregated merchant layer。
6. LocalEliteAgent。
7. elite lending。
8. debt servicing。
9. land sale / purchase。
10. private relief / grain release。
11. tax mediation placeholder interface。
12. trade-network disruption hook。

测试机制：

A. 正常市场整合是否降低空间价格离散度？
B. transport cost 增加是否减少 trade flow？
C. severe shock 下 credit 是否延迟 household collapse？
D. credit 是否可能增加长期 land concentration？

不要写死：
“士绅好/坏”。

输出：
价格离散、土地分布、债务分布。

新增 invariants 和 regression seeds。

P04 report、commit、STOP。
```

---

# 58. P05 — Fiscal Extraction / Governance / Relief

核心中观系统。

---

# 59. P05 提示词

```text
只执行 P05。

建立地方财政—治理层。

实现：

1. CountyGovernment。
2. state capacity 拆为：
   TaxCollectionCapacity
   InformationCapacity
   ReliefCapacity
   CoercionCapacity
   LogisticsCapacity
3. tax quota。
4. collection effort。
5. collection cost。
6. actual receipts。
7. tax arrears。
8. tax base。
9. official relief。
10. relief inventory / fiscal cost。
11. elite tax mediation。
12. extraction escalation policy。

禁止：
state_capacity 单一 scalar。

加入 experiment：

逐渐提高 extraction pressure，
观察：
nominal quota
actual receipt
tax base
migration eligibility
asset depletion。

本阶段不要宣称存在 Fiscal Extraction Inversion。
只提供测试它的数据。

必须测试：
财政 accounting；
税收来源；
无重复征收；
relief conservation。

P05 report、commit、STOP。
```

---

# 60. P06 — Military Finance / Armed Organization

---

# 61. P06 提示词

```text
只执行 P06。

实现：

GovernmentMilitaryUnit：
strength
food
pay_due
pay_received
arrears
morale
cohesion
desertion

ArmedBand：
size
food
arms
mobility
cohesion
network
territorial access

实现：

1. military payroll。
2. arrears accumulation。
3. desertion probability。
4. deserter destination。
5. recruitment pool。
6. ArmedBand creation。
7. recruitment。
8. movement。
9. raid abstraction。
10. split。
11. merge。
12. suppression abstraction。

禁止：
- 创建 LiZichengAgent；
- 写真实军事战术；
- 具体攻城/武器教程。

关键 tests：

deserter population conservation；
recruitment source conservation；
band split/merge conservation；
same-seed deterministic。

建立指标：

number_of_bands
largest_band_share
band_size_distribution
desertion_rate

P06 report、commit、STOP。
```

---

# 62. P07 — Integrated Crisis Engine

这是第一次真正组合系统。

---

# 63. P07 提示词

```text
只执行 P07。

目标：
把 P02–P06 连接成第一版完整 historical mechanism sandbox。

不得添加新大型 subsystem。

连接：

climate
→ agriculture
→ households
→ market/credit
→ taxation/relief
→ migration
→ military finance
→ armed bands
→ violence
→ trade disruption
→ household/fiscal feedback

实现真实 migration。

建立：

1. monthly scheduler。
2. explicit step order。
3. system dependency diagram。
4. integrated event trace。
5. toy 5-county scenario。
6. medium 12-county scenario。
7. 240-tick run。
8. fixed-seed regression suite。

输出指标：

household distress distribution
land concentration
migration
grain price dispersion
actual tax receipts
tax base
military arrears
desertion
number of armed groups
largest band share
governance failure indicators

禁止调参数去复制明末史。

本阶段问题只有：

“模型是否作为一个守恒、可解释、可复现的动态系统正常工作？”

做 independent reviewer。

P07 report、commit、STOP。
```

---

# 64. P08 — Historical Evidence / Parameter Registry

现在才开始认真塞历史材料。

---

# 65. P08 提示词

```text
只执行 P08。

这是 evidence phase，不是“大量搜论文然后总结”。

目标：
建立 simulation claim → evidence → parameter/rule provenance。

建立：

sources/registry
evidence ledger
parameter cards
historical pattern registry

证据等级：
A/B/C/D/S。

至少建立以下 evidence clusters：

1. drought / climate；
2. famine；
3. agriculture；
4. population/migration；
5. grain market/prices；
6. land/debt/local elites；
7. taxation / additional levies；
8. relief；
9. military finance / arrears；
10. rebellions / armed groups。

每条 simulation rule 必须能够关联：
evidence-backed / theoretically assumed / exploratory。

允许复用已有 Academic-Search 能力与其 schema，
但：
- 不复制其他项目具体 claims；
- 不复制 private PDFs；
- institution-auth acquisition 保持 human-only；
- modern scholarship 与 primary material 分层。

建立：
historical_patterns/*.yaml

用于未来 pattern-oriented calibration。

不要：
- 调模型参数拟合；
- 修改机制以迎合历史结果；
- 使用 LLM 自动制造不存在的数字。

生成：
evidence coverage report
parameter uncertainty report
evidence gaps

P08 report、commit、STOP。
```

---

# 66. P09 — Calibration / Hold-out

---

# 67. P09 提示词

```text
只执行 P09。

冻结 P08 evidence registry 的版本。

划分：

1625–1634 calibration
1635–1642 hold-out
1643–1644 hard extrapolation

建立：

1. summary statistics API。
2. historical pattern distance metrics。
3. prior distributions。
4. ABC simulator wrapper。
5. PyMC Simulator integration。
6. SMC small-scale calibration。
7. posterior parameter samples。
8. posterior predictive runs。

重要：

不要寻找单一 best fit。
保存 posterior / accepted ensembles。

先使用小规模模型验证 pipeline，
不要直接跑巨大计算。

hold-out 数据不得用于 calibration objective。

报告：

- 哪些参数 identifiable；
- 哪些参数 equifinal；
- 哪些 pattern 模型无法同时匹配；
- calibration failure 也必须报告。

P09 report、commit、STOP。
```

---

# 68. P10 — Ablation / Sensitivity / Counterfactual

正式“做历史实验”。

---

# 69. P10 提示词

```text
只执行 P10。

目标：
从“模型像不像历史”转向“什么机制真正必要”。

建立 experiment runner。

必须支持：

Ablation:
NO_DROUGHT
NO_EXTRACTION_ESCALATION
FULL_MILITARY_PAY
HIGH_RELIEF
NO_ELITE_CREDIT
NO_TRADE_DISRUPTION
NO_BAND_MERGER
LOW_REPRESSION
OPEN_MIGRATION_EXIT

Sensitivity:
Morris
→ influential parameters

Sobol
→ selected parameters

Counterfactual:
common random numbers
ensemble runs
distributional comparison

输出：

collapse probability
tax-base trajectory
migration distribution
market connectivity
military arrears
largest band share
time-to-governance-breakdown

不要只比较 means。

报告：
interaction effects
tipping regions
nonlinearities

不要调用 USTC LLM。

P10 report、review、commit、STOP。
```

---

# 70. P11 — USTC DeepSeek V4.1 Institutional Decision Layer

这是第一次启用 runtime LLM。

---

# 71. P11 提示词

```text
只执行 P11。

先读取 .env 配置，但绝对不得打印 API key。

确认：

USTC_LLM_MODEL
对应用户在 USTC /v1/models 中人工确认的新 DeepSeek V4.1。

如果不是确认的新 V4.1：
FAIL CLOSED。

禁止自动 fallback 到：
V4 Pro
legacy V4 Flash
任何其他模型。

实现统一 Policy 接口：

InstitutionalPolicy.choose_action(observation, action_space)

已有 policies：
RulePolicy
RandomPolicy
UtilityPolicy

新增：
USTCV41Policy

USTCV41Policy 要求：

1. OpenAI-compatible USTC endpoint。
2. no tools。
3. structured input。
4. structured output。
5. Pydantic validation。
6. bounded action space。
7. timeout。
8. retry only on retryable transport errors。
9. explicit 429 handling。
10. prompt hash。
11. response hash。
12. model id logging。
13. anonymous region / actor ids。
14. no historical names。
15. no future information。
16. reasoning text cannot directly modify world state。

Live API tests 必须：
@pytest.mark.live_ustc

默认测试不得访问网络。

建立 recorded fixture replay：
live response
→ sanitized fixture
→ deterministic replay。

只给少数 institutional actors 使用：
central fiscal authority
provincial authority
selected local authority
selected armed-group leadership

调用必须 event-triggered，不是 every-agent-every-tick。

跑一个极小 smoke scenario。

不要进行大规模 LLM experiment。

P11 report、commit、STOP。
```

---

# 72. P12 — Decision-Policy Robustness

这里不是证明“LLM 更像历史人”。

而是测试：

> 核心机制是否依赖某一种决策算法。

---

# 73. P12 提示词

```text
只执行 P12。

比较：

RulePolicy
UtilityPolicy
RandomPolicy
USTCV41Policy

使用同一组初始状态、参数和 common random numbers。

重点研究：

1. Fiscal Extraction Inversion 是否跨 policy 存在？
2. Fiscal-Military Ratchet 是否跨 policy 存在？
3. crisis tipping region 是否明显移动？
4. armed-band consolidation 是否依赖 LLM？
5. policy differences 影响 level，还是改变机制本身？

USTC calls 必须：
- 少量；
- recorded；
- replayable；
- anonymous；
- bounded。

不得：
“LLM做得像历史，所以LLM正确”。

如果机制只在 USTC policy 下出现：
标记为 model-dependent。

如果在多种 policy 下都出现：
提高 robustness。

生成：
policy-robustness matrix。

P12 report、commit、STOP。
```

---

# 74. P13 — Mechanism Discovery / Mechanism Cards

真正产出理论。

---

# 75. P13 提示词

```text
只执行 P13。

不得继续添加 simulation subsystem。

读取：

calibration
hold-out
sensitivity
ablation
counterfactual
policy robustness

目标：
识别 candidate mechanisms。

至少评估：

M001 Fiscal Extraction Inversion
M002 Crisis Gating
M003 Fiscal-Military Ratchet
M004 Elite Mediation Bifurcation
M005 Insurgent Consolidation

但不得假定五个都成立。

对每个：

1. micro conditions
2. meso conditions
3. causal chain
4. trigger
5. macro outcome
6. necessary vs facilitating conditions
7. time lag
8. sensitivity evidence
9. ablation evidence
10. hold-out evidence
11. policy robustness
12. historical support
13. historical challenge
14. counterexample
15. falsifiable prediction
16. uncertainty

状态只能：

SUPPORTED
CONDITIONAL
WEAK
REJECTED
UNIDENTIFIED

禁止：
模糊写“多因素共同作用”。

要求产生：
machine-readable YAML
+
human-readable Markdown。

额外运行简单 statistical / ML boundary analysis，
寻找 tipping surface，
但 ML 只能帮助描述 simulation output，
不能取代 causal intervention。

生成：
docs/mechanisms/
outputs/reports/mechanism-synthesis.md

P13 report、independent review、commit、STOP。
```

---

# 76. P14 — Visualization / HPC / Release Candidate

最后才做漂亮东西。

---

# 77. P14 提示词

```text
只执行 P14。

目标：
让模型可运行、可观察、可移植到 HPC，但不改变核心机制。

实现：

1. CLI：
   run
   replay
   experiment
   calibrate
   analyze
2. Mesa/Solara visualization：
   county nodes
   migration
   trade
   armed-group distribution
   selected time series
3. run comparison UI。
4. mechanism report browser。
5. reproducible demo scenario。
6. benchmark suite。
7. performance profiling。
8. batch-runner。
9. Slurm array template。
10. environment / uv.lock validation。
11. HPC output merge。
12. final regression suite。

HPC 原则：

- compute nodes 默认不得需要外网；
- 不上传 API key；
- HPC 不调用 USTC runtime LLM；
- LLM decisions 如需要大批量 experiment：
  先在允许联网的环境生成+记录，
  HPC 使用 replay fixtures；
- 每个 Slurm task 独立 seed / manifest；
- 失败任务可重跑。

建立性能阈值：
Mac dev
vs
HPC ensemble。

README 增加：
quick start
architecture
epistemic warning
reproduction
HPC guide

tag：
v0.1.0-rc1

最后：
full reviewer
tests
clean tree

STOP。
```

---

# 78. 什么情况下才上学校超算

不是：

```text
模型刚写了两天
```

而是：

```text
P07 integrated model stable
+
P09 calibration pipeline stable
+
P10 experiment runner stable
```

以后。

建议 Mac：

```text
development
debugging
single runs
small ensembles
visualization
USTC LLM experiments
```

HPC：

```text
10^4–10^6 deterministic runs
Morris
Sobol
ABC
large counterfactual ensembles
```

---

# 79. HPC 绝不能做的事

不要：

```text
export USTC_API_KEY
sbatch 1000 LLM jobs
```

原因：

```text
security
network policy
rate limit
cost
reproducibility
```

---

# 80. 首个真正科学意义上的 milestone

不是：

```text
地图能动
```

而是：

> 在完全没有 LLM 的情况下，一个 calibration 后的多层 ABM 能够在 hold-out 时段产生若干独立历史 pattern，并且针对至少一个候选机制完成 sensitivity + ablation + counterfactual 三重检验。

我把它定义为：

```text
Milestone M1
Mechanism-capable deterministic model
```

---

# 81. 第二个 milestone

```text
Milestone M2
Policy-robust mechanism model
```

要求：

核心机制在：

```text
rule
utility
USTC V4.1
```

多种制度决策模型之间具有一定稳健性。

---

# 82. 最终成功标准

这个项目成功不是因为：

```text
它成功重演了1644
```

而是因为：

1. 每条关键规则有 provenance；
2. 多尺度历史 pattern 同时得到解释；
3. calibration 与 hold-out 分离；
4. 模型结果对参数扰动有明确敏感性；
5. 可以进行真正的 intervention；
6. 关键机制可被 ablation 删除；
7. 可以给出机制成立的参数区域；
8. 可以识别 tipping surface；
9. 可以列出历史反例；
10. 可以提出返回史料检验的新预测；
11. LLM 决策不成为不可解释的黑箱；
12. 任何结果都能从 run manifest 重放。

---

# 83. 项目永久硬规则

建议原样进入：

```text
.omp/RULES.md
```

核心内容：

```text
1. Simulation is an argument, not evidence.

2. Historical evidence, model assumption and generated result must never be silently merged.

3. No historical outcome may be directly encoded merely to reproduce history.

4. State capacity is multidimensional.

5. Rebellion may not be represented as a simple anger threshold.

6. Weighted cohorts are preferred over fake household-level precision.

7. LLMs may never determine physical/economic state directly.

8. Runtime LLM = USTC-confirmed DeepSeek V4.1 only.

9. Runtime LLM has no tools.

10. Runtime LLM never receives API credentials, filesystem or shell access.

11. No automatic fallback from USTC V4.1 to another model.

12. OpenCode Go is development-only.

13. Tests must not require live LLM access.

14. Every run must record code/config/seed provenance.

15. Every Phase stops after report + commit.

16. Advisor off by default.

17. Ordinary tasks use <=1 subagent; complex tasks <=2.

18. Do not expand geographical scope before the Shaanxi–Henan model is scientifically useful.

19. Do not optimize UI before mechanism validation.

20. Do not claim causal historical truth from simulation alone.
```

---

# 84. 我建议你实际启动顺序

人工：

```text
shell initialization
↓
USTC /models verification
↓
OpenCode Go verification
↓
save this file as docs/OMP_ENGINEERING_PLAN.md
↓
initial git commit
```

然后启动 OMP。

第一次只粘贴：

```text
P00 prompt
```

不要把：

```text
P00–P14
```

一起交给它跑。

只有你人工看完：

```text
P00 report
git diff
tests
```

以后，再把 P01 prompt 交给它。

这一点继续沿用你之前所有 OMP 工程最有效的：

```text
human phase gate
```

工作方式。