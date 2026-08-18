Option Explicit
Dim sh, fso, ps1, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ps1 = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "Install-ContextMenu.ps1")
If Not fso.FileExists(ps1) Then
  MsgBox "Missing Install-ContextMenu.ps1", 16, "Install"
  WScript.Quit 1
End If
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File """ & ps1 & """"
sh.Run cmd, 1, True