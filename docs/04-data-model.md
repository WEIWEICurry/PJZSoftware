# 数据模型与计算口径

状态：总体逻辑模型。M1 已落地的表与首版字段合并决策见 docs/08-daily-ledger.md；投资和历史汇总实体仍属后续设计。物理变更必须有迁移与验证。

## 1. 基础规则

- ID 用 UUID；所有业务表携带 ledger_id、created_at、updated_at、revision。账务日期是本地日历日，审计时间为 UTC。
- 人民币金额以 INTEGER 分保存；API 用整数分的十进制字符串，例如 amount_fen="12345" 表示 123.45 元。
- 单价／份额以规范十进制 TEXT 存储并转 Python Decimal；份额最多 8 位小数，价格最多 8 位小数，超出时拒绝并说明，不静默截断。禁止 SQLite REAL 或 JS Number 算账。
- 金额舍入采用 ROUND_HALF_UP 到分；比例分摊保留高精度，最后一笔承担分位余数。输入范围和 Decimal 上下文显式定义，溢出拒绝。
- 历史事件按 effective_date、day_sequence、id 确定顺序；同日交易可调整顺序后全量重算该标的后续事件。
- 所有写入用事务；外键开启。余额、持仓是可重建投影，事件为事实来源。修改保留变更前后本地修订，作废不物理删除金融记录。

## 2. 主要实体

| 实体 | 关键字段与约束 |
| --- | --- |
| ledgers | id、name、currency=CNY、schema_version |
| accounts | name、kind、currency、archived；kind 区分现金／银行卡／支付／证券现金／负债／应收 |
| categories | name、direction、parent_id、archived；被引用后归档 |
| financial_events | kind、effective_date、day_sequence、status、source、idempotency_key、revision；统一事件父表 |
| cash_entries | event_id、account_id、delta_fen；余额＝有效 entry 之和 |
| daily_transactions | event_id、income/expense、category_id、amount_fen、note；对应普通收支及退款 |
| transfers | event_id、from_account_id、to_account_id、amount_fen、fee_fen、fee_category_id；不允许同账户转账 |
| opening_balances | event_id、account_id、balance_fen、as_of_date；期初不计入收支 |
| balance_adjustments | event_id、account_id、delta_fen、reason；单独报告，非收入 |
| instruments | market、code、name、kind、currency；market+code 唯一 |
| investment_events | event_id、account_id、instrument_id、action、quantity_decimal、gross_fen、fee_fen、tax_fen、cost_basis_fen? |
| valuations | instrument_id、price_date、price_decimal、source=manual；日期与来源可追溯 |
| historical_summaries | period_start、period_end、direction、category_id、amount_fen、batch_id、coverage_state |
| reconciliation_groups | summary_id、covered_detail_ids、scope_hash、difference_fen、state、confirmed_at |
| import_batches | file_hash、canonical_hash、format_version、status、counts；重导幂等 |
| budgets | month、category_id、limit_fen；同月同分类唯一，首版仅叶分类 |
| attachments | relative_path、sha256、size、source_batch_id；不保存任意外部绝对路径 |
| operation_revisions | entity_id、operation、before/after、at；本地敏感数据，随账本备份，不上传 |
| settings / schema_migrations | 显示／备份策略与数据库迁移记录 |
| idempotency_records | key、payload_hash、result_ref；相同 key 不同输入拒绝 |

负债账户以“欠款为正”的展示约定存储余额；借款增加欠款、还本金减少欠款，借款与本金还款不进日常收支。账户类型决定 entry 解释；不宣称是完整复式会计系统。

投资事件、现金变动、份额投影和修订记录在同一事务更新。数据归属、引用、日期、有效数量及事件类型在应用层与可表达的数据库约束两处验证。

建议索引：账本＋日期＋顺序、账户＋日期、账户＋标的＋日期、汇总期间＋分类、导入摘要；不对备注等私密长文本无条件建全文索引。

## 3. 日常与现金

支出减少资产账户余额，收入增加；退款以 expense_refund 关联原支出，抵减退款发生日的支出，不改写旧月报表。转账一端减少、一端增加；费用另计日常支出。期初与校正不影响收入。

