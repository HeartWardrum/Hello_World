#w::
{
    ; 配置：将 "yourapp.exe" 替换为你的应用进程名
    TargetApp := "notepad.exe" ; 例如：notepad.exe, msedge.exe, Code.exe

    ; 检查目标应用窗口是否存在
    if (appHwnd := WinExist("ahk_exe " TargetApp)) {
        ; 应用已运行，检查它是否是活动窗口
        if (WinActive("ahk_id " appHwnd)) {
            ; 如果在前台，则最小化
            WinMinimize
        } else {
            ; 如果在后台，则激活并恢复窗口（如果是最小化状态）
            WinActivate
            if (WinGetMinMax() = -1) { ; -1 表示窗口是最小化的
                WinRestore
            }
        }
    } else {
        ; 应用未运行，启动它
        ; 配置：将下面的路径替换为你自己的应用路径或启动命令
        Run "notepad"
        ; 示例：
        ; Run "msedge" ; 启动Microsoft Edge
        ; Run "C:\Program Files\SomeApp\app.exe" ; 使用完整路径启动应用
    }
}
