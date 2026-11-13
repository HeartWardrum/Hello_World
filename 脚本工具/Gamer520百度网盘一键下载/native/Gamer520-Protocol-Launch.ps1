<#
.SYNOPSIS
  处理浏览器自定义协议 gamer520dl:，调用主下载脚本。
#>
param(
  [Parameter(Mandatory = $false, Position = 0)]
  [string]$ProtocolArg
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$mainScript = Join-Path $scriptRoot 'Gamer520-BaiduDownload.ps1'
if (-not (Test-Path -LiteralPath $mainScript)) {
  throw "找不到主脚本: $mainScript"
}

if (-not $ProtocolArg) {
  if ($args.Count -gt 0) { $ProtocolArg = [string]$args[0] }
}
if (-not $ProtocolArg) { throw '未收到协议参数' }

$raw = $ProtocolArg.Trim().Trim('"')
$raw = $raw -replace '^gamer520dl://', '' -replace '^gamer520dl:', ''

if ($raw -match '[?&]url=([^&]+)') {
  $raw = [System.Uri]::UnescapeDataString($Matches[1])
} else {
  $raw = [System.Uri]::UnescapeDataString($raw)
}

$raw = $raw.Trim()
if ($raw -notmatch '^https?://') {
  throw "无效 URL: $raw"
}

Write-Host "协议唤起 URL: $raw"
& $mainScript -Url $raw
$code = if (Test-Path variable:LASTEXITCODE) { $LASTEXITCODE } else { 0 }
exit $code
