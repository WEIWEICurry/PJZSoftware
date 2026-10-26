# 运行与开发指南

## 当前版本：0.2.0 日常账本便携版

已实现账户与期初、普通收支、退款、转账／借还本金与费用、余额校正、修改／作废、归档、分类和月收支总览。备份包含全部已实现的业务数据、修订和幂等记录。历史截图尚未导入，投资持仓、预算及分类图表后续开发。

恢复后保留独立副本，不自动切换；用 --data-dir 指向恢复目录可打开该账本。旧版 schema v1 会先备份再升级；支持 v1、v2 备份恢复，拒绝更高版本。

## 直接运行 Windows 便携目录

双击 dist/PJZSoftware/PJZSoftware.exe，必须保留同目录的 _internal 文件夹。默认浏览器打开界面，启动器提供打开与退出控制；关闭浏览器标签不等于退出服务。

默认数据位置：%LOCALAPPDATA%/PJZSoftware/ledgers/default/。安装资源与账本分离。换电脑时使用备份恢复，不直接复制运行中的数据库。

```powershell
.\dist\PJZSoftware\PJZSoftware.exe --data-dir 'D:\我的账本'
```

不要同时用旧程序操作升级后的账本。回退需使用旧程序与升级前备份，不支持直接降级 v2。尚未提供正式安装／卸载向导及程序签名。

## 开始记账

1. 在“账户”录入账户类型、实际期初日期及余额（负债填欠款）。若要补录历史，期初日期应在这些交易之前。
2. 在“日常账本”选择类型、账户、日期和金额。转账选择两端，借还本金也使用转账；手续费单独计支出。
3. 退款在原支出行点“退款”发起，允许部分退款且不能累计超过原额；分类沿用原支出。
4. 修改／作废后重新检查完整时间线，余额不足或关联退款失效会拒绝整个操作。期初记录不可直接编辑，差异用“余额校正”并写原因。
5. 归档账户必须零余额；历史记录保留，归档后不接收新流水。
6. 用“数据管理”备份和恢复。备份不加密，保存到信任的位置；当前上限 8 MB。

总览的账户净额只包含现金资产和负债，不代表包含投资持仓的完整净资产。负债账户暂不支持普通收入、负债之间转账或负的欠款余额。

## 从源码运行

开发依赖：Node.js 22、uv 0.10.10、Python 3.13。便携版用户不需这些工具。

```powershell
uv sync --locked
Push-Location frontend
npm ci
$env:NEXT_TELEMETRY_DISABLED='1'
npm run build
Pop-Location
uv run python -m pjz --data-dir '.\data\development-ledger'
```

前端变更需重新构建；后端变更需重启。当前不提供带认证的 Next 双服务热更新代理。

## 质量检查

```powershell
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run mypy
uv run pytest -q
uv run python scripts/export_contract.py --check
uv run python -m pjz --self-test
Push-Location frontend
npm run contract
npm run format:check
npm run lint
npm run typecheck
npm run build
npx playwright install chromium --only-shell
npm test
Pop-Location
```

可设置 PLAYWRIGHT_CHANNEL=msedge 使用已安装 Edge。浏览器测试使用临时合成账本，涵盖服务端已保存但响应丢失后的重试，不接触默认账本。

接口变更先运行 scripts/export_contract.py（不带 --check），再执行 npm run contract；契约和生成类型一起提交。

## 打包

```powershell
.\scripts\build.ps1
uv run python scripts/package_probe.py
```

构建将前端与 Alembic 迁移脚本一并打包。实际 exe 自检覆盖合成账户／收支的备份恢复；package_probe 在不含开发工具的子进程 PATH 验证监听、静态页面、鉴权、重复启动与中断重开。这不能替代正式安装／卸载和独立 Windows 标准账户验收。

## 仍未实现

自动每日备份、附件、CSV、截图旧账导入、预算、投资持仓、修订历史查看页和图形化账本切换。金额以整数分计算；现金时间线每次写入重放，当前面向个人规模，尚未做大数据量性能承诺。修订记录已本地保存并随账本备份。
