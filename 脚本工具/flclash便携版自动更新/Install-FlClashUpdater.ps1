#Requires -Version 5.1
<#
.SYNOPSIS
  One-click deploy from this folder (relative paths).
  FlClash programs install to installRoot in config.ini (default D:\tool).
#>
[CmdletBinding()]
param(
  [string]$InstallRoot
)

$ErrorActionPreference = 'Stop'
$UpdaterDir = $PSScriptRoot
$ConfigPath = Join-Path $UpdaterDir 'config.ini'
$TaskName   = 'FlClash Portable Updater'

Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Show-Info {
  param([string]$Text, [string]$Title = 'FlClash 一键部署')
  [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
  ) | Out-Null
}

function Show-Error {
  param([string]$Text, [string]$Title = 'FlClash 一键部署')
  [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Error
  ) | Out-Null
}

function Resolve-InstallRoot {
  param([string]$Override)
  if ($Override) { return $Override }
  $root = $null
  if (Test-Path $ConfigPath) {
    Get-Content $ConfigPath -Encoding UTF8 | ForEach-Object {
      if ($_ -match '^\s*installRoot\s*=\s*(.+)$') { $root = $Matches[1].Trim().Trim('"') }
    }
  }
  if ($root) { return $root }
  if (Test-Path 'D:\') { return 'D:\tool' }
  return (Join-Path $env:LOCALAPPDATA 'FlClash')
}

function Save-Config {
  param([string]$Root)
  @(
    '# FlClash install root (program files). Tools live next to this config.',
    "installRoot=$Root"
  ) | Set-Content -Path $ConfigPath -Encoding UTF8
}

function Test-IsElevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Register-FlClashTask {
  $ps1 = Join-Path $UpdaterDir 'Update-FlClash.ps1'
  $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`" -SilentCheck"

  $registerInline = {
    param([string]$Name, [string]$Argument, [string]$User)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    $action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $Argument
    $trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '10:00'
    $settings = New-ScheduledTaskSettingsSet `
      -AllowStartIfOnBatteries `
      -DontStopIfGoingOnBatteries `
      -StartWhenAvailable `
      -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
      -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    $desc = 'Weekly FlClash portable update check. One confirm then auto stop/install/remove old/start.'
    Register-ScheduledTask `
      -TaskName $Name `
      -Action $action `
      -Trigger $trigger `
      -Settings $settings `
      -Principal $principal `
      -Description $desc `
      -Force | Out-Null
  }

  try {
    & $registerInline -Name $TaskName -Argument $arg -User $env:USERNAME
    return
  } catch {
    if (Test-IsElevated) { throw }
  }

  # Many machines deny Register-ScheduledTask without elevation.
  $tmp = Join-Path $env:TEMP ("FlClash-reg-task-{0}.ps1" -f [guid]::NewGuid().ToString('N'))
  $marker = Join-Path $env:TEMP ("FlClash-reg-task-{0}.ok" -f [guid]::NewGuid().ToString('N'))
  $safeArg = $arg.Replace("'", "''")
  $safeUser = $env:USERNAME.Replace("'", "''")
  $safeName = $TaskName.Replace("'", "''")
  @"
`$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName '$safeName' -Confirm:`$false -ErrorAction SilentlyContinue
`$action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '$safeArg'
`$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '10:00'
`$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
`$principal = New-ScheduledTaskPrincipal -UserId '$safeUser' -LogonType Interactive -RunLevel Limited
`$desc = 'Weekly FlClash portable update check. One confirm then auto stop/install/remove old/start.'
Register-ScheduledTask -TaskName '$safeName' -Action `$action -Trigger `$trigger -Settings `$settings -Principal `$principal -Description `$desc -Force | Out-Null
'OK' | Set-Content -Path '$($marker.Replace("'","''"))' -Encoding UTF8
"@ | Set-Content -Path $tmp -Encoding UTF8

  try {
    $p = Start-Process -FilePath 'powershell.exe' `
      -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tmp) `
      -Verb RunAs -Wait -PassThru
  } catch {
    throw '需要管理员权限才能注册计划任务。请在 UAC 提示时选择「是」。'
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }

  $ok = Test-Path $marker
  Remove-Item $marker -Force -ErrorAction SilentlyContinue
  if ($null -eq $p -or $p.ExitCode -ne 0 -or -not $ok) {
    throw '注册计划任务失败（可能取消了 UAC，或权限不足）。'
  }
}

