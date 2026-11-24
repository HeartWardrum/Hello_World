# Gamer520 → 百度网盘一键下载

从 [gamer520](https://www.gamer520.com) 文章页自动解析百度网盘分享链接，唤起本机百度网盘客户端；可选浏览器插件一键触发。  
**不经过网页「立即下载」**，因此一般不会碰到网站验证码。

同目录还包含：`Pin-Games-To-Desktop.ps1`（把绿色版游戏 / Steam 快捷方式整理到桌面）。

---

## 功能

| 能力 | 说明 |
|------|------|
| 解析分享链 | 跟随「立即下载」跳转，从网盘页二维码 `data=` 取出 `pan.baidu.com` 链接与提取码 |
| 过 Cloudflare | 普通 HTTP 请求被 403 时，自动改用本机 Chrome / Edge 的 headless 模式抓取（真实浏览器指纹） |
| 唤起客户端 | 复制分享链 + `BaiduYunGuanjia://` 协议 / 启动本地百度网盘 |
| 浏览器插件 | 在文章页点一下扩展图标，经 Native Messaging 调用本机脚本（无需点「打开外部应用」） |

---

## 目录结构

```
Gamer520百度网盘一键下载/
├── README.md
├── Gamer520-BaiduDownload.ps1   # 主脚本
├── Gamer520-BaiduDownload.cmd   # CMD 启动器（推荐在 CMD 里用这个）
├── Pin-Games-To-Desktop.ps1     # 桌面游戏快捷方式整理
├── browser-extension/           # Edge / Chrome 扩展（加载解压目录）
└── native/
    ├── Install-BrowserIntegration.ps1  # 注册本地通道 + 协议
    ├── native_host.py                  # Native Messaging 主机
    ├── native-host.cmd
    ├── Gamer520-Protocol-Launch.*      # gamer520dl:// 协议兜底
    └── extension-id.txt                # 固定扩展 ID
```

---

## 环境要求

- Windows 10 / 11
- PowerShell 5.1+
- 已安装百度网盘客户端（默认路径可改：`D:\Tool\百度云\BaiduNetdisk\BaiduNetdisk.exe`）
- **本机装了 Chrome 或 Edge**（脚本在 HTTP 被拦截时用它抓页面，自动查找常见安装路径）
- 浏览器插件额外需要：Python 3（已加入 PATH）

---

## 用法一：命令行

在 **CMD** 中请用 `.cmd`（直接跑 `.ps1` 往往无效果）：

```bat
cd /d 本目录
Gamer520-BaiduDownload.cmd "https://www.gamer520.com/125476.html"
```

PowerShell：

```powershell
.\Gamer520-BaiduDownload.ps1 -Url "https://www.gamer520.com/125476.html"
```

常用参数：

| 参数 | 含义 |
|------|------|
| `-ExtractOnly` | 只解析打印，不启动网盘 |
| `-OpenBrowser` | 额外用浏览器打开百度分享页（默认不开） |
| `-BaiduExe` | 指定百度网盘 `BaiduNetdisk.exe` 路径 |
| `-NoBrowser` | 只用 HTTP 请求抓取，不用浏览器兜底（站点有 Cloudflare 时基本一定失败，仅排错用） |

---

## 用法二：浏览器插件（一键）

### 1. 注册本机通道

在仓库本目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\native\Install-BrowserIntegration.ps1
```

会注册：

- **Native Messaging**（推荐，点图标直接跑脚本）
- 协议 `gamer520dl://`（兜底）

卸载：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\native\Install-BrowserIntegration.ps1 -Uninstall
```

### 2. 加载扩展

1. 打开 `edge://extensions/` 或 `chrome://extensions/`
2. 打开「开发人员模式」
3. 「加载解压缩的扩展」→ 选择本目录下的 `browser-extension`
4. 打开任意 gamer520 **文章页**，点击工具栏扩展图标

> 更换目录或重新 `Install-BrowserIntegration` 后，请在扩展页点「重新加载」。

---

## 说明与限制

- 百度网盘需已登录；客户端弹出「识别到分享链接」后，需手动点保存 / 下载。
- **不要**在网页上点「立即下载」——那才会出验证码；本工具直接解析接口/页面源码。
- Native Messaging **不是**后台常驻监听：仅在你点击扩展图标时临时启动本机主机。
- 默认不打开浏览器，避免干扰；需要时加 `-OpenBrowser`。

### 关于 Cloudflare（2026 年站点变更）

gamer520 现在对非浏览器客户端（PowerShell / curl / HttpClient 等）统一返回 **403 / Cloudflare 挑战页**。脚本已改为：

1. 先照旧用 `Invoke-WebRequest` 抓（快）；
2. 拿到 403 或挑战页时，自动改用本机 Chrome / Edge 的 `--headless=new --dump-dom`
   抓取渲染后的 HTML（真实浏览器指纹，能过验证）；
3. 用一个持久化 profile 缓存 `cf_clearance` cookie：`%LOCALAPPDATA%\Gamer520-Download\browser-profile`。

因此：

- 一般单次运行会启动 2 次无界面浏览器，耗时约 10–20 秒，期间屏幕上不会有窗口；
- 首次运行（profile 为空）可能先遇到验证页，脚本会自动等几秒重试一次；
- 若浏览器抓取也被拦，可先用普通浏览器打开该文章页通过验证（脚本与普通浏览器使用不同 profile，仅作参考），或稍后再试；
- 删掉 `%LOCALAPPDATA%\Gamer520-Download` 目录可重置缓存。

---

## Pin-Games-To-Desktop

把绿色版游戏目录、Steam 库等整理成桌面快捷方式（可重复运行）：

```powershell
.\Pin-Games-To-Desktop.ps1
.\Pin-Games-To-Desktop.ps1 -WhatIf
```

具体根目录、别名等见脚本内参数与注释。

---

## 许可证 / 声明

仅供个人学习与自用自动化。请遵守当地法律与目标站点、网盘服务条款；勿用于未授权分发或侵权用途。
