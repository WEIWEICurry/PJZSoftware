# PJZSoftware

面向个人的 Windows 本地记账与投资资产管理软件。项目暂名 PJZSoftware，当前已实现 M0 基础验证便携版，尚未开放正式记账与投资功能。

首版目标：离线记账、人民币账户、A 股／境内 ETF／公募基金管理，以及可验证的备份与换机恢复。按用户选择采用 **Next.js + FastAPI + SQLite**。

## 已确定的产品边界

- 账本留在本机；核心功能不需要联网、远程服务器或注册账号。
- 首版无需独立解锁密码，数据库和备份默认不做应用层加密，依赖 Windows 账户权限保护。
- 首版使用手动估值，不接行情、银行或券商账户，不代客交易。
- 旧账支持分类月度汇总；明确区分汇总与逐笔明细，避免重复入账。
- 代码与个人数据分离。GitHub 只管理代码、设计和合成测试样例。

## 设计文档

建议依次阅读：

1. [产品需求与验收标准](docs/01-product.md)
2. [页面与操作流程](docs/02-experience.md)
3. [架构与技术决策](docs/03-architecture.md)
4. [数据模型与金额规则](docs/04-data-model.md)
5. [隐私、备份与历史迁移](docs/05-data-safety.md)
6. [开发规范、质量与实施计划](docs/06-development.md)
7. [运行、验证与打包指南](docs/07-running.md)

[协作约定](AGENTS.md)约束后续开发；[变更记录](CHANGELOG.md)记录交付内容。

## 仓库与本地数据

远端仓库：[WEIWEICurry/PJZSoftware](https://github.com/WEIWEICurry/PJZSoftware)。

本地 `data/` 存放迁移资料且被 Git 忽略。安装后运行时数据计划放在 Windows 用户数据目录下的独立账本文件夹，卸载或更新程序时不得删除账本。完整路径由应用显示并支持打开。

不要将个人截图、账本、交易记录、账户余额、备份或日志附到公开 Issue／PR。演示与测试只使用虚构数据。

## 当前状态

已实现 Next.js 静态界面、FastAPI 本机会话保护、SQLite 元数据持久化、带校验的快照备份、新目录恢复、可见 Windows 启动器和基础 CI。真实截图尚未导入。

本地构建产物：dist/PJZSoftware/PJZSoftware.exe（必须保留整个目录）。从源码运行和质量检查见[运行指南](docs/07-running.md)。

后端 13 项测试及浏览器端到端流程已在本机通过，便携程序通过最小 PATH、中文目录、回环监听、重复启动及中断恢复验证。全新 Windows 标准账户、安装／卸载验收尚待完成，CI 是否通过以 GitHub 实际结果为准。