首版不允许普通资产账户余额为负，透支需显式使用负债账户。证券现金与持仓分开，证券账户总资产＝证券现金＋持仓估值，不能重复计入总览。

## 4. 投资成本算法

首版按“账户＋标的”使用移动加权成本，不承诺券商税务成本口径。

- 买入：总成本增加成交金额＋买入费用＋税费；证券现金减少相同金额；份额增加。
- 卖出：本次分摊成本＝卖出前剩余成本×卖出数量／卖出前数量，舍入到分；全部清仓时取全部剩余成本。剩余成本减去本次分摊，不能留下清仓尾差。
- 已实现卖出盈亏＝成交金额－卖出费用－税费－分摊成本。
- 现金分红：证券现金增加实际净到账，单列投资收益，不降低持仓成本，不再计普通收入。
- 分红再投：同一原子事件包含净分红收入与再买入；新增份额和成本，现金净变化为零（额外费用显式体现），不能又记一次普通收入。
- 拆分／合并：总成本不变，按确定比例调整份额；现金补差需独立记录。无依据的任意份额修改不作为交易。
- 未实现盈亏＝有效份额×估值价（最终舍入到分）－剩余成本。
- 累计投资盈亏＝已实现卖出盈亏＋净现金分红及再投分红－未归入交易的独立费用＋未实现盈亏；已在买卖净额或成本中计入的费用不再扣。
- 有持仓无价格时收益未知；不以零价代替。不同标的价格日期不一致时标注，不能伪装为统一时点净值。

合成验算：买 100 份，成交 1000 元、费用 5 元；再买 100 份，成交 1200 元、费用 5 元。共 200 份、成本 2210 元。卖 50 份，成交 650 元、费用 2 元，分摊成本 552.50 元，已实现收益 95.50 元，余 150 份、成本 1657.50 元。余份按 13 元估值，未实现收益 292.50 元，合计 388 元，与净现金流＋持仓价值一致。

公募基金以确认日、实际确认份额和金额为准，首版不处理申购确认前冻结资金。期初持仓允许录数量、日期和已知成本；成本未知不能自动填零，相关盈亏显示“成本待补”。期初持仓只调整资产，不计收入；期初前累计收益不推算。卖出前需先补齐计算所需成本。

## 5. 历史汇总与明细去重

汇总没有交易日期与账户，不建立 cash_entries。保留原始期间（包含起止日）和来源；只支持单月内期间，重叠的同分类汇总不能同时生效。

每个“月份＋分类＋方向”存在明确覆盖区间。有效汇总覆盖区间内的逐笔记录仍参与其真实账户余额，但默认不再加入收支报表；区间外明细正常计入。界面必须标注覆盖状态，导入前提示，不能悄悄吞掉新明细。

补齐明细时，先核对该区间总额与日期覆盖，再由用户确认整段切换为明细统计。零差额不自动表示明细完整。存在差额时停留待核对状态，不自动补一笔“差额支出”，不采用“汇总减已导明细”伪造交易。

原汇总保留为凭证并标为 replaced，不物理删除。日级图表和任意截取汇总区间的报表显示“缺少逐日数据”，不能把月总额强行记到月底或平均分配。

当前截图的十月汇总截止 10 月 26 日；后续该日新增记录可能与截图覆盖重叠，必须核对后替换汇总或更新截止范围，不直接追加到报表。导入预览显式提示此边界。

## 6. 修订与重算

历史投资事件修改、作废或改顺序后，重放该账户标的后续有效事件；负持仓、资金不足、成本未知或不支持事件导致校验失败时整个事务回滚。当前投影可在恢复后重建，并与备份校验摘要核对。不得只修改展示数字而不修复事实来源。

## schema v3：应收本金

receivable 以待收回本金为正，借出增加应收、收回减少应收；负债仍以欠款为正。两类均复用 transfer 与 cash_entries，不额外维护一份余额。新建对象与借还流水同事务；旧负债直接复用。普通收入、支出、退款不能记入应收账户。

总览 assets_fen 表示资金账户余额，receivable_fen 单独表示待收回本金；net_fen＝assets_fen＋receivable_fen－debt_fen。上述四类本金不进入月度收支。具体迁移与验收见 [简化借还款](10-simple-loans.md)。
