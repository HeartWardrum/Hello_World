Option Explicit

Dim shell, fso, repoPaths, repo, commitMsg, curTime, execObj, gitStatus

' ==========================================
' 【配置】支持中文路径！确保每个路径用双引号包裹
' ==========================================
repoPaths = Array( _
    "D:\我的项目\测试仓库", _
    "E:\笔记\我的Markdown笔记" _
)

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

For Each repo In repoPaths
    ' 检查目录和 .git 文件夹是否存在
    If fso.FolderExists(repo) And fso.FolderExists(repo & "\.git") Then
        
        shell.CurrentDirectory = repo
        
        ' 升级：改用 Exec 并在后台读取状态，彻底避开中文文件名在命令行中的匹配问题
        Set execObj = shell.Exec("cmd /c chcp 65001 >nul && git status --porcelain")
        gitStatus = execObj.StdOut.ReadAll()
        
        ' 如果状态输出不为空，说明有文件变动（修改、新增或删除）
        If Trim(gitStatus) <> "" Then
            
            ' 格式化时间，自动补 0
            curTime = Right("0" & Hour(Time), 2) & ":" & Right("0" & Minute(Time), 2) & ":" & Right("0" & Second(Time), 2)
            commitMsg = "Auto-commit: " & Date & "_" & curTime
            
            ' 静默执行 Git 命令
            shell.Run "cmd /c chcp 65001 >nul && git add .", 0, True
            shell.Run "cmd /c chcp 65001 >nul && git commit -m """ & commitMsg & """", 0, True
            shell.Run "cmd /c chcp 65001 >nul && git push origin main", 0, True
            
        End If
    End If
Next

Set shell = Nothing
Set fso = Nothing
Set execObj = Nothing