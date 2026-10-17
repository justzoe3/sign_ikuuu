# iKuuu → GitHub 会话同步扩展

本扩展在你正常登录 iKuuu 后，将当前会话通过 GitHub 官方公钥加密，写入你指定仓库的 `IKUUU_COOKIE` Secret，并触发 `sign_ikuuu.yml`。每天签到由 GitHub Actions 执行；浏览器关闭后，现有会话仍可供 Actions 使用。会话失效后需要再次正常登录。

## 安装与配置

1. 下载扩展 ZIP，解压到一个保留的文件夹。
2. Chrome 或 Edge 打开扩展管理，开启开发者模式，选择“加载已解压的扩展程序”，选择解压后的文件夹。
3. 打开扩展，填入你现有的 GitHub 令牌。令牌需要目标仓库的 Secrets 和 Actions 写入权限。也可以点击“创建专用令牌”，只选 `sign_ikuuu` 仓库，赋予这两项写入权限。
4. 仓库填 `justzoe3/sign_ikuuu`，点击“保存并同步”。
5. 在 iKuuu 正常登录。扩展会同步会话并打开 Actions 结果页。

GitHub 令牌保存在本机扩展存储，不写入仓库。扩展没有网页内容脚本，只能读取 `ikuuu.top` 的 Cookie。会话仅在本机出现变化或手动同步时上传；后台每 30 分钟检查本机 Cookie，不产生签到请求。收到 GitHub API 同步成功只代表已触发 workflow，不能替代网站签到成功确认。

本扩展不处理验证码。图片验证和额外身份验证由你在网站正常完成。验证码服务返回 forbidden 时，不重试自动登录。

## 依赖

- TweetNaCl.js 1.0.3：原始 `nacl-fast.min.js`，许可见 `vendor/tweetnacl-LICENSE`。
- blakejs 1.2.1：原始模块打包，许可见 `vendor/blakejs-LICENSE`。
- npm 包下载时已核对 registry 中的 SHA-512 integrity；sealed box 输出与 LibSodium 解密交叉验证。

当前实现已完成本地模拟与加密兼容性验证；需要真实登录会话才能核对第一次 Actions 签到。
