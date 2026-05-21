Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set colItems = objWMIService.ExecQuery("Select * from Win32_Process Where Name = 'powershell.exe'")

Dim count
count = 0

For Each objItem in colItems
    ' 增加安全防御：防止部分系统进程的 CommandLine 为空导致报错
    If Not IsNull(objItem.CommandLine) Then
        If InStr(objItem.CommandLine, "VimArrows.ps1") > 0 Then
            objItem.Terminate()
            count = count + 1
        End If
    End If
Next

If count > 0 Then
    MsgBox "Mapping closed successfully!", 64, "Notice"
Else
    MsgBox "No active mapping process found.", 48, "Notice"
End If