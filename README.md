# iKuuu GitHub 每日签到

当前实现：本机正常登录 → 浏览器扩展加密同步会话 → GitHub Actions 每日签到。

**尚未确认本账号的真实签到成功。** 自动登录已在 Actions 实测：验证码服务返回 `60500 / forbidden`，页面显示“极验封禁”。这不是依赖安装错误或单纯图片识别失败；不会循环重试或更换网络绕过该限制。

- [真实失败记录与验证码诊断](https://github.com/justzoe3/sign_ikuuu/actions/runs/39057224034)
- [极验官方错误码说明](https://docs.geetest.com/gt4/apirefer/errorcode/web)：60500 为服务端 forbidden。

## 使用会话同步版

1. 按 [浏览器扩展说明](browser-extension/README.md) 安装扩展，填写仓库和 GitHub 令牌。
2. 在本机 iKuuu 页面正常登录。扩展使用 GitHub 公钥加密会话，更新 `IKUUU_COOKIE` Secret，然后启用并触发 Cookie 签到 workflow。
3. 以 Actions 摘要中的服务端签到响应为准。同步成功只代表会话已提交和 workflow 已触发。

每日执行时间为香港时间 07:10，GitHub 调度可能延迟。有效会话同步后，浏览器关闭不影响 Actions 使用现有会话。会话过期时需要在本机再次正常登录；扩展会再次同步。未获得有效会话前，Cookie 定时 workflow 保持停用，避免空跑。

签到客户端只使用 Python 标准库，不需要浏览器、模型下载或付费验证码服务。凭据保存在 GitHub Secret，日志脱敏；不会把会话写入仓库。遇到失效、限流、重定向或非 JSON 响应，都会正确失败并说明原因。

## 验证情况

本地 30 项 Python 回归检查通过，覆盖服务端成功/已经签到、伪成功、过期重定向、限流、登录阶段与脱敏。浏览器扩展的同步、会话去重和失败处理已通过模拟检查；其 sealed-box 加密输出已用独立 PyNaCl/LibSodium 解密验证。

这些检查不代表真实网站签到成功。首次完整验证仍需要一份由用户正常登录获得的有效会话。

- `scripts/run_ikuuu_cookie.py`：在 Actions 中执行真实签到。
- `browser-extension/`：读取本机 iKuuu 会话并加密同步。
- `scripts/ikuuu_browser.py`：保留自动登录实验代码；遇到明确 forbidden 立即退出。
- `verify-integration.yml`：只运行集成自检，不登录 iKuuu。

自动登录实验中仅保存了验证码面板的公开截图，保留 1 天；没有上传整页表单、账号密码、Cookie 或浏览器配置。
