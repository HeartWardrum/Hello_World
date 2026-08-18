$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms | Out-Null
try {
    Remove-Item -Path "HKCU:\Software\Classes\Directory\shell\SetFolderAlias" -Recurse -Force -ErrorAction SilentlyContinue
    [void][System.Windows.Forms.MessageBox]::Show(
        "已卸载右键菜单「设置显示名称（不改路径）」。",
        "卸载右键菜单",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )
}
catch {
    [void][System.Windows.Forms.MessageBox]::Show(
        $_.Exception.Message, "卸载右键菜单",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
    exit 1
}
