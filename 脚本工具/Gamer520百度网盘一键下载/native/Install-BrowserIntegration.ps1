<#
.SYNOPSIS
  注册浏览器插件本地通道（Native Messaging，推荐）+ gamer520dl:// 协议兜底。

.EXAMPLE
  .\Install-BrowserIntegration.ps1
  .\Install-BrowserIntegration.ps1 -Uninstall
#>
[CmdletBinding()]
param([switch]$Uninstall)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$hostName = 'com.gamer520.baidu'
$protocol = 'gamer520dl'
$root = $PSScriptRoot
$launchCmd = Join-Path $root 'Gamer520-Protocol-Launch.cmd'
$nativeCmd = Join-Path $root 'native-host.cmd'
$hostJson = Join-Path $root 'com.gamer520.baidu.json'
$extDir = Join-Path (Split-Path -Parent $root) 'browser-extension'
$extIdFile = Join-Path $root 'extension-id.txt'
$extId = 'hhpakjhlankhglipjndpfnfidoedpncf'
if (Test-Path -LiteralPath $extIdFile) {
  $extId = (Get-Content -LiteralPath $extIdFile -TotalCount 1).Trim()
}

function Remove-Protocol {
  $regPath = "HKCU:\Software\Classes\$protocol"
  if (Test-Path $regPath) {
    Remove-Item -LiteralPath $regPath -Recurse -Force
  }
}

function Remove-NativeHosts {
  $paths = @(
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
  )
  foreach ($p in $paths) {
    if (Test-Path $p) { Remove-Item -LiteralPath $p -Force }
  }
  if (Test-Path -LiteralPath $hostJson) { Remove-Item -LiteralPath $hostJson -Force }
}

if ($Uninstall) {
  Remove-Protocol
  Remove-NativeHosts
  Write-Host '[+] 已卸载协议与 Native Messaging 注册' -ForegroundColor Green
  return
}

if (-not (Test-Path -LiteralPath $launchCmd)) { throw "找不到: $launchCmd" }
if (-not (Test-Path -LiteralPath $nativeCmd)) { throw "找不到: $nativeCmd" }

# ---- resolve python ----
$python = $null
try {
  $python = (Get-Command python -ErrorAction Stop).Source
} catch {
  try { $python = (Get-Command py -ErrorAction Stop).Source } catch {}
}
if (-not $python) { throw '未找到 python，请先安装 Python 并加入 PATH' }

# native-host.cmd 写成绝对 python 路径，避免 PATH 差异
@(
  '@echo off'
  "chcp 65001 >nul"
  "`"$python`" `"$root\native_host.py`""
) | Set-Content -LiteralPath $nativeCmd -Encoding ASCII

# ---- Native Messaging host manifest ----
$hostManifest = [ordered]@{
  name = $hostName
  description = 'Gamer520 Baidu Download Native Host'
  path = $nativeCmd
  type = 'stdio'
  allowed_origins = @("chrome-extension://$extId/")
}
$hostManifest | ConvertTo-Json -Compress | Set-Content -LiteralPath $hostJson -Encoding UTF8

$nmKeys = @(
  "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName",
  "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName",
  "HKCU:\Software\Chromium\NativeMessagingHosts\$hostName"
)
foreach ($k in $nmKeys) {
  New-Item -Path $k -Force | Out-Null
  New-ItemProperty -Path $k -Name '(default)' -Value $hostJson -PropertyType String -Force | Out-Null
}

# ---- protocol fallback ----
$regPath = "HKCU:\Software\Classes\$protocol"
$command = '"{0}" "%1"' -f $launchCmd
New-Item -Path $regPath -Force | Out-Null
New-ItemProperty -Path $regPath -Name '(default)' -Value 'URL:Gamer520 Baidu Download' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $regPath -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
New-Item -Path "$regPath\DefaultIcon" -Force | Out-Null
New-ItemProperty -Path "$regPath\DefaultIcon" -Name '(default)' -Value 'D:\Tool\百度云\BaiduNetdisk\BaiduNetdisk.exe,0' -PropertyType String -Force | Out-Null
New-Item -Path "$regPath\shell\open\command" -Force | Out-Null
New-ItemProperty -Path "$regPath\shell\open\command" -Name '(default)' -Value $command -PropertyType String -Force | Out-Null

Write-Host ''
Write-Host '[+] Native Messaging 已注册（推荐，无需点「打开」）' -ForegroundColor Green
Write-Host "    Host: $hostName"
Write-Host "    JSON: $hostJson"
Write-Host "    Python: $python"
Write-Host "    扩展 ID: $extId"
Write-Host '[+] 协议 gamer520dl:// 已注册（兜底）' -ForegroundColor Green
Write-Host ''
Write-Host '请重新加载浏览器插件:' -ForegroundColor Cyan
Write-Host '  1. 打开 edge://extensions/ 或 chrome://extensions/'
Write-Host '  2. 若尚未安装: 「加载解压缩的扩展」→'
Write-Host "     $extDir" -ForegroundColor Yellow
Write-Host '  3. 若已安装: 点插件卡片上的「重新加载」'
Write-Host '  4. 打开 gamer520 文章页，点工具栏图标'
Write-Host ''
Write-Host '成功时会直接弹本机 PowerShell 窗口跑下载，不再闪「打开」确认框。'
Write-Host ''
