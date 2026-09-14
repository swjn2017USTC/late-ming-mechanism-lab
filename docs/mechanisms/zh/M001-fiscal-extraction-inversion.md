> 本文件是英文原稿的中文译稿；英文原稿为准：机制卡英文原稿在 `docs/mechanisms/`，阶段综合报告英文原稿在 `outputs/reports/`。
> 本中文译稿对应 tag `v0.1.0-rc1` 的状态，英文原稿更新后须同步本目录；对应英文原稿：`docs/mechanisms/M001-fiscal-extraction-inversion.md`。

# M001 - Fiscal Extraction Inversion 财政汲取倒转

**状态（Status）: CONDITIONAL（有条件成立）**

*问题.* 把财政机器压得更紧，是否反而收不到它本该收到的份额？

## 1. 微观条件

- 课税是按某一税率对登记税基征收，而家户可以迁走、隐匿，或拖欠不缴。
- 土地会易主，也会退出耕作，因此税率所适用的税基在一次运行之内并不固定。

## 2. 中观条件

- 征收力度是一项决策：县在观察到缺口之后可以加压，而不是施加一个恒定的力度。
- 配额是按登记册评定的，而登记册与实际耕种的土地并不一致，因此二者可以背离。

## 3. 因果链

- 压力上升：每亩评估额，或所索取配额的份额，增加。
- 力度随之上升；在 utility 政策下，它从 3.34-4.25 移动到声明的上限 5.0。
- 家户迁出、隐匿或拖欠，可评估的税基收缩。
- 当力度停留在上限时，相对评估配额的实收下降。

## 4. 触发条件

一条在观察到实收缺口之后提高征收力度的决策规则。P10 的消融中没有一条：P12 的 utility 政策是本项目中唯一加压到上限的实验臂。

## 5. 宏观结果

长期缺口：实收低于配额、登记税基收缩，而军饷索取要靠不断缩小的实收来满足。

## 6. 必要条件与促成条件

- 一个可以通过迁移、藏匿或拖欠对税率作出反应的税基。（*micro* 微观，necessary 必要）
- 一个征收力度出于选择而非恒定的政权机构。（*meso* 中观，necessary 必要）
- 使迁出合法且负担得起的困顿线。（*micro* 微观，facilitating 促成）
- 一个滞后于实际耕种面积的评估登记册。（*meso* 中观，facilitating 促成）

## 7. 时滞

未定：P12 的读数比较的是一次 240 月步（tick）运行的端点，没有任何产物记录力度序列，也没有产物记录力度与实收份额相交的月份。按月的分辨率只存在于 P10 治理时间线中的越线计数。

## 8. 敏感性证据

在 p10-morris 批次的莫里斯筛选中，assessed_value_tael_per_mu 对 indicators_crossed_end 的 mu* = 0.75（sigma = 1.06）：与土地约束并列第三，位于临时迁徙份额与参考价格之后，因此这一并列是并列，而不是排名。P09 辨识了它：后验中位数 0.240 两/亩，对照先验 0.05-0.40，收缩 0.401，结论为已辨识。

## 9. 消融证据

NO_EXTRACTION_ESCALATION 移除了评估税率与征收力度对欠饷存量的反应，并降低了相对配额的实收（receipts_over_quota_total -0.06 [-0.10, -0.01]，下降），方向与倒转的说法相反。它对税基的影响未定（tax_base_change_mu -2,417.48 [-5,239.52, +4,228.41]，未定），因此该实验臂改变了征收到的数量，却没有表明加压会摧毁税基。

## 10. 留出期证据

quota-erosion-and-surcharge 在留出年份上于 1.00 的后验抽样中满足，在全运行上也是 1.00；receipts-shortfall-chronic 在校准窗口上于 1.00 的抽样中满足。该机制所论的缺口是存在的；本应导致它的加压，不在任何留出期的量中。

## 11. 政策稳健性

在 utility 重复中于 1.00 的比例出现，强度 0.10-0.31；在 random 重复中为 0.33；在 rule 重复中一次也没有：P12 的结论是“政策依赖”。当决策规则以加压回应缺口时它出现，当规则按兵不动时它不出现。

## 12. 史料支持

receipts-shortfall-chronic（等级 B，目标，窗口 1600-1644）：校准窗口 1.00；quota-erosion-and-surcharge（等级 B，留出期，窗口 1522-1644）：留出年份 1.00，全运行 1.00

## 13. 史料挑战

史料把缺口归因于征收所能触及的范围——逃亡、收成与规避——而不是归因于一条当局在实收下降时加压的反馈规则，两个史料模式也都不带被测量的征收力度。模型恰恰通过史料没有描述的这条规则产生了它的倒转，而汲取升级实验臂收得的是更多的配额，不是更少。

## 14. 反例

rule 政策：6 次重复中 0 次，参数抽样与同一个世界都与显示出它的那个实验臂相同。结构性的倒转不会取决于由哪一套声明政策在决策。

## 15. 可证伪预测

消融力度反应——把征收力度固定在其预热值——倒转就会消失：随着名义压力上升，相对配额的实收不再下降。如果它仍然下降，那么倒转就不是该反应规则造成的，这张机制卡就是错的。

## 16. 不确定性

三套声明政策、三个县、三十二个家户群组。utility 政策的上限 5.0 是一个声明的边界，不是观测到的边界，而倒转对该上限的依赖尚未检验。唯一改变汲取程度的实验臂方向相反，因此这张卡依赖的是单一政策下运行之内的同向变动。

## 引用证据

| kind | source | reading |
|---|---|---|
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | assessed_value_tael_per_mu 对 indicators_crossed_end 的 mu*=0.75 sigma=1.06 |
| calibration | `outputs/calibration/p09-*/ensemble.parquet` | assessed_value_tael_per_mu 中位数 0.240，收缩 0.401，已辨识 |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | receipts_over_quota_total -0.06 [-0.10, -0.01]，下降 |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | quota-erosion-and-surcharge 留出期 1.00，全运行 1.00 |
| policy-robustness | `outputs/experiments/p12-robustness/mechanism_readings.parquet` | 倒转在 1.00/utility、0.33/random、0.00/rule 中出现；结论为政策依赖 |
| historical-support | `ray-huang-1974` | receipts-shortfall-chronic（等级 B，目标，窗口 1600-1644）：校准窗口 1.00 |

全书的状况：1 个 CONDITIONAL（有条件成立），1 个 REJECTED（被否证），2 个 SUPPORTED（成立），1 个 UNIDENTIFIED（无法辨识），1 个 WEAK（弱）。
