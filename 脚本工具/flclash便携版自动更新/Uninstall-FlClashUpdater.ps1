#Requires -Version 5.1
<#
.SYNOPSIS
  Remove FlClash auto-update scheduled task and desktop shortcuts.
  Does NOT delete FlClash program files or updater scripts.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$TaskName = 'FlClash Portable Updater'

Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Show-YesNo {
  param([string]$Text, [string]$Title = 'FlClash 卸载自动更新')
  return [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
  )
}

function Show-Info {
  param([string]$Text, [string]$Title = 'FlClash 卸载自动更新')
  [System.Windows.Forms.MessageBox]::Show(
    $Text, $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
  ) | Out-Null
}

$ask = Show-YesNo @"
将移除：
1. 计划任务「$TaskName」
2. 桌面快捷方式「FlClash」「FlClash 检查更新」

不会删除：
· FlClash 程序目录
· 本更新工具脚本

是否继续？
"@
if ($ask -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$desktop = [Environment]::GetFolderPath('Desktop')
@(
  'FlClash.lnk',
  'FlClash 检查更新.lnk'
) | ForEach-Object {
  $p = Join-Path $desktop $_
  if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue }
}

Show-Info '已移除计划任务与桌面快捷方式。FlClash 程序仍可正常使用。'
exit 0
