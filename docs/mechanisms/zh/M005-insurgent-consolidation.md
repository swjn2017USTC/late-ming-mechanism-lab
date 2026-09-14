> 本文件是英文原稿的中文译稿；英文原稿为准：机制卡英文原稿在 `docs/mechanisms/`，阶段综合报告英文原稿在 `outputs/reports/`。
> 本中文译稿对应 tag `v0.1.0-rc1` 的状态，英文原稿更新后须同步本目录；对应英文原稿：`docs/mechanisms/M005-insurgent-consolidation.md`。

# M005 - Insurgent Consolidation 叛乱武装整合

**状态（Status）: SUPPORTED（成立）**

*问题.* 随着危机推进，武装集团是否会整合为数量更少、规模更大的组织？

## 1. 微观条件

- 武装集团通过吸纳县再也养不起的家户——即吸纳轨道——以及向周围人口征粮而壮大。
- 内聚力是一个绑定的约束：一个获得口粮少于其成员所需的武装集团会失去内聚力，并可能再次失去成员。

## 2. 中观条件

- 弹压是国家对武装集团的强制触及能力，移除它会改变哪些武装集团得以存续。
- 武装集团掠取的粮食，就是县无法评估、军队无法购买的粮食，因此武装集团的壮大与财政能力争夺同一季收成。

## 3. 因果链

- 从困顿人口与兵丁中的招募在危机年份持续进行。
- 武装集团形成的速度快于其瓦解的速度，最大武装集团在武装人口中的份额上升，而武装集团的数量随弹压变动。
- 武装人口变成数量更少、规模更大的组织，史料称其对粮食的需求超过了一个县所能征收的量——而本项目中没有任何产物测量过这个量。

## 4. 触发条件

弹压消退：移除强制触及能力之后，最大武装集团的份额下降，因此使武力集中的是弹压，而不是危机本身。该实验臂中武装集团数量如何变化则未定。

## 5. 宏观结果

武力集中于数量更少、规模更大的武装集团——在每一套声明政策中都出现，各为六次重复中的五次——同时县的税基无法同时满足军饷索取与赈济需求。

## 6. 必要条件与促成条件

- 一个由困顿家户与欠饷士兵构成的招募来源。（*micro* 微观，necessary 必要）
- 可从周围人口掠取的粮食。（*micro* 微观，necessary 必要）
- 弱到足以让大型武装集团在自身扩张后仍然存续的弹压。（*meso* 中观，facilitating 促成）
- 抬高武装集团必须购买的粮食价格的贸易中断。（*meso* 中观，facilitating 促成）

## 7. 时滞

是在整个运行上而不是在某一月步上：P12 的读数比较的是 240 个 tick 中的起始武装集团数与最终数。没有任何产物记录最大武装集团份额见顶的月份，因此整合的速度未定。

## 8. 敏感性证据

对最大武装集团份额最大的基本效应是 reference_price_tael_per_shi、food_shi_per_soldier_month、assessed_value_tael_per_mu——参考价格、士兵的口粮与评估额——而越线计数的首位是 temporary_share_of_adults_per_month、reference_price_tael_per_shi。两个排序只共享一个首位项，而不是三个，因此武装集团份额并不只是继承了崩溃边界的驱动因素，也没有任何武装集团专属参数居首。

## 9. 消融证据

弹压是承重的，方向也被测量：LOW_REPRESSION（largest_band_share_max -0.05 [-0.10, -0.01]，下降）降低了最大武装集团的份额，同时使武装集团数量仍未定。合并规则不承重：NO_BAND_MERGER 产生与基线相同的合并计数（两者都是 0，期末武装集团数 5.25 对 5.25），因为整个批次中没有任何一次合并被触发。

## 10. 留出期证据

many-bands-then-consolidation 在留出年份上于 0.62 的后验抽样中满足，在全运行上为 0.94；absorption-of-deserters-and-refugees 为 0.75 的抽样。形状在整个运行上相符；留出年份的得分低于全运行。

## 11. 政策稳健性

稳健：在 rule 0.83、utility 0.83、random 0.83 的重复中出现（P12 结论为“稳健”，3 个实验臂中的 3 个）。唯一政策依赖的部分是强度：utility 实验臂的中位强度在三者中最高。

## 12. 史料支持

many-bands-then-consolidation（等级 B，留出期，窗口 1630-1644）：留出年份 0.62，全运行 0.94；absorption-of-deserters-and-refugees（等级 B，目标，窗口 1628-1644）：校准窗口 0.75

## 13. 史料挑战

史料记载 1630 年代早期有三十来个武装集团，到 1644, 只剩一个占主导的组织，整合幅度达一个数量级；模型从五个武装集团变为三个、再变为九个，最大份额从 0.20 升到约 0.38。方向相符，幅度则小得多，因此这张卡主张的是整合，而不是史料所描述的规模。

## 14. 反例

合并实验臂：把内聚力门槛提高到最大值什么也没有改变（0 次合并，对照基线的 0 次），而整合仍然出现。不论它由什么产生，都不是模型文档所点名的合并规则。

## 15. 可证伪预测

降低内聚力门槛，使合并真正被触发，最大武装集团的份额就应当超过各声明政策所达到的最大值 0.382。如果合并被触发而份额并不上升，那么合并这一环节只是装饰，该机制的因果链应当围绕形成与瓦解重写。

## 16. 不确定性

模型点名的因果环节——按内聚力合并——从未真正运转过：P10 批次的每个实验臂、每个水平上都是零次合并。作为结果的整合是稳健的；它在模型内部的归因则不是，而这张卡并不同时主张结果与环节。每套政策五到六次重复足以显示存在，不足以估计强度。

## 引用证据

| kind | source | reading |
|---|---|---|
| policy-robustness | `outputs/experiments/p12-robustness/mechanism_readings.parquet` | 在 rule 0.83、utility 0.83、random 0.83 的重复中出现；结论为稳健 |
| ablation | `outputs/experiments/p10-ablations/runs.parquet` | LOW_REPRESSION largest_band_share_max -0.05 [-0.10, -0.01]，下降；NO_BAND_MERGER 合并 0 次，对照基线 0 次 |
| hold-out | `outputs/calibration/p09-*/predictive_checks.parquet` | many-bands-then-consolidation 留出期 0.62，全运行 0.94 |
| sensitivity | `outputs/experiments/p10-morris/runs.parquet` | 最大武装集团份额的首位项为 reference_price_tael_per_shi、food_shi_per_soldier_month、assessed_value_tael_per_mu |
| historical-support | `lorge-2005` | many-bands-then-consolidation（等级 B，留出期，窗口 1630-1644）：留出年份 0.62 |

全书的状况：1 个 CONDITIONAL（有条件成立），1 个 REJECTED（被否证），2 个 SUPPORTED（成立），1 个 UNIDENTIFIED（无法辨识），1 个 WEAK（弱）。
