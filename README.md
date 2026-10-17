# iKuuu GitHub Actions 独立项目

账号密码登录、免费 CPU 模型识别、浏览器操作和签到均由 GitHub Actions 执行。项目代码放在当前仓库，不依赖浏览器扩展、本地常驻程序、外部签到服务器或运行时检出其他项目。

## 当前结果

**仅账号密码的完整自动签到尚未跑通。** 最近的真实登录测试被验证码服务以 `60500 / forbidden` 拒绝，页面显示“极验封禁”。程序遇到此类拒绝会立即停止，不循环重试账号、伪造成功或更换网络绕过限制。

[真实失败记录](https://github.com/justzoe3/sign_ikuuu/actions/runs/39057224034) · [极验官方错误码](https://docs.geetest.com/gt4/apirefer/errorcode/web)

[迁移后的独立项目自检已通过](https://github.com/justzoe3/sign_ikuuu/actions/runs/39060995939)：31 项检查、真实 Chrome 在本地测试站点上的登录/签到、额外验证与拒绝处理，以及三个公开模型的完整性和 CPU 加载。**自检不访问真实 iKuuu，不代表已经签到。**

## 配置与执行

在 Repository Secrets 中配置 `ACCOUNTS`，每行一个 `邮箱:密码`。现有账号 Secret 可直接沿用。运行入口为 `python scripts/run_actions.py`，也兼容 `python sign_ikuuu.py`。

Actions 中有两个主要入口：

- **iKuuu Actions 独立项目自检**：验证当前仓库的完整运行环境，不登录真实网站。
- **iKuuu Actions 独立签到**：由 Actions 内的 Chrome 打开正常登录表单，本地模型识别支持的文字点选/九宫格，确认登录后在同一会话内请求签到。只有网站返回成功或今日已经签到才标绿。

签到 workflow 中已定义香港时间每天 07:10 的计划，GitHub 调度可能延迟。当前因为真实登录仍被服务端拒绝，该 workflow 保持停用；不会把失败的账号登录持续放进每日计划。

仓库保活每月检查一次，仅在已配置凭据且超过 20 天没有提交时写入心跳，避免公开仓库的计划任务因长期无活动停用。

## 运行边界

每个账号最多处理 5 轮图片验证、最多执行 300 秒。验证码服务明确 forbidden 或接口限流时，停止当前运行及剩余账号。网站要求邮箱验证码或身份验证器动态码时，会报告相应阶段；当前没有配置额外验证信息的自动读取。

如果另行在 GitHub Secret 中配置了 `IKUUU_COOKIE`，程序也支持直接在 Actions 内签到；它是可选输入，不需要扩展。Cookie 失效会返回失败，不能把它当作账号密码自动登录问题已经解决。

模型权重从原始公开仓库的固定提交下载，核对 SHA-256 后缓存；浏览器会话不写入公开缓存。第三方代码来源和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

原本地扩展方案已从当前项目移除，对应扩展发布包已撤回。
