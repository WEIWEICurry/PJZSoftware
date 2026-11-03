# 模块独立路径

## 验收条件

各模块使用 Next.js App Router 独立静态路径：/、/accounts/、/journal/、/reports/、/investments/、/investment-reports/、/data/、/plan/。支持直接访问、刷新、浏览器前进后退和新标签打开。未知路径返回 404，不回退伪装首页。

共享根布局持有本地连接与运行状态，切换模块不重建会话、不新增 Node 服务。保持原有认证与 Host／Origin 检查；URL 不写金额、备注和令牌。筛选和未保存表单本次仍沿用原有组件生命周期，不承诺刷新保留。

采用现有 trailingSlash 静态目录导出，FastAPI StaticFiles(html=True) 按目录提供 index.html，无需通配文件读取或服务端渲染。验收使用合成数据覆盖所有路径直达、刷新、历史导航、404 与既有账务回归。
