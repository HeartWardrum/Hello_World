# Register Explorer context menu for SetFolderAlias.ps1
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms | Out-Null

function Show-Info([string]$Message) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message, "安装右键菜单",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )
}

function Show-Error([string]$Message) {
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message, "安装右键菜单",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
}

try {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $script = Join-Path $here "SetFolderAlias.ps1"
    if (-not (Test-Path -LiteralPath $script)) {
        Show-Error "找不到脚本：`r`n$script"
        exit 1
    }

    $key = "HKCU:\Software\Classes\Directory\shell\SetFolderAlias"
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(default)" -Value "设置显示名称（不改路径）"
    New-ItemProperty -Path $key -Name "Icon" -Value "shell32.dll,15" -PropertyType String -Force | Out-Null
    New-Item -Path "$key\command" -Force | Out-Null
    $cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -STA -File `"$script`" `"%1`""
    Set-ItemProperty -Path "$key\command" -Name "(default)" -Value $cmd

    Show-Info ("安装完成。`r`n`r`n资源管理器中右键文件夹 → 设置显示名称（不改路径）`r`nWin11 若看不到：先点「显示更多选项」。`r`n`r`n脚本：`r`n" + $script)
}
catch {
    Show-Error $_.Exception.Message
    exit 1
}
