# iKuuu Cookie 自动签到

使用公开项目 [viceren/ikuuu-auto-checkin](https://github.com/viceren/ikuuu-auto-checkin) 的 Cookie 直签方案，上游代码固定为提交 `601a929e9caac126920c9fccd70c467ed63315e5`，运行时检出，不依赖账号密码自动完成验证码。

## 一次性配置

1. 在你正常使用的浏览器里打开 `https://ikuuu.top/auth/login`，完成登录及必要的人机验证。
2. 打开浏览器开发者工具的 Network / 网络面板，刷新用户中心。在该站点的用户中心请求中，复制 Request Headers / 请求标头里的 **Cookie 完整值**。应包含已登录的 `uid`、`key` 等字段；不要复制 `Set-Cookie` 响应头。
3. 到本仓库 **Settings → Secrets and variables → Actions → New repository secret**，名称填 `IKUUU_COOKIE`，值填上一步的一行 Cookie，然后保存。
4. 在 **Actions → iKuuu Cookie 自动签到 → Run workflow** 手动运行一次，查看运行摘要里的服务端签到结果。

Cookie 是登录凭据，只放入 GitHub Repository secret。不要提交到仓库，也不要贴到 Issues 或聊天记录。Cookie 过期后在同一个 Secret 中更新即可。

现有 `ACCOUNTS` 是旧脚本使用的邮箱密码配置；新流程只读取 `IKUUU_COOKIE`。

## 运行行为

- 每天香港时间 **07:10** 计划运行；GitHub 的实际触发时间可能延迟。
- 先检查 Cookie 配置，再验证用户中心登录态，最后调用签到接口。
- 只有服务端确认签到成功或今日已经签到，且上游返回成功摘要时，工作流才显示成功。
- 缺少 Cookie、登录失效、网络异常或签到失败都会标红，并在运行摘要中给出原因。
- Cookie 和邮箱在日志及摘要中脱敏。
- 每次只安装 Requests，不下载 Playwright 浏览器；不配置微信、第三方打码或外部消息通知。
- `Keep Repository Alive` 每月 1 日检查一次；仅当仓库超过 20 天没有提交时生成一条保活提交，避免公开仓库长期无活动导致计划任务停用。

当前站点默认 `https://ikuuu.top`。如该站点确认切换到 `https://ikuuu.pw`，可在仓库 Actions Variables 添加 `IKUUU_BASE_URL=https://ikuuu.pw`；更新 Cookie 时使用对应站点的有效登录会话。

## 上游与本仓库集成

- 签到客户端：`viceren/ikuuu-auto-checkin/checkin.py`，固定到上述提交。
- 本仓库的 `scripts/run_ikuuu_cookie.py` 负责配置检查、输出脱敏、超时限制、退出状态及成功摘要校验。
- 修改上游版本前，应先审阅源码并验证实际签到结果，不能只依据 Actions 的绿色状态。
