# Set Explorer display name without renaming the real folder path.
# Compatible with PowerShell 5.1 and folder names that contain [ ].
param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$FolderPath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Show-Info([string]$Message) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message, "设置显示名称",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )
}

function Show-Error([string]$Message) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message, "设置显示名称",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
}

function Read-DisplayName([string]$Path) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "设置文件夹显示名称"
    $form.Width = 540
    $form.Height = 280
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.ShowInTaskbar = $true

    $label = New-Object System.Windows.Forms.Label
    $label.Left = 12
    $label.Top = 12
    $label.Width = 500
    $label.Height = 120
    $label.Text = "真实路径（不会改）:`r`n$Path`r`n`r`n输入资源管理器里要显示的中文名。`r`n点取消 = 什么都不做；输入 CLEAR 再确定 = 清除显示名。"

    $box = New-Object System.Windows.Forms.TextBox
    $box.Left = 12
    $box.Top = 140
    $box.Width = 500

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "确定"
    $ok.Left = 336
    $ok.Top = 180
    $ok.Width = 85
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "取消"
    $cancel.Left = 427
    $cancel.Top = 180
    $cancel.Width = 85
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel

    $form.AcceptButton = $ok
    $form.CancelButton = $cancel
    $form.Controls.AddRange(@($label, $box, $ok, $cancel)) | Out-Null
    $result = $form.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    return $box.Text
}

function Update-Explorer([string]$Path) {
    try {
        $type = @"
using System;
using System.Runtime.InteropServices;
public static class FolderAliasShell {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern void SHChangeNotify(int eventId, uint flags, string item1, IntPtr item2);
}
"@
        if (-not ("FolderAliasShell" -as [type])) {
            Add-Type -TypeDefinition $type
        }
        $updateItem = 0x00002000
        $updateDir  = 0x00001000
        $pathW      = 0x0005
        $flush      = 0x1000
        [FolderAliasShell]::SHChangeNotify($updateItem, $pathW -bor $flush, $Path, [IntPtr]::Zero)
        $parent = [IO.Path]::GetDirectoryName($Path)
        if ($parent) {
            [FolderAliasShell]::SHChangeNotify($updateDir, $pathW -bor $flush, $parent, [IntPtr]::Zero)
        }
    } catch {
        # Refresh is best-effort; writing desktop.ini still succeeded.
    }
}

function Set-DirFlag([string]$Path, [IO.FileAttributes]$Flag, [bool]$Enable) {
    $attr = [IO.File]::GetAttributes($Path)
    if ($Enable) {
        $attr = $attr -bor $Flag
    } else {
        $attr = $attr -band (-bnot $Flag)
    }
    [IO.File]::SetAttributes($Path, $attr)
}

try {
    if ([string]::IsNullOrWhiteSpace($FolderPath)) {
        Show-Error "未收到文件夹路径。请通过资源管理器右键菜单运行，或重新双击「安装右键菜单.vbs」。"
        exit 1
    }

    $FolderPath = $FolderPath.TrimEnd('\')
    if (-not (Test-Path -LiteralPath $FolderPath -PathType Container)) {
        Show-Error "文件夹不存在:`r`n$FolderPath"
        exit 1
    }

    $name = Read-DisplayName $FolderPath
    if ($null -eq $name -or $name -eq "") {
        exit 0
    }

    $ini = Join-Path $FolderPath "desktop.ini"
    if (Test-Path -LiteralPath $ini) {
        [IO.File]::SetAttributes($ini, [IO.FileAttributes]::Normal)
    }

    if ($name.Trim().ToUpperInvariant() -eq "CLEAR") {
        if (Test-Path -LiteralPath $ini) {
            Remove-Item -LiteralPath $ini -Force
        }
        Set-DirFlag $FolderPath ([IO.FileAttributes]::ReadOnly) $false
        Set-DirFlag $FolderPath ([IO.FileAttributes]::System) $false
        Update-Explorer $FolderPath
        Show-Info "已清除显示名。`r`n`r`n请关掉当前窗口再打开该目录。若仍是旧名，可对该文件夹：`r`n属性 → 自定义 → 更改图标 → 还原默认值 → 应用。"
        exit 0
    }

    $text = "[.ShellClassInfo]`r`nLocalizedResourceName=$name`r`nConfirmFileOp=0`r`n"
    [IO.File]::WriteAllText($ini, $text, [Text.Encoding]::Unicode)
    [IO.File]::SetAttributes($ini, [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System)
    Set-DirFlag $FolderPath ([IO.FileAttributes]::ReadOnly) $true
    Set-DirFlag $FolderPath ([IO.FileAttributes]::System) $true

    try { Unblock-File -LiteralPath $ini -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item -LiteralPath ($ini + ":Zone.Identifier") -Force -ErrorAction SilentlyContinue } catch {}

    if (-not (Test-Path -LiteralPath $ini)) {
        Show-Error "写入后找不到 desktop.ini，可能被安全软件删除了。`r`n路径:`r`n$ini"
        exit 1
    }

    Update-Explorer $FolderPath
    Show-Info ("已设置显示名：" + $name + "`r`n`r`n真实路径仍是：`r`n" + $FolderPath + "`r`n`r`n请关掉当前窗口再打开该目录查看。`r`n若仍显示英文：属性 → 自定义 → 更改图标 → 还原默认值 → 应用。")
}
catch {
    Show-Error ("失败：`r`n" + $_.Exception.Message + "`r`n`r`n路径：`r`n" + $FolderPath)
    exit 1
}
