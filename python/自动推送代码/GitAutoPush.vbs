' 强制声明变量
Option Explicit

Dim shell, fso, repoPaths, repo, commitMsg, curTime

' ==========================================
' 【配置】把你所有的 Git 仓库绝对路径写在下面
'  每个路径用双引号包裹，中间用逗号隔开
' ==========================================
repoPaths = Array( _
    "D:\projects\my-repo-1", _
    "D:\projects\my-repo-2", _
    "E:\notes\my-markdown-notes" _
)

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 循环处理每一个仓库
For Each repo In repoPaths
    ' 检查目录和 .git 文件夹是否存在
    If fso.FolderExists(repo) And fso.FolderExists(repo & "\.git") Then
        
        ' 切换到对应的仓库盘符和目录
        shell.CurrentDirectory = repo
        
        ' 检查是否有文件变动 (0 表示有变动, 1 表示无变动)
        ' 这里的 0, True 是让命令在后台静默运行且等待其执行完毕
        If shell.Run("cmd /c git status --porcelain | findstr /R "". """, 0, True) = 0 Then
            
            ' 格式化时间，自动补 0（完美解决上午10点前的空格Bug）
            curTime = Right("0" & Hour(Time), 2) & ":" & Right("0" & Minute(Time), 2) & ":" & Right("0" & Second(Time), 2)
            commitMsg = "Auto-commit: " & Date & "_" & curTime
            
            ' 静默执行 Git 命令
            ' 最后一个参数 True 表示必须等上一步执行完，再执行下一步
            shell.Run "cmd /c git add .", 0, True
            shell.Run "cmd /c git commit -m """ & commitMsg & """", 0, True
            shell.Run "cmd /c git push origin main", 0, True
            
        End If
    End If
Next

' 释放对象
Set shell = Nothing
Set fso = Nothing