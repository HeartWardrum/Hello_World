Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript = currentDir & "\VimArrows.ps1"

Set ws = CreateObject("Wscript.Shell")
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """", 0, False

' 使用纯英文提示，彻底免疫任何编码格式引发的崩溃
MsgBox "Alt+IJKL mapping started successfully!", 64, "Notice"