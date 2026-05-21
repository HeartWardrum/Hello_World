' ============================================================
'  GitAutoSync.vbs
'  功能：自动同步、提交并推送多个 Git 仓库
'  支持：仓库路径含中文、每个仓库独立远程地址
'  系统：Windows 11 (VBScript 修复优化版)
' ============================================================

Option Explicit

' ============================================================
'  ★ 配置区域 - 按需修改 ★
' ============================================================

' 仓库列表，格式：本地路径 | 远程仓库URL | 分支名 | 自定义提交前缀（可留空）
' 远程URL 若已通过 git remote set-url 设置好，可填 "已配置" 跳过强制设置
Dim REPO_CONFIG
REPO_CONFIG = Array( _
    "C:\Users\你的用户名\Documents\项目一|https://github.com/你的账号/仓库一.git|main|项目一", _
    "D:\工作\中文路径测试\项目二|https://github.com/你的账号/仓库二.git|master|项目二", _
    "E:\我的代码\项目三|已配置|develop|" _
)

' 提交信息模板（{prefix} = 上方自定义前缀，{date} = 日期，{time} = 时间）
Dim COMMIT_TEMPLATE
COMMIT_TEMPLATE = "{prefix}自动同步 {date} {time}"

' 是否在每次运行完弹出汇总报告（True/False）
Dim SHOW_REPORT
SHOW_REPORT = True

' 日志文件路径（支持环境变量 %USERPROFILE%，留空则不写日志）
Dim LOG_FILE
LOG_FILE = "%USERPROFILE%\Desktop\GitAutoSync.log"

' ============================================================
'  全局变量声明与初始化
' ============================================================

Dim oShell, oFSO, oLog
Dim i, repoLine
Dim report, successCount, failCount, actualLogFile

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")
Randomize ' 初始化随机数种子

' 解析日志路径中的环境变量
If LOG_FILE <> "" Then
    actualLogFile = oShell.ExpandEnvironmentStrings(LOG_FILE)
    On Error Resume Next
    Set oLog = oFSO.OpenTextFile(actualLogFile, 8, True) ' 8 = 追加模式
    If Err.Number <> 0 Then
        MsgBox "无法创建或打开日志文件: " & actualLogFile, vbCritical, "配置错误"
        WScript.Quit
    End If
    On Error GoTo 0
End If

' ============================================================
'  主程序核心逻辑
' ============================================================

Call WriteLog("===============================")
Call WriteLog("GitAutoSync 启动：" & Now())
Call WriteLog("===============================")

report       = "GitAutoSync 运行报告" & vbCrLf & String(40, "=") & vbCrLf
successCount = 0
failCount    = 0

' 遍历每个仓库
For i = 0 To UBound(REPO_CONFIG)
    repoLine = Trim(REPO_CONFIG(i))
    If repoLine <> "" Then
        ' 调用子程序处理单个仓库，规避 VBS 无法使用 GoTo 的限制
        Call ProcessSingleRepo(repoLine)
    End If
Next

' 汇总报告
report = report & vbCrLf & String(40, "=") & vbCrLf
report = report & "完成：" & successCount & " 个成功，" & failCount & " 个失败" & vbCrLf
report = report & "时间：" & Now()

Call WriteLog(report)

' 释放日志对象
If Not oLog Is Nothing Then
    oLog.Close
    Set oLog = Nothing
End If

' 弹出提示框
If SHOW_REPORT Then
    MsgBox report, vbInformation, "GitAutoSync 完成"
End If


