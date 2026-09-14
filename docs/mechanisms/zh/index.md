> 本文件是英文原稿的中文译稿；英文原稿为准：机制卡英文原稿在 `docs/mechanisms/`，阶段综合报告英文原稿在 `outputs/reports/`。
> 本中文译稿对应 tag `v0.1.0-rc1` 的状态，英文原稿更新后须同步本目录；对应英文原稿：`docs/mechanisms/index.md`。

# 机制卡

P13 读取了校准集成、留出期检验、敏感性筛选、消融、反事实实验臂与政策稳健性矩阵，并为每个候选机制各写一张机制卡。本报告汇总六张机制卡共同说明的内容、它们与本项目更早文件相互矛盾之处，以及拟合曲面能补充什么、不能补充什么。

状态由证据计算得出，并按模式（schema）的规则校验——SUPPORTED（成立）的机制卡必须同时引用一次干预，以及被观察的量——机制卡中的每个数字都读自它所指名的批次。机器可读形式为 `cards.yaml`。

| id | 机制 | 状态 | 一句话 |
|---|---|---|---|
| M001 | [Fiscal Extraction Inversion](M001-fiscal-extraction-inversion.md) | CONDITIONAL | 三套声明政策、三个县、三十二个家户群组。 |
| M002 | [Crisis Gating](M002-crisis-gating.md) | SUPPORTED | 被闸门控制的区域随决策政策移动：在 rule 政策下有 9 个网格单元中的 7 个崩溃，random 下 6 个，utility 下 5 个，且只有 rule 政策的单元集合与参照相同——因此哪些单元崩溃是政策依赖的。 |
| M003 | [Fiscal-Military Ratchet](M003-fiscal-military-ratchet.md) | REJECTED | 欠饷从 254 两到 26,849 两，有 37 个月下降，对照评估额 287,355：rule 实验臂最大的期末存量属于一个仍然记录了数十个存量下降月份的重复，而该实验臂最大的下降计数是 53。 |
| M004 | [Elite Mediation Bifurcation](M004-elite-mediation-bifurcation.md) | WEAK | 这张卡以一个分叉命名，而证据只解决了它的一支，这就是状态为 WEAK（弱）而不是 CONDITIONAL（有条件成立）的原因：信贷是承重的，而关于精英分化为中介者与累积者、且后果不同这一主张，既未被测量，也与运行不一致——在运行中两面是一起出现的。 |
| M005 | [Insurgent Consolidation](M005-insurgent-consolidation.md) | SUPPORTED | 稳健：在 rule 0.83、utility 0.83、random 0.83 的重复中出现（P12 结论为“稳健”，3 个实验臂中的 3 个）。 |
| M006 | [Famine Mortality](M006-famine-mortality.md) | UNIDENTIFIED | 这个空缺是结构性的，而不是经验性的：没有死亡事件、没有死亡参数、没有死亡输出，因此项目中没有任何东西原则上能够测量这一机制。 |

计数：1 个 CONDITIONAL（有条件成立），1 个 REJECTED（被否证），2 个 SUPPORTED（成立），1 个 UNIDENTIFIED（无法辨识），1 个 WEAK（弱）。

## 状态的含义

| 状态 | 含义 |
|---|---|
| SUPPORTED（成立） | 一次干预改变了它，且至少还有一种其他证据类型与之相符 |
| CONDITIONAL（有条件成立） | 它在某个声明的条件下成立，在该条件之外不成立 |
| WEAK（弱） | 证据存在，但使该主张仍未解决 |
| REJECTED（被否证） | 某项测量与所述主张相矛盾 |
| UNIDENTIFIED（无法辨识） | 项目中没有任何东西能够测量它 |

## 机制卡不是什么

机制卡是带有其可证伪条件的主张，而不是把所有可能相关的因素汇总起来。一张说自己的多种因素相互作用的卡，会在写出之前就被模式拒绝：这些字段的存在，就是为了强制点明一个条件、一个触发条件和一条因果链，使读者能逐项对照机制卡所引用的产物（artifact）。

## 术语表

本目录是英文原稿的译本，术语按下表回译到英文，读者可据此对照英文原稿。

- mechanism 机制；card 机制卡；status 状态
- micro conditions 微观条件；meso conditions 中观条件；causal chain 因果链
- trigger 触发条件；macro outcome 宏观结果；necessary 必要 / facilitating 促成
- time lag 时滞；sensitivity evidence 敏感性证据；ablation evidence 消融证据；hold-out evidence 留出期证据
- policy robustness 政策稳健性；historical support 史料支持；historical challenge 史料挑战
- counterexample 反例；falsifiable prediction 可证伪预测；uncertainty 不确定性
- 证据类型：calibration 校准 · hold-out 留出期 · sensitivity 敏感性 · ablation 消融 · counterfactual 反事实 · policy-robustness 政策稳健性 · historical-support 史料支持 · historical-challenge 史料挑战
- 状态词表：SUPPORTED（成立）· CONDITIONAL（有条件成立）· WEAK（弱）· REJECTED（被否证）· UNIDENTIFIED（无法辨识）
- tick 月步（tick）· run 运行 · replicate 重复 · sandbox 沙盒 · cohort 家户群组 · county 县
- band 武装集团 · quota 配额 · receipts 实收 · arrears 欠饷 · tax base 税基 · extraction 汲取
- relief 赈济 · elite mediation 精英中介 · consolidation 整合 · mobility gate 迁徙闸门
- sandbox fixture 沙盒夹具 · posterior 后验 · prior 先验 · ensemble 集成（后验样本集）
- 译本另用的译法：tael 两 · arm 实验臂 · suppression 弹压 · cohesion 内聚力 · merger 合并 · pattern 史料模式 · grade 等级 · grid cell 网格单元 · partial dependence 部分依赖 · load-bearing 承重 · no-op 空操作
