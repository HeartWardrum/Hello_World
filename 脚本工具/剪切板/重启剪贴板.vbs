Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strScript = strDir & "\clipboard_manager_v2.py"
strMatch = "clipboard_manager_v2.py"

strKill = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" & strMatch & "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
objShell.Run strKill, 0, True

WScript.Sleep 500

strPythonW = "pythonw.exe"
strPythonWLocal = objShell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\Python\Python312\pythonw.exe"
If objFSO.FileExists(strPythonWLocal) Then
    strPythonW = """" & strPythonWLocal & """"
End If

objShell.CurrentDirectory = strDir
objShell.Run strPythonW & " """ & strScript & """", 0, False
