#Requires -Version 5.1
<#
.SYNOPSIS
  FlClash portable updater.
  One confirm → download → stop FlClash → install → remove old → start new.
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
    [System.Windows.Forms.MessageBoxDefaultButton]::Button1
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

function Test-FlClashHelperServiceRunning {
  $svc = Get-Service -Name 'FlClashHelperService' -ErrorAction SilentlyContinue
  return ($null -ne $svc -and "$($svc.Status)" -eq 'Running')
}

function Stop-FlClashUserProcesses {
  param([int]$GraceSeconds = 5)

  $ui = @(Get-Process -Name 'FlClash' -ErrorAction SilentlyContinue)
  foreach ($p in $ui) {
    try {
      if ($p.MainWindowHandle -ne [IntPtr]::Zero) {
        $p.CloseMainWindow() | Out-Null
      }
    } catch { }
  }

  $deadline = (Get-Date).AddSeconds($GraceSeconds)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
    if (-not (Get-Process -Name @('FlClash', 'FlClashCore') -ErrorAction SilentlyContinue)) {
      return
    }
  }

  Get-Process -Name @('FlClash', 'FlClashCore') -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 400
}

function Stop-FlClashElevated {
  # HelperService runs as LocalSystem; stopping it needs admin (UAC).
  $tmp = Join-Path $env:TEMP ("FlClash-stop-{0}.ps1" -f [guid]::NewGuid().ToString('N'))
  $elevLog = Join-Path $env:TEMP ("FlClash-stop-{0}.log" -f [guid]::NewGuid().ToString('N'))

  $script = @"
`$ErrorActionPreference = 'Continue'
`$log = '$($elevLog.Replace("'", "''"))'
function L(`$m) { Add-Content -Path `$log -Value (('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), `$m)) -Encoding UTF8 }
L 'elevated stop begin'
try {
  `$svc = Get-Service -Name 'FlClashHelperService' -ErrorAction SilentlyContinue
  if (`$svc) {
    L ('service status=' + `$svc.Status)
    if (`$svc.Status -ne 'Stopped') {
      Stop-Service -Name 'FlClashHelperService' -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 500
    }
  }
} catch { L ('Stop-Service: ' + `$_.Exception.Message) }
try { & sc.exe stop FlClashHelperService | Out-Null } catch {}
foreach (`$n in @('FlClash','FlClashCore','FlClashHelperService')) {
  Get-Process -Name `$n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
`$deadline = (Get-Date).AddSeconds(12)
while ((Get-Date) -lt `$deadline) {
  Start-Sleep -Milliseconds 400
  `$left = @(Get-Process -Name @('FlClash','FlClashCore','FlClashHelperService') -ErrorAction SilentlyContinue)
  if (-not `$left) { break }
  `$left | Stop-Process -Force -ErrorAction SilentlyContinue
  try { Stop-Service -Name 'FlClashHelperService' -Force -ErrorAction SilentlyContinue } catch {}
}
`$still = @(Get-Process -Name @('FlClash','FlClashCore','FlClashHelperService') -ErrorAction SilentlyContinue)
if (`$still) {
  L ('FAIL still running: ' + ((`$still | Select-Object -ExpandProperty Name -Unique) -join ', '))
  exit 1
}
L 'elevated stop ok'
exit 0
"@
  Set-Content -Path $tmp -Value $script -Encoding UTF8
  Write-Log 'Requesting admin to stop FlClashHelperService (UAC)'

  try {
    $p = Start-Process -FilePath 'powershell.exe' `
      -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tmp) `
      -Verb RunAs -Wait -PassThru
  } catch {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    throw '需要管理员权限才能停止 FlClashHelperService。请在 UAC 提示时选择「是」。'
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }

  if (Test-Path $elevLog) {
    Get-Content $elevLog -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Log ("elev: {0}" -f $_) }
    Remove-Item $elevLog -Force -ErrorAction SilentlyContinue
  }

  if ($null -eq $p -or $p.ExitCode -ne 0) {
    throw '管理员提权结束 FlClash 失败（可能取消了 UAC，或服务仍在运行）。'
  }
}

function Stop-FlClashProcesses {
  $running = @(Get-RunningFlClash)
  $svcRunning = Test-FlClashHelperServiceRunning
  if (-not $running -and -not $svcRunning) {
    Write-Log 'FlClash not running'
    return
  }

  $names = @()
  if ($running) { $names += ($running | Select-Object -ExpandProperty Name -Unique) }
  if ($svcRunning) { $names += 'FlClashHelperService(service)' }
  Write-Log ("Stopping FlClash: {0}" -f (($names | Select-Object -Unique) -join ', '))

  Stop-FlClashUserProcesses

  # HelperService is LocalSystem — always elevate when present
  if ((Get-RunningFlClash) -or (Test-FlClashHelperServiceRunning)) {
    Stop-FlClashElevated
  }

  Start-Sleep -Milliseconds 500
  if ((Get-RunningFlClash) -or (Test-FlClashHelperServiceRunning)) {
    throw '无法结束 FlClash 进程/服务，请手动退出后重试。'
  }
  Write-Log 'FlClash stopped'
}

function Remove-OldInstall {
  param(
    [string]$OldPath,
    [string]$NewPath
  )
  if (-not $OldPath) { return }
  if (-not (Test-Path $OldPath)) { return }
  if ($OldPath -eq $NewPath) { return }

  # Never delete the stable junction itself
  if ([IO.Path]::GetFullPath($OldPath).TrimEnd('\') -eq [IO.Path]::GetFullPath($StableLink).TrimEnd('\')) {
    Write-Log 'Skip delete: old path is stable junction'
    return
  }

  try {
    Remove-Item -LiteralPath $OldPath -Recurse -Force -ErrorAction Stop
    Write-Log ("Removed old install {0}" -f $OldPath)
  } catch {
    Write-Log ("WARN: failed to remove old install: {0}" -f $_.Exception.Message)
  }
}

function Show-FlClashWindow {
  # Bring FlClash main window to foreground (may start hidden / tray-only).
  if (-not ('FlClashWin32' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class FlClashWin32 {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder s, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
  public static bool Activate(int[] pids) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint pid;
      GetWindowThreadProcessId(h, out pid);
      bool match = false;
      for (int i = 0; i < pids.Length; i++) if (pids[i] == (int)pid) { match = true; break; }
      if (!match) return true;
      var sb = new StringBuilder(256);
      GetWindowText(h, sb, 256);
      string title = sb.ToString();
      RECT r;
      if (!GetWindowRect(h, out r)) return true;
      int w = r.R - r.L, hgt = r.B - r.T;
      // Prefer titled / sized windows; skip tiny tool windows
      if (w < 100 || hgt < 100) return true;
      if (title.IndexOf("FlClash", StringComparison.OrdinalIgnoreCase) < 0 && !IsWindowVisible(h)) return true;
      found = h;
      return false;
    }, IntPtr.Zero);
    if (found == IntPtr.Zero) return false;
    ShowWindow(found, 9); // SW_RESTORE
    SetForegroundWindow(found);
    return true;
  }
}
"@
  }

  $ids = @(Get-Process -Name 'FlClash' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
  if (-not $ids) { return $false }
  try { return [FlClashWin32]::Activate($ids) } catch { return $false }
}

function Start-FlClash {
  param([string]$InstallDir)

  if (-not $InstallDir) { $InstallDir = $StableLink }
  $exe = Join-Path $InstallDir 'FlClash.exe'
  if (-not (Test-Path $exe)) {
    $exe = Join-Path $StableLink 'FlClash.exe'
    $InstallDir = $StableLink
  }
  if (-not (Test-Path $exe)) {
    throw ("启动失败：未找到 {0}" -f $exe)
  }

  # Allow locks/mutex from force-stop to release
  Start-Sleep -Seconds 2

  Write-Log ("Starting {0}" -f $exe)
  Start-Process -FilePath $exe -WorkingDirectory $InstallDir -WindowStyle Normal | Out-Null

  $ready = $false
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Get-Process -Name 'FlClash' -ErrorAction SilentlyContinue) {
      $ready = $true
      break
    }
  }

  if (-not $ready) {
    Write-Log 'First start: process not found, retry'
    Start-Process -FilePath $exe -WorkingDirectory $InstallDir -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Name 'FlClash' -ErrorAction SilentlyContinue)) {
      throw '已尝试启动 FlClash，但进程未出现。请手动运行稳定入口。'
    }
  }

  # FlClash is single-instance: a second launch activates / shows the existing window
  Start-Sleep -Milliseconds 800
  Start-Process -FilePath $exe -WorkingDirectory $InstallDir -WindowStyle Normal | Out-Null
  Start-Sleep -Milliseconds 800

  if (Show-FlClashWindow) {
    Write-Log 'FlClash window activated'
  } else {
    Write-Log 'FlClash process running (window may be in tray)'
  }

  $proc = Get-Process -Name 'FlClash' -ErrorAction SilentlyContinue | Select-Object -First 1
  Write-Log ("Started OK pid={0} path={1}" -f $(if ($proc) { $proc.Id } else { '?' }), $exe)
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
    [switch]$StopBeforeInstall
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
    if ($StopBeforeInstall) { Stop-FlClashProcesses }
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

  if ($StopBeforeInstall) {
    Stop-FlClashProcesses
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

  $askMsg = @"
发现 FlClash 新版本：

  当前：v$($state.currentVersion)
  最新：v$tag

确认后将自动完成：
1. 下载安装包（下载期间可继续使用）
2. 退出 FlClash（Helper 服务需 UAC 提权一次）
3. 安装新版本并切换稳定入口
4. 删除旧版本目录
5. 启动新版本

是否开始更新？
"@
  $ask = Show-YesNo $askMsg
  if ($ask -ne [System.Windows.Forms.DialogResult]::Yes) {
    Write-Log 'User declined update'
    exit 0
  }

  $oldPath = $state.currentPath
  $oldVer  = $state.currentVersion

  $dest = Install-ReleasePayload -Release $release -Tag $tag -StopBeforeInstall
  if (-not $dest) { exit 0 }

  Remove-OldInstall -OldPath $oldPath -NewPath $dest
  Start-FlClash -InstallDir $dest

  Show-Info ("更新完成：v{0} → v{1}`n`n已启动新版本（若未看到窗口，请点托盘图标）。`n稳定入口：`n  {2}\FlClash.exe" -f $oldVer, $tag, $StableLink)
  exit 0
}
catch {
  Write-Log ("ERROR: {0}" -f $_.Exception.Message)
  if (-not $SilentCheck -or $Bootstrap -or $ForcePrompt) {
    Show-Info ("更新出错：`n{0}`n`n详情见日志：`n{1}" -f $_.Exception.Message, $LogPath)
  }
  exit 1
}
