# GitHub Pages 构建

`dashboard/` 保存React界面源代码，`site/`保存当前可部署静态产物。界面读取同仓库的三个公开数据文件，不需要Sites后台或用户登录。

在此目录运行 `pnpm install --frozen-lockfile` 和 `pnpm build`，将 `dist/github/` 中的页面与资源复制到 `../site/`，保留`../site/data/`。提交后由现有Pages工作流发布。

Gmail通知由私有云任务处理；此仓库没有收件地址、Gmail授权凭据或可公开调用的邮件发送接口。
