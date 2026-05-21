Set objShell = WScript.CreateObject("WScript.Shell")
Set objFSO = WScript.CreateObject("Scripting.FileSystemObject")

' 自动获取当前 VBS 脚本所在的文件夹路径，无需手动修改
strRepoPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = strRepoPath

' 生成自动提交的描述信息 (使用当前时间)
strCommitMsg = "Auto commit: " & Now

' 拼接完整的 Git 命令
strCommand = "cmd.exe /c git add . && git commit -m """ & strCommitMsg & """ && git push"

' 执行命令 (0 表示隐藏 CMD 窗口，True 表示等待执行完毕)
intReturn = objShell.Run(strCommand, 0, True)

