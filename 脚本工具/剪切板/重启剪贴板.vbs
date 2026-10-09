Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strScript = strDir & "\clipboard_manager_v2.py"
strMatch = "clipboard_manager_v2.py"

' 杀掉之前可能卡在后台的旧进程
strKill = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" & strMatch & "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
objShell.Run strKill, 0, True

WScript.Sleep 500

' 关键修改：直接使用你刚才安装了 PyQt5 等库的 pyenv 3.8.10 环境的 pythonw.exe
strPythonW = "C:\Users\th952\.pyenv\pyenv-win\versions\3.8.10\pythonw.exe"

objShell.CurrentDirectory = strDir
' 运行程序（加上引号防止路径中有空格）
objShell.Run """" & strPythonW & """ """ & strScript & """", 0, False