> 本文件是英文原稿的中文译稿；英文原稿为准：机制卡英文原稿在 `docs/mechanisms/`，阶段综合报告英文原稿在 `outputs/reports/`。
> 本中文译稿对应 tag `v0.1.0-rc1` 的状态，英文原稿更新后须同步本目录；对应英文原稿：`docs/mechanisms/M002-crisis-gating.md`。

# M002 - Crisis Gating 危机闸门

**状态（Status）: SUPPORTED（成立）**

*问题.* 产生崩溃的是冲击本身，还是让冲击得以抵达税基的那个条件？

## 1. 微观条件

- 家户可以迁出：迁出是家户群组在困顿越过一条声明阈值线时所进入的状态，它带走自身的劳动力与消费。
- 迁出必须负担得起——要计收迁徙成本与途中损耗——因此落在阈值线以下的家户仍可能走不了。

## 2. 中观条件

- 县的税基是留下来的劳动力与土地，因此外流就是可评估价值的外流。
- 军饷是对同一笔实收提出的索取，因此更小的税基表现为欠饷，而不是表现为更小的索取。

## 3. 因果链

- 闸门打开：迁徙成本、途中损耗，以及使家户有资格迁出的困顿线都被移除。
- 家户以基线从未达到的数量退出。
- 税基收缩的幅度约为次大实验臂的七倍，按中位数对中位数计约十七倍。
- 实收无法覆盖军饷索取，欠饷上升，县在每个重复中都越过声明的崩溃线。

## 4. 触发条件

是制度闸门，不是天气：闸门打开时，危机出现在基线本没有危机的地方；而移除气候冲击后崩溃没有变化。

## 5. 宏观结果

县的财政与其强制触及能力发生系统性崩溃，且在每个重复中都于同一月步（tick）达到。

## 6. 必要条件与促成条件

- 一道可开可闭的家户迁徙闸门。（*meso* 中观，necessary 必要）
- 以仍然在场的家户为内容的税基。（*meso* 中观，necessary 必要）
- 严重到足以把家户推向阈值线的气候冲击。（*micro* 微观，facilitating 促成）
- 一支对实收的索取不随实收缩小而缩小的军队。（*meso* 中观，facilitating 促成）

## 7. 时滞

二十四个 tick，且在每个重复中都如此：开闸实验臂在 240, 即第 48 个 tick越过声明的崩溃线，在 24 个 tick的预热之后。它是消融批次中唯一一个其重复会越线的实验臂；莫里斯与索博尔设计分别在 tick 24, 48 与 216 越线。

## 8. 敏感性证据

对 indicators_crossed_end 最大的基本效应是 temporary_share_of_adults_per_month、reference_price_tael_per_shi、land_per_adult_capacity_mu（p10-morris）：一个迁徙份额、一个市场价格与一个土地约束，而土地约束与评估额并列，而不是排在其后。居首的控制项落在迁徙与市场一侧，不在气候轴上。

## 9. 消融证据

打开闸门就是原因：breakdown +1.00 [+1.00, +1.00]，上升；tax_base_change_mu -162,553.28 [-170,826.34, -161,632.75]，下降；households_exited +8,514.95 [+3,896.31, +9,732.58]，上升——对照的是一个没有任何重复崩溃的基线。移除气候冲击则不然：breakdown +0.00 [+0.00, +0.00]，未定；税基未定（tax_base_change_mu +2,718.02 [-4,560.20, +3,078.74]，未定）；迁出下降（households_departed -534.23 [-580.57, -20.96]，下降）。

## 10. 留出期证据

shaanxi-net-outflow 在留出年份上得分为 0.16，对照全运行的 1.00，在外推上为 0.00；chongzhen-drought-sequence 在留出年份上得分为 0.00。外流的方向相符；它的时点不符。

## 11. 政策稳健性

被闸门控制的区域随决策政策移动：在 rule 政策下有 9 个网格单元中的 7 个崩溃，random 下 6 个，utility 下 5 个，且只有 rule 政策的单元集合与参照相同——因此哪些单元崩溃是政策依赖的。至于*闸门*本身是崩溃的承载者，这一点是在 P10 消融中检验的，而且只在一套政策下，而非三套。

## 12. 史料支持

shaanxi-net-outflow（等级 C，留出期，窗口 1628-1644）：留出年份 0.16，全运行 1.00；chongzhen-drought-sequence（等级 B，留出期，窗口 1627-1644）：留出年份 0.00

## 13. 史料挑战

史料中的外流集中在饥荒发作的那些年份，而模型符合全程的方向，却错过了这些年份：留出得分为 0.16，而全运行为 1.00。一道持续渗漏的闸门与一道在危机中打开的闸门并不相同。

## 14. 反例

干旱消融：移除气候冲击保持了基线的结果——没有任何重复崩溃——因此冲击不是那道闸门。消融批次的十二个实验臂中只有闸门臂崩溃。在 P10 的其他地方，没有它也确有崩溃发生——极端参数抽样下有 40 次索博尔运行中的 7 次以及一个临界网格单元越线——因此这一主张说的是所声明的实验臂，而不是唯一的路径。

## 15. 可证伪预测

在最严酷的气候设定下关闭闸门，崩溃就不应发生：一个在严酷度下限 0.9 与名义压力 0.04 下拒绝永久迁出的实验臂，在每个重复中都产生零次崩溃。在最温和的设定下强行打开闸门，则至少应有一个重复崩溃。任一个结果都能否证这张机制卡。

## 16. 不确定性

被干预的只有一道闸门。赈济与贸易渠道也有实验臂，但它们对越线计数的影响在四次重复下未定，因此这张卡并不主张它们不是闸门。三个县、三十二个家户群组，以及一条其困顿线是声明的而非观测的迁徙规则。

## 引用证据

| kind | source | reading |
|---|---|---|
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | OPEN_MIGRATION_EXIT breakdown +1.00 [+1.00, +1.00]，上升；NO_DROUGHT breakdown +0.00 [+0.00, +0.00]，未定 |
| counterfactual | `outputs/experiments/p10-ablations/runs.parquet` | NO_DROUGHT x FULL_MILITARY_PAY 对 indicators_crossed_end：联合 +0.00，对照可加值 -0.50 [+0.00, +1.00]，可加 |
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | 对 indicators_crossed_end 最强的参数：temporary_share_of_adults_per_month、reference_price_tael_per_shi、land_per_adult_capacity_mu |
| policy-robustness | `outputs/experiments/p12-robustness/tipping_grid.parquet` | 崩溃的网格单元：rule 7, random 6, utility 5 |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | shaanxi-net-outflow：留出期 0.16，外推 0.00，全运行 1.00 |
| historical-challenge | `data/historical_patterns/01-drought-climate.yaml` | chongzhen-drought-sequence（等级 B，留出期）：留出年份 0.00——一项被驳倒的检验，此处作为挑战而非支持引用 |

全书的状况：1 个 CONDITIONAL（有条件成立），1 个 REJECTED（被否证），2 个 SUPPORTED（成立），1 个 UNIDENTIFIED（无法辨识），1 个 WEAK（弱）。
