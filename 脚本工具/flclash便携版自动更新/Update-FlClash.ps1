#Requires -Version 5.1
<#
.SYNOPSIS
  FlClash portable updater. Never force-kills FlClash / FlClashCore.
  Tools live in this folder; FlClash installs under installRoot from config.ini.
#>
[CmdletBinding()]
param(
  [switch]$ForcePrompt,
  [switch]$SilentCheck,
  [switch]$Bootstrap
)

$ErrorActionPreference = 'Stop'
$UpdaterDir = $PSScriptRoot
$StatePath  = Join-Path $UpdaterDir 'state.ini'
$LogPath    = Join-Path $UpdaterDir 'update.log'
$ConfigPath = Join-Path $UpdaterDir 'config.ini'

function Get-InstallRoot {
  $root = $null
  if (Test-Path $ConfigPath) {
    Get-Content $ConfigPath -Encoding UTF8 | ForEach-Object {
      if ($_ -match '^\s*installRoot\s*=\s*(.+)$') { $root = $Matches[1].Trim().Trim('"') }
    }
  }
  if (-not $root) {
    if (Test-Path 'D:\') { $root = 'D:\tool' }
    else { $root = Join-Path $env:LOCALAPPDATA 'FlClash' }
  }
  return $root
}

$ToolRoot     = Get-InstallRoot
$StableLink   = Join-Path $ToolRoot 'FlClash'
$RepoApi      = 'https://api.github.com/repos/chen08209/FlClash/releases/latest'
$AssetSuffix  = 'windows-amd64.zip'
$ProcessNames = @('FlClash', 'FlClashCore', 'FlClashHelperService')

Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type -AssemblyName System.Drawing | Out-Null

function Write-Log {
  param([string]$Message)
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

function Show-Info {
  param([string]$Text, [string]$Title = 'FlClash 更新')
  [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
  ) | Out-Null
}

function Show-YesNo {
  param([string]$Text, [string]$Title = 'FlClash 更新')
  return [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question,
    [System.Windows.Forms.MessageBoxDefaultButton]::Button2
  )
}

function Show-RetryCancel {
  param([string]$Text, [string]$Title = 'FlClash 更新')
  return [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::RetryCancel,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  )
}

function Read-State {
  $state = @{
    currentPath    = $null
    currentVersion = $null
  }
  if (Test-Path $StatePath) {
    Get-Content $StatePath -Encoding UTF8 | ForEach-Object {
      if ($_ -match '^\s*([^=]+)=(.*)$') {
        $state[$Matches[1].Trim()] = $Matches[2].Trim()
      }
    }
  }
  if (-not $state.currentPath -or -not (Test-Path (Join-Path $state.currentPath 'FlClash.exe'))) {
    $found = Get-ChildItem $ToolRoot -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '^FlClash-(\d+\.\d+\.\d+)-windows-amd64$' } |
      Sort-Object {
        if ($_.Name -match 'FlClash-(\d+\.\d+\.\d+)-') { [version]$Matches[1] } else { [version]'0.0.0' }
      } -Descending |
      Select-Object -First 1
    if ($found -and ($found.Name -match 'FlClash-(\d+\.\d+\.\d+)-')) {
      $state.currentPath = $found.FullName
      $state.currentVersion = $Matches[1]
    } else {
      $state.currentPath = $null
      $state.currentVersion = $null
    }
  }
  return $state
}

function Save-State {
  param([string]$Path, [string]$Version)
  @(
    "currentPath=$Path"
    "currentVersion=$Version"
  ) | Set-Content -Path $StatePath -Encoding UTF8
}

function Get-RunningFlClash {
  Get-Process -Name $ProcessNames -ErrorAction SilentlyContinue
}

function Wait-FlClashExit {
  while ($true) {
    $running = Get-RunningFlClash
    if (-not $running) { return $true }
    $names = ($running | Select-Object -ExpandProperty Name -Unique) -join ', '
    $msg = "检测到 FlClash 仍在运行：$names`n`n为避免突然断网，本脚本不会强制结束进程。`n请先在 FlClash 里关闭系统代理，再完全退出程序，然后点「重试」。`n`n若暂时不想更新，点「取消」。"
    $r = Show-RetryCancel $msg
    if ($r -eq [System.Windows.Forms.DialogResult]::Cancel) { return $false }
  }
}

function Get-LatestRelease {
  $headers = @{
    'User-Agent' = 'FlClash-Portable-Updater'
    'Accept'     = 'application/vnd.github+json'
  }
  try {
    return Invoke-RestMethod -Uri $RepoApi -Headers $headers -TimeoutSec 60
  } catch {
    $mirrors = @(
      'https://ghfast.top/https://api.github.com/repos/chen08209/FlClash/releases/latest',
      'https://ghproxy.net/https://api.github.com/repos/chen08209/FlClash/releases/latest',
      'https://gh-proxy.com/https://api.github.com/repos/chen08209/FlClash/releases/latest',
      'https://mirror.ghproxy.com/https://api.github.com/repos/chen08209/FlClash/releases/latest'
    )
    foreach ($m in $mirrors) {
      try {
        return Invoke-RestMethod -Uri $m -Headers $headers -TimeoutSec 60
      } catch { }
    }
    throw
  }
}

function Get-DownloadCandidates {
  param([string]$Url)
  return @(
    $Url,
    ("https://ghfast.top/{0}" -f $Url),
    ("https://ghproxy.net/{0}" -f $Url),
    ("https://gh-proxy.com/{0}" -f $Url),
    ("https://mirror.ghproxy.com/{0}" -f $Url)
  )
}

function Update-StableJunction {
  param([string]$TargetPath)
  if (Test-Path $StableLink) {
    $item = Get-Item $StableLink -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      cmd /c "rmdir `"$StableLink`"" | Out-Null
    } elseif ($item.PSIsContainer) {
      throw ("{0} 已存在且不是联接，请手动处理后重试。" -f $StableLink)
    }
  }
  cmd /c "mklink /J `"$StableLink`" `"$TargetPath`"" | Out-Null
}

function Test-Sha256 {
  param($Release, [string]$AssetName, [string]$ZipPath)
  $sumsAsset = $Release.assets | Where-Object { $_.name -eq 'SHA256SUMS' } | Select-Object -First 1
  if (-not $sumsAsset) { return }
  try {
    $sumsText = $null
    foreach ($url in (Get-DownloadCandidates $sumsAsset.browser_download_url)) {
      try {
        $sumsText = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 60).Content
        break
      } catch { }
    }
    if (-not $sumsText) { return }
    $line = ($sumsText -split "`n" | Where-Object { $_ -match [regex]::Escape($AssetName) } | Select-Object -First 1)
    if ($line -match '([A-Fa-f0-9]{64})') {
      $expect = $Matches[1].ToLowerInvariant()
      $actual = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($expect -ne $actual) {
        Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
        throw "校验失败（SHA256 不匹配）"
      }
      Write-Log 'SHA256 OK'
    }
  } catch {
    if ($_.Exception.Message -match 'SHA256') { throw }
    Write-Log ("SHA256 skip: {0}" -f $_.Exception.Message)
  }
}

function Install-ReleasePayload {
  param(
    $Release,
    [string]$Tag,
    [switch]$RequireExit
  )
  $asset = $Release.assets | Where-Object { $_.name -like "*$AssetSuffix" } | Select-Object -First 1
  if (-not $asset) { throw "GitHub 上未找到 $AssetSuffix 资源" }

  $destDir = Join-Path $ToolRoot ("FlClash-{0}-windows-amd64" -f $Tag)
  $zipPath = Join-Path $env:TEMP ("FlClash-{0}-windows-amd64.zip" -f $Tag)
  $extract = Join-Path $env:TEMP ("FlClash-extract-{0}" -f $Tag)

  if (Test-Path $destDir) {
    if (-not (Test-Path (Join-Path $destDir 'FlClash.exe'))) {
      throw ("目标目录已存在但不完整：{0}" -f $destDir)
    }
    Update-StableJunction -TargetPath $destDir
    Save-State -Path $destDir -Version $Tag
    return $destDir
  }

  Write-Log ("Downloading {0}" -f $asset.browser_download_url)
  $downloaded = $false
  foreach ($url in (Get-DownloadCandidates $asset.browser_download_url)) {
    try {
      Write-Log ("Try URL {0}" -f $url)
      Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing -TimeoutSec 600
      $downloaded = $true
      break
    } catch {
      Write-Log ("Download failed: {0}" -f $_.Exception.Message)
    }
  }
  if (-not $downloaded) { throw '下载失败。请检查网络后重试。' }

  Test-Sha256 -Release $Release -AssetName $asset.name -ZipPath $zipPath

  if ($RequireExit) {
    $readyMsg = "安装包已下载完成（v$Tag）。`n`n下一步需要替换程序文件。请先：`n1. 在 FlClash 中关闭系统代理 / TUN`n2. 完全退出 FlClash（托盘图标也要退出）`n`n准备好后点「是」继续。`n点「否」取消（已下载的安装包会保留在临时目录，下次可再跑脚本）。"
    $ready = Show-YesNo $readyMsg
    if ($ready -ne [System.Windows.Forms.DialogResult]::Yes) {
      Write-Log 'User cancelled after download'
      return $null
    }
    if (-not (Wait-FlClashExit)) {
      Write-Log 'User cancelled while waiting for exit'
      Show-Info '已取消更新。FlClash 保持原样。'
      return $null
    }
  }

  if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
  New-Item -ItemType Directory -Path $extract -Force | Out-Null
  Expand-Archive -Path $zipPath -DestinationPath $extract -Force

  $payload = $extract
  $children = Get-ChildItem $extract -Force
  if ($children.Count -eq 1 -and $children[0].PSIsContainer) {
    $payload = $children[0].FullName
  }
  if (-not (Test-Path (Join-Path $payload 'FlClash.exe'))) {
    throw '解压后未找到 FlClash.exe'
  }

  Move-Item -Path $payload -Destination $destDir
  Update-StableJunction -TargetPath $destDir
  Save-State -Path $destDir -Version $Tag

  Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
  if (Test-Path $extract) { Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue }

  Write-Log ("Installed {0} @ {1}" -f $Tag, $destDir)
  return $destDir
}

# --- main ---
try {
  if (-not (Test-Path $ToolRoot)) {
    New-Item -ItemType Directory -Path $ToolRoot -Force | Out-Null
  }

  Write-Log 'Check started'
  $state = Read-State

  if ($Bootstrap) {
    Write-Log 'Bootstrap mode'
    if ($state.currentPath -and $state.currentVersion -and (Test-Path (Join-Path $state.currentPath 'FlClash.exe'))) {
      Update-StableJunction -TargetPath $state.currentPath
      Save-State -Path $state.currentPath -Version $state.currentVersion
      Write-Log ("Bootstrap: existing v{0}" -f $state.currentVersion)
      exit 0
    }

    $release = Get-LatestRelease
    $tag = $release.tag_name.TrimStart('v')
    Write-Log ("Bootstrap download v{0}" -f $tag)
    $dest = Install-ReleasePayload -Release $release -Tag $tag
    if (-not $dest) { exit 1 }
    exit 0
  }

  if (-not $state.currentPath -or -not $state.currentVersion) {
    Show-Info "未找到 FlClash 便携版安装目录。`n请确认位于 $ToolRoot\FlClash-*-windows-amd64`n或先运行「一键部署」。"
    Write-Log 'ERROR: install not found'
    exit 1
  }

  $localVer = [version]$state.currentVersion
  Write-Log ("Local {0} @ {1}" -f $state.currentVersion, $state.currentPath)

  $release = Get-LatestRelease
  $tag = $release.tag_name.TrimStart('v')
  $remoteVer = [version]$tag
  Write-Log ("Remote {0}" -f $tag)

  if ($remoteVer -le $localVer) {
    Write-Log 'Already up to date'
    if ($ForcePrompt -or -not $SilentCheck) {
      Show-Info ("当前已是最新版 v{0}，无需更新。" -f $state.currentVersion)
    }
    exit 0
  }

  $askMsg = "发现 FlClash 新版本：`n`n  当前：v$($state.currentVersion)`n  最新：v$tag`n`n是否开始更新？`n`n说明：`n1. 会先下载安装包（此时可保持 FlClash 运行，避免断网）`n2. 下载完成后会再提示你手动退出 FlClash`n3. 脚本绝不会强制结束进程`n4. 订阅/配置在 AppData，一般不受影响"
  $ask = Show-YesNo $askMsg
  if ($ask -ne [System.Windows.Forms.DialogResult]::Yes) {
    Write-Log 'User declined update'
    exit 0
  }

  $dest = Install-ReleasePayload -Release $release -Tag $tag -RequireExit
  if (-not $dest) { exit 0 }

  Show-Info ("更新完成：v{0} → v{1}`n`n请使用稳定入口启动：`n  {2}\FlClash.exe`n`n旧版目录仍保留：`n  {3}`n`n确认新版本正常后，可自行删除旧目录。" -f $state.currentVersion, $tag, $StableLink, $state.currentPath)
  exit 0
}
catch {
  Write-Log ("ERROR: {0}" -f $_.Exception.Message)
  if (-not $SilentCheck -or $Bootstrap -or $ForcePrompt) {
    Show-Info ("更新出错：`n{0}`n`n详情见日志：`n{1}" -f $_.Exception.Message, $LogPath)
  }
  exit 1
}