' ============================================================
'  核心业务子程序（每个仓库独立运行，Exit Sub 相当于 Continue）
' ============================================================
Sub ProcessSingleRepo(line)
    Dim parts, localPath, remoteURL, branch, prefix
    Dim cdCmd, result, commitMsg

    parts = Split(line, "|")
    If UBound(parts) < 2 Then
        Call WriteLog("配置格式错误，跳过：" & line)
        report = report & vbCrLf & "✗ 配置格式错误: " & line & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If

    localPath = Trim(parts(0))
    remoteURL = Trim(parts(1))
    branch    = Trim(parts(2))
    
    If UBound(parts) >= 3 Then
        prefix = Trim(parts(3))
    Else
        prefix = ""
    End If
    
    If prefix <> "" Then prefix = "[" & prefix & "] "

    report = report & vbCrLf & "仓库：" & localPath & vbCrLf

    ' 1. 检查本地路径是否存在
    If Not oFSO.FolderExists(localPath) Then
        Call WriteLog("路径不存在，跳过：" & localPath)
        report = report & "  ✗ 路径不存在" & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If

    ' 2. 检查是否是 git 仓库
    If Not oFSO.FolderExists(localPath & "\.git") Then
        Call WriteLog("不是 Git 仓库，跳过：" & localPath)
        report = report & "  ✗ 非 Git 仓库" & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If

    ' 构建基础命令框架（chcp 65001 解决 cmd 乱码，&& 确保 cd 成功才执行后续）
    cdCmd = "chcp 65001 >nul && cd /d """ & localPath & """ && "

    ' 3. 设置远程地址（如果不是"已配置"）
    If remoteURL <> "已配置" And remoteURL <> "" Then
        result = RunCmd(cdCmd & "git remote set-url origin """ & remoteURL & """")
        Call WriteLog("设置远程 [" & localPath & "]：" & result)
    End If

    ' 4. git pull（同步远程）
    result = RunCmd(cdCmd & "git pull origin """ & branch & """")
    Call WriteLog("git pull [" & localPath & "]：" & result)
    
    If InStr(LCase(result), "error:") > 0 Or InStr(LCase(result), "fatal:") > 0 Then
        report = report & "  ✗ pull 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If
    report = report & "  ✓ pull 完成" & vbCrLf

    ' 5. git add .
    result = RunCmd(cdCmd & "git add .")
    Call WriteLog("git add [" & localPath & "]：" & result)

    ' 6. 生成提交信息
    commitMsg = COMMIT_TEMPLATE
    commitMsg = Replace(commitMsg, "{prefix}", prefix)
    commitMsg = Replace(commitMsg, "{date}", Format2(Year(Now())) & "-" & Format2(Month(Now())) & "-" & Format2(Day(Now())))
    commitMsg = Replace(commitMsg, "{time}", Format2(Hour(Now())) & ":" & Format2(Minute(Now())) & ":" & Format2(Second(Now())))

    ' 7. git commit
    result = RunCmd(cdCmd & "git commit -m """ & commitMsg & """")
    Call WriteLog("git commit [" & localPath & "]：" & result)

    ' 检查是否有文件变更
    If InStr(LCase(result), "nothing to commit") > 0 Or InStr(LCase(result), "nothing added") > 0 Then
        report = report & "  ➜ 无本地变更，无需提交" & vbCrLf
        successCount = successCount + 1
        Exit Sub
    End If

    If InStr(LCase(result), "error:") > 0 Or InStr(LCase(result), "fatal:") > 0 Then
        report = report & "  ✗ commit 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If
    report = report & "  ✓ commit：" & commitMsg & vbCrLf

    ' 8. git push
    result = RunCmd(cdCmd & "git push origin """ & branch & """")
    Call WriteLog("git push [" & localPath & "]：" & result)

    If InStr(LCase(result), "error:") > 0 Or InStr(LCase(result), "fatal:") > 0 Then
        report = report & "  ✗ push 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        Exit Sub
    End If
    
    report = report & "  ✓ push 完成" & vbCrLf
    successCount = successCount + 1
End Sub

' ============================================================
'  底层的工具函数
' ============================================================

' 执行命令并捕获返回文本（完美的标准输出与错误输出重定向）
Function RunCmd(cmd)
    Dim tmpFile, output, oTmp, tempDir
    
    tempDir = oShell.ExpandEnvironmentStrings("%TEMP%")
    tmpFile = tempDir & "\gitsync_tmp_" & Int(Rnd() * 99999) & ".txt"

    ' 将 cmd 本身和流重定向包裹在一个通用的大双引号内，避免 Windows 解析特殊路径出错
    oShell.Run "cmd /c " & Chr(34) & cmd & " > """ & tmpFile & """ 2>&1" & Chr(34), 0, True

    output = ""
    If oFSO.FileExists(tmpFile) Then
        On Error Resume Next
        Set oTmp = oFSO.OpenTextFile(tmpFile, 1)
        If Err.Number = 0 Then
            output = oTmp.ReadAll()
            oTmp.Close
        End If
        oFSO.DeleteFile tmpFile
        On Error GoTo 0
    End If
    
    RunCmd = Trim(output)
End Function

' 写日志辅助函数
Sub WriteLog(msg)
    If Not oLog Is Nothing Then
        On Error Resume Next
        oLog.WriteLine "[" & Now() & "] " & msg
        On Error GoTo 0
    End If
End Sub

' 补零格式化
Function Format2(n)
    If n < 10 Then
        Format2 = "0" & n
    Else
        Format2 = CStr(n)
    End If
End Function