function New-Shortcut {
  param(
    [string]$LinkPath,
    [string]$TargetPath,
    [string]$WorkingDirectory,
    [string]$Description
  )
  $wsh = New-Object -ComObject WScript.Shell
  $sc = $wsh.CreateShortcut($LinkPath)
  $sc.TargetPath = $TargetPath
  if ($WorkingDirectory) { $sc.WorkingDirectory = $WorkingDirectory }
  if ($Description) { $sc.Description = $Description }
  if (Test-Path $TargetPath) {
    $sc.IconLocation = "$TargetPath,0"
  }
  $sc.Save()
}

function Ensure-DesktopShortcuts {
  param([string]$ToolRoot)
  $desktop = [Environment]::GetFolderPath('Desktop')
  $exe = Join-Path $ToolRoot 'FlClash\FlClash.exe'
  $checkBat = Join-Path $UpdaterDir '手动更新.bat'
  if (-not (Test-Path $checkBat)) {
    $checkBat = Join-Path $UpdaterDir '检查更新.bat'
  }

  if (Test-Path $exe) {
    New-Shortcut `
      -LinkPath (Join-Path $desktop 'FlClash.lnk') `
      -TargetPath $exe `
      -WorkingDirectory (Split-Path $exe -Parent) `
      -Description 'FlClash (stable junction)'
  }
  if (Test-Path $checkBat) {
    New-Shortcut `
      -LinkPath (Join-Path $desktop 'FlClash 手动更新.lnk') `
      -TargetPath $checkBat `
      -WorkingDirectory $UpdaterDir `
      -Description '手动更新 FlClash（一次确认后自动完成）'
  }
}

# --- main ---
try {
  $resolvedRoot = Resolve-InstallRoot -Override $InstallRoot
  Save-Config -Root $resolvedRoot

  $confirm = @"
工具目录（本文件夹）：
  $UpdaterDir

FlClash 安装目录：
  $resolvedRoot

将完成：
1. 写入 config.ini（installRoot）
2. 下载并安装最新 FlClash 便携版（若尚未安装）
3. 创建稳定入口联接：$resolvedRoot\FlClash
4. 注册每周一 10:00 自动检查更新
5. 创建桌面快捷方式

点确定开始。
"@
  Show-Info $confirm

  if (-not (Test-Path $resolvedRoot)) {
    New-Item -ItemType Directory -Path $resolvedRoot -Force | Out-Null
  }

  $updatePs1 = Join-Path $UpdaterDir 'Update-FlClash.ps1'
  $boot = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', $updatePs1, '-Bootstrap'
  ) -Wait -PassThru -WindowStyle Normal

  if ($boot.ExitCode -ne 0) {
    throw "首次安装 / Bootstrap 失败（退出码 $($boot.ExitCode)）。详见 $(Join-Path $UpdaterDir 'update.log')"
  }

  Register-FlClashTask
  Ensure-DesktopShortcuts -ToolRoot $resolvedRoot

  $statePath = Join-Path $UpdaterDir 'state.ini'
  $ver = '?'
  if (Test-Path $statePath) {
    $line = Get-Content $statePath -Encoding UTF8 | Where-Object { $_ -match '^currentVersion=' } | Select-Object -First 1
    if ($line) { $ver = $line.Split('=')[1].Trim() }
  }

  Show-Info @"
部署完成。

工具目录：$UpdaterDir
安装根目录：$resolvedRoot
FlClash 版本：v$ver
稳定入口：$resolvedRoot\FlClash\FlClash.exe
计划任务：$TaskName（每周一 10:00）

桌面已创建：
  · FlClash
  · FlClash 手动更新

手动验收可运行本目录「手动更新.bat」。
如需移除自动更新，运行本目录下的「卸载.bat」。
"@
  exit 0
}
catch {
  Show-Error ("部署失败：`n{0}" -f $_.Exception.Message)
  exit 1
}
