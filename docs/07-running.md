# 运行与开发指南

## 当前功能范围

这是 M0 基础验证版：可创建空白本地账本、修改名称、下载快照备份、预览并恢复到新目录，提供可见启动器和安全退出。没有收入支出、投资持仓或历史截图导入功能。请勿作为正式财务软件投入使用。

恢复后的账本目前不自动切换；可用 --data-dir 指向恢复目录启动。备份不含尚未实现的金融实体，不与未来完整版备份兼容性作无条件承诺。

## 直接运行 Windows 便携目录

构建后双击 dist/PJZSoftware/PJZSoftware.exe。必须保留同目录的 _internal 文件夹，不能只拷走 exe。启动器显示“打开软件”和“退出软件”，默认浏览器展示界面。关闭标签页不会结束本地服务。

默认数据位置：%LOCALAPPDATA%/PJZSoftware/ledgers/default/。关闭软件后拷贝整个便携程序目录可换位置运行，数据目录独立；换机使用应用备份与恢复。

自定义独立账本：

```powershell
.\dist\PJZSoftware\PJZSoftware.exe --data-dir 'D:\我的账本'
```

不要让两个不同版本同时操作同一个目录。遇到数据库损坏或不支持的 schema 时程序拒绝打开；保留原目录，不删除后重试。

当前输出是便携程序目录，尚非带安装／卸载向导的正式安装包，未签名。首版发布前还需干净机器与标准账户安装验收。

## 从源码运行

开发依赖：Node.js 22、uv 0.10.10、Python 3.13。uv 可按 .python-version 获取所需 Python；用户运行便携版无需这些开发工具。

在仓库根目录：

```powershell
uv sync --locked
Push-Location frontend
npm ci
$env:NEXT_TELEMETRY_DISABLED='1'
npm run build
Pop-Location
uv run python -m pjz --data-dir '.\data\development-ledger'
```

运行时页面由 FastAPI 提供。修改前端后重新构建，后端变更需重启；当前不提供带认证代理的双服务热更新方案。不要把 Next 开发服务器当成生产入口。

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

本机可设置 PLAYWRIGHT_CHANNEL=msedge 使用已安装 Edge。浏览器测试启动隔离服务并使用临时合成账本，不接触默认账本。契约变更运行 scripts/export_contract.py（不带 --check）并执行 npm run contract，然后一并提交。

## 打包

```powershell
.\scripts\build.ps1
uv run python scripts/package_probe.py
```

build.ps1 构建前端、生成 PyInstaller onedir 并运行 exe 自检。package_probe.py 在不含开发工具的子进程 PATH 下验证真实静态界面、本机监听、匿名拒绝、重复启动与强制中断后重开。它不能替代全新 Windows 虚拟机测试。

## 已知限制与后续

- 备份及上传上限 8 MB；恢复预览有效期 120 秒。
- 首版无需密码且不加密；可被同一 Windows 用户下其他程序读取。
- M0 数据库仅一个账本元数据表、schema v1；无金融记录。Alembic 业务迁移在 M1 引入，当前拒绝其他 schema，绝不重建已有库。
- 账本改名通过 revision 防冲突；金融写入的完整幂等与修订记录将随 M1 落地。
- 自动每日备份、附件、CSV、迁移旧账、托盘、安装向导尚未实现。
- CI 配置已纳入仓库；是否通过以 GitHub 实际检查结果为准。
