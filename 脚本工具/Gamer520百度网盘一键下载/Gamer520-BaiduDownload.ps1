<#
.SYNOPSIS
  从 gamer520 文章页自动提取百度网盘分享链接，并唤起百度网盘客户端。

.DESCRIPTION
  流程：文章页 →「立即下载」(/go?post_id=) → 跳转页 → 解析百度网盘二维码 data 参数 →
  复制链接/提取码 → 启动百度网盘并打开分享页。

  gamer520 现在会对非浏览器 HTTP 客户端返回 403 / Cloudflare 挑战页，因此 Get-Html 在
  HTTP 失败时会自动改用本机 Chrome/Edge 的 --headless=new --dump-dom 抓取渲染后的 HTML
  （真实浏览器指纹 + 持久化 profile 缓存 cf_clearance），无需手动干预。

.EXAMPLE
  .\Gamer520-BaiduDownload.ps1 -Url 'https://www.gamer520.com/125476.html'
  .\Gamer520-BaiduDownload.ps1 -Url '...' -ExtractOnly
  .\Gamer520-BaiduDownload.ps1 -Url '...' -OpenBrowser
#>
[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory, Position = 0)]
  [string]$Url,

  [string]$BaiduExe = 'D:\Tool\百度云\BaiduNetdisk\BaiduNetdisk.exe',

  [string]$UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',

  # 只提取信息，不启动网盘
  [switch]$ExtractOnly,

  # 额外用浏览器打开百度分享页（默认不开，避免网页验证码/干扰）
  [switch]$OpenBrowser,

  # 只用 HTTP 请求抓取，不启用浏览器兜底（gamer520 现在有 Cloudflare 防护，一般不建议）
  [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
Write-Host ''
Write-Host 'Gamer520 -> 百度网盘 提取工具' -ForegroundColor White
Write-Host ("时间: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host ''

function Write-Step {
  param([string]$Message, [string]$Color = 'Cyan')
  Write-Host "[*] $Message" -ForegroundColor $Color
}

function Write-Ok {
  param([string]$Message)
  Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Warn2 {
  param([string]$Message)
  Write-Host "[!] $Message" -ForegroundColor Yellow
}


# 返回本机可用的 Chromium 内核浏览器（Chrome 优先，其次 Edge），按顺序尝试
function Get-BrowserExeList {
  $candidates = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
  )
  $found = @()
  foreach ($p in $candidates) {
    if ($p -and (Test-Path -LiteralPath $p)) { $found += $p }
  }
  return $found
}

function Test-CloudflareChallenge {
  param([string]$Html)
  if ([string]::IsNullOrWhiteSpace($Html)) { return $true }
  if ($Html -match '(?i)Just a moment|challenge-platform|cf_chl_|Enable JavaScript and cookies|Access denied|Error 1015|cf-error-details|Sorry, you have been blocked') { return $true }
  # 几乎没内容的响应也算失败（正常页面至少几百字节）
  if ($Html.Length -lt 200) { return $true }
  return $false
}

# gamer520 现在对所有非浏览器 HTTP 客户端返回 403 / Cloudflare 挑战页。
# 这里用本机 Chrome/Edge 的 headless 模式（真实浏览器指纹 + 独立持久化 profile 保留 cf_clearance
# cookie）抓取页面，再用 --dump-dom 把渲染后的 HTML 取回来。
function Read-TextFileShared {
  param([string]$Path)
  for ($i = 0; $i -lt 40; $i++) {
    try {
      $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
      try {
        $sr = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8)
        try { return $sr.ReadToEnd() } finally { $sr.Dispose() }
      } finally { $fs.Dispose() }
    } catch {
      Start-Sleep -Milliseconds 200
    }
  }
  return ''
}

# headless 模式下浏览器默认 UA 带 "HeadlessChrome"，会被 Cloudflare 直接拦；
# 这里按本机浏览器真实版本拼一个普通 Chrome UA，保证 UA 与 TLS 指纹一致。
function Get-BrowserUserAgent {
  param([string]$Exe)
  $ver = $null
  try {
    $v = (Get-Item -LiteralPath $Exe).VersionInfo.ProductVersion
    if ($v -match '^\d+\.\d+\.\d+\.\d+$') { $ver = $v }
  } catch {}
  if (-not $ver) { return $UserAgent }
  return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$ver Safari/537.36"
}

function Invoke-BrowserDumpOnce {
  param(
    [string]$Exe,
    [string]$UserDataDir,
    [string]$Uri,
    [string]$Ua,
    [string]$OutFile,
    [string]$ErrFile,
    [int]$WaitSeconds = 75
  )

  $argList = @(
    "--user-data-dir=`"$UserDataDir`"",
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-breakpad',
    '--virtual-time-budget=20000',
    '--dump-dom',
    "--user-agent=`"$Ua`"",
    "`"$Uri`""
  ) -join ' '

  $cmdLine = "`"`"$Exe`" $argList > `"$OutFile`" 2> `"$ErrFile`"`""
  $c = Start-Process -FilePath "$env:COMSPEC" -ArgumentList "/c $cmdLine" -NoNewWindow -PassThru
  if (-not $c.WaitForExit($WaitSeconds * 1000)) { try { $c.Kill() } catch {} }
  return (Read-TextFileShared -Path $OutFile)
}

function Get-HtmlViaBrowser {
  param(
    [Parameter(Mandatory)][string]$Uri,
    [int]$WaitSeconds = 75
  )

  $exes = Get-BrowserExeList
  if (-not $exes -or $exes.Count -eq 0) { return $null }

  $profileDir = Join-Path $env:LOCALAPPDATA 'Gamer520-Download\browser-profile'
  if (-not (Test-Path -LiteralPath $profileDir)) {
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
  }

  $outFile = Join-Path $env:TEMP ("gamer520-dump-" + [guid]::NewGuid().ToString('N') + '.html')
  $errFile = Join-Path $env:TEMP ("gamer520-dump-" + [guid]::NewGuid().ToString('N') + '.log')
  $tmpProfiles = @()
  try {
    foreach ($exe in $exes) {
      $ua = Get-BrowserUserAgent -Exe $exe

      # 先用持久化 profile（缓存的 cf_clearance 能省一次验证）
      $html = Invoke-BrowserDumpOnce -Exe $exe -UserDataDir $profileDir -Uri $Uri -Ua $ua `
        -OutFile $outFile -ErrFile $errFile -WaitSeconds $WaitSeconds
      if (-not [string]::IsNullOrWhiteSpace($html)) { return $html }

      # 持久化 profile 被占用 / 启动失败时，用一次性临时 profile 再试
      $altProfile = Join-Path $env:TEMP ("gamer520-profile-" + [guid]::NewGuid().ToString('N'))
      $tmpProfiles += $altProfile
      $html = Invoke-BrowserDumpOnce -Exe $exe -UserDataDir $altProfile -Uri $Uri -Ua $ua `
        -OutFile $outFile -ErrFile $errFile -WaitSeconds $WaitSeconds
      if (-not [string]::IsNullOrWhiteSpace($html)) { return $html }
    }
    return ''
  } finally {
    Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue -WhatIf:$false
    foreach ($tp in $tmpProfiles) {
      Remove-Item -LiteralPath $tp -Recurse -Force -ErrorAction SilentlyContinue -WhatIf:$false
    }
  }
}
function Get-Html {
  param(
    [Parameter(Mandatory)][string]$Uri,
    [string]$Referer,
    [switch]$NoBrowser
  )

  $headers = @{
    'User-Agent' = $UserAgent
    'Accept'     = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    'Accept-Language' = 'zh-CN,zh;q=0.9,en;q=0.8'
  }
  if ($Referer) { $headers['Referer'] = $Referer }

  $reason = $null
  try {
    $resp = Invoke-WebRequest -Uri $Uri -Headers $headers -UseBasicParsing -TimeoutSec 45
    $content = [string]$resp.Content
    if (-not (Test-CloudflareChallenge -Html $content)) {
      return [pscustomobject]@{
        Uri     = if ($resp.BaseResponse -and $resp.BaseResponse.ResponseUri) { $resp.BaseResponse.ResponseUri.AbsoluteUri } else { $Uri }
        Content = $content
        Source  = 'http'
      }
    }
    $reason = 'Cloudflare 挑战页'
  } catch {
    $reason = $_.Exception.Message
  }

  if ($NoBrowser) { throw "HTTP 抓取失败（$reason）: $Uri" }

  $browsers = Get-BrowserExeList
  if (-not $browsers -or $browsers.Count -eq 0) {
    throw "HTTP 抓取被拦截（$reason），且本机未找到 Chrome / Edge 可用于兜底抓取: $Uri"
  }
  Write-Warn2 "HTTP 抓取被拦截（$reason），改用本机浏览器内核抓取: $Uri"
  $html = Get-HtmlViaBrowser -Uri $Uri
  if ([string]::IsNullOrWhiteSpace($html)) {
    throw "浏览器抓取也没有返回内容: $Uri"
  }
  if (Test-CloudflareChallenge -Html $html) {
    # 首次访问时可能还停留在 Cloudflare 验证页，等待其自动通过后重试一次
    Write-Warn2 '浏览器首次抓取遇到 Cloudflare 验证页，等待后重试...'
    Start-Sleep -Seconds 4
    $html = Get-HtmlViaBrowser -Uri $Uri
  }
  if ([string]::IsNullOrWhiteSpace($html) -or (Test-CloudflareChallenge -Html $html)) {
    throw "浏览器抓取被 Cloudflare 拦截（$Uri）。可先在浏览器中打开该页面通过验证后重试。"
  }
  Write-Ok '浏览器抓取成功'
  return [pscustomobject]@{ Uri = $Uri; Content = $html; Source = 'browser' }
}

function Get-PostId {
  param([string]$Html, [string]$PageUrl)
  if ($Html -match 'go\?post_id=(\d+)') { return $Matches[1] }
  if ($PageUrl -match '/(\d+)\.html') { return $Matches[1] }
  return $null
}

function Get-FilePassword {
  param([string]$Html)
  # 文章侧栏「文件密码」
  if ($Html -match 'data-clipboard-text="([^"]+)"') { return $Matches[1].Trim() }
  if ($Html -match '文件密码[：:]\s*<span[^>]*>\s*([^<]+)\s*</span>') { return $Matches[1].Trim() }
  if ($Html -match "og:title'\s+content='([^']+)'") { return $Matches[1].Trim() }
  return $null
}

function Get-GoRedirectUrl {
  param([string]$Html)
  $m1 = [regex]::Match($Html, "window\.location\s*=\s*'([^']+)'")
  if ($m1.Success) { return $m1.Groups[1].Value }
  $m2 = [regex]::Match($Html, 'window\.location\s*=\s*"([^"]+)"')
  if ($m2.Success) { return $m2.Groups[1].Value }
  $m3 = [regex]::Match($Html, 'refresh[^>]*url=([^\s>"'';]+)', 'IgnoreCase')
  if ($m3.Success) { return $m3.Groups[1].Value }
  return $null
}

function ConvertFrom-HtmlUrl {
  param([string]$Value)
  $v = $Value.Replace('&#038;', '&').Replace('&amp;', '&')
  try { return [System.Uri]::UnescapeDataString($v) } catch { return $v }
}

function Get-BaiduShareFromPage {
  param([string]$Html)

  $result = [ordered]@{
    ShareUrl   = $null
    ExtractPwd = $null
    UnzipPwd   = $null
    QuarkUrl   = $null
    XunleiUrl  = $null
  }

  if ($Html -match '解压密码[:：]\s*([^\s|<"+]+)') {
    $result.UnzipPwd = $Matches[1].Trim()
  }

  # 优先：百度网盘二维码 data=（站点把分享链编码进二维码）
  $qrMatches = [regex]::Matches(
    $Html,
    'create-qr-code/\?[^"''>\s]*data=([^"''&\s]+)[^"''>\s]*"[^>]*alt="[^"]*百度'
  )
  if ($qrMatches.Count -eq 0) {
    $qrMatches = [regex]::Matches(
      $Html,
      'data=(https?%3A%2F%2Fpan\.baidu\.com%2Fs%2F[^"''&\s]+)'
    )
  }
  if ($qrMatches.Count -gt 0) {
    $decoded = ConvertFrom-HtmlUrl $qrMatches[0].Groups[1].Value
    if ($decoded -match '^(https?://pan\.baidu\.com/s/[A-Za-z0-9_-]+)(?:\?pwd=([A-Za-z0-9]+))?') {
      $result.ShareUrl = if ($Matches[2]) { "$($Matches[1])?pwd=$($Matches[2])" } else { $Matches[1] }
      if ($Matches[2]) { $result.ExtractPwd = $Matches[2] }
    }
  }

  # 备选：正文里的 pan.baidu 链接（排除导航「限时特惠」类菜单项时可再收窄）
  if (-not $result.ShareUrl) {
    $bdp = [regex]::Match($Html, 'bdp-container[\s\S]{0,8000}')
    $scope = if ($bdp.Success) { $bdp.Value } else { $Html }
    $m = [regex]::Match($scope, 'https?://pan\.baidu\.com/s/[A-Za-z0-9_-]+(?:\?pwd=[A-Za-z0-9]+)?')
    if ($m.Success) {
      $result.ShareUrl = $m.Value
      if ($m.Value -match '[?&]pwd=([A-Za-z0-9]+)') { $result.ExtractPwd = $Matches[1] }
    }
  }

  if (-not $result.ExtractPwd) {
    $pwdBox = [regex]::Match($Html, '提取码[:：]\s*<strong>\s*([A-Za-z0-9]+)\s*</strong>')
    if ($pwdBox.Success) { $result.ExtractPwd = $pwdBox.Groups[1].Value }
  }

  # 确保分享链带 pwd
  if ($result.ShareUrl -and $result.ExtractPwd -and $result.ShareUrl -notmatch '[?&]pwd=') {
    $sep = if ($result.ShareUrl.Contains('?')) { '&' } else { '?' }
    $result.ShareUrl = "$($result.ShareUrl)${sep}pwd=$($result.ExtractPwd)"
  }

  $quark = [regex]::Match($Html, 'data=(https?%3A%2F%2Fpan\.quark\.cn%2Fs%2F[^"''&\s]+)')
  if ($quark.Success) { $result.QuarkUrl = ConvertFrom-HtmlUrl $quark.Groups[1].Value }

  $xunlei = [regex]::Match($Html, 'data=(https?%3A%2F%2Fpan\.xunlei\.com%2Fs%2F[^"''&\s]+)')
  if ($xunlei.Success) { $result.XunleiUrl = ConvertFrom-HtmlUrl $xunlei.Groups[1].Value }

  return [pscustomobject]$result
}

function Find-BaiduExe {
  param([string]$Preferred)
  if ($Preferred -and (Test-Path -LiteralPath $Preferred)) { return $Preferred }

  $candidates = @(
    'D:\Tool\百度云\BaiduNetdisk\BaiduNetdisk.exe',
    "$env:APPDATA\baidu\BaiduNetdisk\BaiduNetdisk.exe",
    "$env:LOCALAPPDATA\baidu\BaiduNetdisk\BaiduNetdisk.exe",
    "${env:ProgramFiles}\BaiduNetdisk\BaiduNetdisk.exe",
    "${env:ProgramFiles(x86)}\BaiduNetdisk\BaiduNetdisk.exe"
  )
  foreach ($p in $candidates) {
    if (Test-Path -LiteralPath $p) { return $p }
  }

  $proc = Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match 'BaiduNetdisk' -and $_.Path } |
    Select-Object -First 1
  if ($proc) { return $proc.Path }
  return $null
}

function Start-BaiduDownload {
  param(
    [string]$ShareUrl,
    [string]$ExtractPwd,
    [string]$ExePath,
    [switch]$OpenBrowser
  )

  # 剪贴板只放分享链，便于客户端「识别到分享链接」弹窗
  Set-Clipboard -Value $ShareUrl
  Write-Ok "已复制分享链到剪贴板: $ShareUrl"
  if ($ExtractPwd) {
    Write-Ok "提取码: $ExtractPwd （链接里已带 ?pwd=）"
  }

  $yunDetect = $null
  if ($ExePath) {
    $cand = Join-Path (Split-Path -Parent $ExePath) 'YunDetectService.exe'
    if (Test-Path -LiteralPath $cand) { $yunDetect = $cand }
  }
  if (-not $yunDetect -and (Test-Path -LiteralPath 'D:\Tool\百度云\BaiduNetdisk\YunDetectService.exe')) {
    $yunDetect = 'D:\Tool\百度云\BaiduNetdisk\YunDetectService.exe'
  }

  if ($ExePath) {
    $running = Get-Process -Name 'BaiduNetdisk' -ErrorAction SilentlyContinue
    if (-not $running) {
      if ($PSCmdlet.ShouldProcess($ExePath, '启动百度网盘')) {
        Start-Process -FilePath $ExePath
        Start-Sleep -Seconds 3
        Write-Ok "已启动: $ExePath"
      }
    } else {
      Write-Ok '百度网盘已在运行'
    }
  } else {
    Write-Warn2 '未找到百度网盘客户端'
  }

  # 用官方 URL Protocol 唤起客户端处理分享链（不经过 gamer520 网页，无验证码）
  $proto = "BaiduYunGuanjia://$ShareUrl"
  if ($PSCmdlet.ShouldProcess($proto, '通过百度协议打开分享')) {
    try {
      if ($yunDetect) {
        Start-Process -FilePath $yunDetect -ArgumentList $proto
        Write-Ok '已通过协议唤起百度网盘（绕过网站验证码）'
      } else {
        Start-Process $proto
        Write-Ok '已通过 BaiduYunGuanjia:// 协议唤起'
      }
    } catch {
      Write-Warn2 "协议唤起失败: $($_.Exception.Message)"
    }
  }

  # 再刷一次剪贴板，并尝试把百度窗口置前，触发剪贴板识别
  Start-Sleep -Milliseconds 800
  Set-Clipboard -Value $ShareUrl
  try {
    $wshell = New-Object -ComObject WScript.Shell
    [void]$wshell.AppActivate('百度网盘')
    Start-Sleep -Milliseconds 400
    [void]$wshell.AppActivate('BaiduNetdisk')
  } catch {}

  if ($OpenBrowser) {
    if ($PSCmdlet.ShouldProcess($ShareUrl, '浏览器打开分享页')) {
      Start-Process $ShareUrl
      Write-Ok '已打开浏览器百度分享页'
    }
  } else {
    Write-Ok '未打开浏览器（避免网页验证码）。需要时加 -OpenBrowser'
  }
}

# ---- main ----
if ($Url -notmatch '^https?://') {
  throw "无效 URL: $Url"
}

Write-Step "读取文章页: $Url"
$article = Get-Html -Uri $Url -NoBrowser:$NoBrowser
$postId = Get-PostId -Html $article.Content -PageUrl $Url
$filePwd = Get-FilePassword -Html $article.Content
if (-not $postId) { throw '未找到 post_id / 立即下载入口' }
Write-Ok "post_id=$postId$(if ($filePwd) { ", 文件密码=$filePwd" })"

$goUrl = "https://www.gamer520.com/go?post_id=$postId"
Write-Step "跟随立即下载: $goUrl"
$go = Get-Html -Uri $goUrl -Referer $Url -NoBrowser:$NoBrowser

# /go 有时是 JS 跳转脚本，有时（浏览器抓取时）浏览器已直接跟随到最终网盘页
$jump = Get-GoRedirectUrl -Html $go.Content
$pack = $null
if ($jump) {
  Write-Ok "跳转: $jump"
  Write-Step "读取网盘页: $jump"
  $pack = Get-Html -Uri $jump -Referer $goUrl -NoBrowser:$NoBrowser
} elseif ($go.Content -match 'pan\.baidu\.com') {
  Write-Ok '浏览器已直接跟随到网盘页'
  $pack = $go
  $canon = [regex]::Match($go.Content, '<link[^>]+rel="canonical"[^>]+href="([^"]+)"')
  if (-not $canon.Success) { $canon = [regex]::Match($go.Content, '<meta[^>]+property="og:url"[^>]+content="([^"]+)"') }
  if (-not $canon.Success) { $canon = [regex]::Match($go.Content, 'https?://[A-Za-z0-9.-]*gamers520\.com/\d+\.html') }
  if ($canon.Success) { $jump = $canon.Groups[1].Value }
} else {
  throw '未能从 /go 页面解析跳转地址（可能被 Cloudflare 拦截）'
}

$share = Get-BaiduShareFromPage -Html $pack.Content
if (-not $share.ShareUrl) {
  throw '未解析到百度网盘分享地址（二维码 data / pan.baidu 链接）'
}

Write-Host ''
Write-Host '======== 结果 ========' -ForegroundColor Magenta
Write-Host "百度分享: $($share.ShareUrl)"
if ($share.ExtractPwd) { Write-Host "提取码:   $($share.ExtractPwd)" }
if ($share.UnzipPwd)   { Write-Host "解压密码: $($share.UnzipPwd)" }
if ($filePwd)          { Write-Host "文件密码: $filePwd" }
if ($share.QuarkUrl)   { Write-Host "夸克:     $($share.QuarkUrl)" }
if ($share.XunleiUrl)  { Write-Host "迅雷:     $($share.XunleiUrl)" }
Write-Host '======================' -ForegroundColor Magenta
Write-Host ''

if ($ExtractOnly) {
  Write-Ok '仅提取模式，已结束'
  return [pscustomobject]@{
    PostId     = $postId
    FilePwd    = $filePwd
    JumpUrl    = $jump
    ShareUrl   = $share.ShareUrl
    ExtractPwd = $share.ExtractPwd
    UnzipPwd   = $share.UnzipPwd
  }
}

$exe = Find-BaiduExe -Preferred $BaiduExe
$startParams = @{
  ShareUrl   = $share.ShareUrl
  ExtractPwd = $share.ExtractPwd
  ExePath    = $exe
}
if ($OpenBrowser) { $startParams.OpenBrowser = $true }
Start-BaiduDownload @startParams

Write-Host ''
Write-Warn2 '不要在 gamer520 网页点「立即下载」——那才会出验证码。本工具已直接拿到网盘链。'
Write-Warn2 '百度网盘需已登录；若弹出「识别到分享链接」，点保存/下载即可。'
