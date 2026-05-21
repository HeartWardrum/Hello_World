' ============================================================
'  GitAutoSync.vbs
'  功能：自动同步、提交并推送多个 Git 仓库
'  支持：仓库路径含中文、每个仓库独立远程地址
'  系统：Windows 11
' ============================================================

Option Explicit

' ============================================================
'  ★ 配置区域 - 按需修改 ★
' ============================================================

' 仓库列表，格式：本地路径 | 远程仓库URL | 分支名 | 自定义提交前缀（可留空）
' 每行一个仓库，用 vbCrLf 分隔
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

' 日志文件路径（留空则不写日志）
Dim LOG_FILE
LOG_FILE = Environ("USERPROFILE") & "\Desktop\GitAutoSync.log"

' ============================================================
'  主程序
' ============================================================

Dim oShell, oFSO, oLog
Dim i, repoLine, parts
Dim localPath, remoteURL, branch, prefix
Dim commitMsg, result
Dim report, successCount, failCount

Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

' 初始化日志
If LOG_FILE <> "" Then
    Set oLog = oFSO.OpenTextFile(LOG_FILE, 8, True) ' 8=追加
    oLog.WriteLine "==============================="
    oLog.WriteLine "GitAutoSync 启动：" & Now()
    oLog.WriteLine "==============================="
End If

report       = "GitAutoSync 运行报告" & vbCrLf & String(40, "=") & vbCrLf
successCount = 0
failCount    = 0

' 遍历每个仓库
For i = 0 To UBound(REPO_CONFIG)
    repoLine = Trim(REPO_CONFIG(i))
    If repoLine = "" Then GoTo NextRepo

    parts = Split(repoLine, "|")
    If UBound(parts) < 2 Then
        Call WriteLog("配置格式错误，跳过：" & repoLine)
        GoTo NextRepo
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

    ' 检查路径是否存在
    If Not oFSO.FolderExists(localPath) Then
        Call WriteLog("路径不存在，跳过：" & localPath)
        report = report & "  ✗ 路径不存在" & vbCrLf
        failCount = failCount + 1
        GoTo NextRepo
    End If

    ' 检查是否是 git 仓库
    If Not oFSO.FolderExists(localPath & "\.git") Then
        Call WriteLog("不是 Git 仓库，跳过：" & localPath)
        report = report & "  ✗ 非 Git 仓库" & vbCrLf
        failCount = failCount + 1
        GoTo NextRepo
    End If

    ' 切换到仓库目录（用 cmd /c 保证中文路径兼容）
    Dim cdCmd
    cdCmd = "cmd /c chcp 65001 >nul & cd /d """ & localPath & """ & "

    ' 设置远程地址（如果不是"已配置"）
    If remoteURL <> "已配置" And remoteURL <> "" Then
        result = RunCmd(cdCmd & "git remote set-url origin """ & remoteURL & """ 2>&1")
        Call WriteLog("设置远程 [" & localPath & "]：" & result)
    End If

    ' git pull（同步远程）
    result = RunCmd(cdCmd & "git pull origin " & branch & " 2>&1")
    Call WriteLog("git pull [" & localPath & "]：" & result)
    If InStr(result, "error") > 0 Or InStr(result, "fatal") > 0 Then
        report = report & "  ✗ pull 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        GoTo NextRepo
    End If
    report = report & "  ✓ pull 完成" & vbCrLf

    ' git add .
    result = RunCmd(cdCmd & "git add . 2>&1")
    Call WriteLog("git add [" & localPath & "]：" & result)

    ' 生成提交信息
    commitMsg = COMMIT_TEMPLATE
    commitMsg = Replace(commitMsg, "{prefix}", prefix)
    commitMsg = Replace(commitMsg, "{date}", Format2(Year(Now())) & "-" & Format2(Month(Now())) & "-" & Format2(Day(Now())))
    commitMsg = Replace(commitMsg, "{time}", Format2(Hour(Now())) & ":" & Format2(Minute(Now())) & ":" & Format2(Second(Now())))

    ' git commit
    result = RunCmd(cdCmd & "git commit -m """ & commitMsg & """ 2>&1")
    Call WriteLog("git commit [" & localPath & "]：" & result)

    If InStr(result, "nothing to commit") > 0 Or InStr(result, "nothing added") > 0 Then
        report = report & "  ➜ 无变更，跳过提交" & vbCrLf
        ' 即使无变更也算成功
        successCount = successCount + 1
        GoTo NextRepo
    End If

    If InStr(result, "error") > 0 Or InStr(result, "fatal") > 0 Then
        report = report & "  ✗ commit 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        GoTo NextRepo
    End If
    report = report & "  ✓ commit：" & commitMsg & vbCrLf

    ' git push
    result = RunCmd(cdCmd & "git push origin " & branch & " 2>&1")
    Call WriteLog("git push [" & localPath & "]：" & result)

    If InStr(result, "error") > 0 Or InStr(result, "fatal") > 0 Then
        report = report & "  ✗ push 失败：" & Left(result, 120) & vbCrLf
        failCount = failCount + 1
        GoTo NextRepo
    End If
    report = report & "  ✓ push 完成" & vbCrLf
    successCount = successCount + 1

    NextRepo:
Next

' 汇总
report = report & vbCrLf & String(40, "=") & vbCrLf
report = report & "完成：" & successCount & " 个成功，" & failCount & " 个失败" & vbCrLf
report = report & "时间：" & Now()

Call WriteLog(report)

If LOG_FILE <> "" And Not IsNull(oLog) Then
    oLog.Close
End If

If SHOW_REPORT Then
    MsgBox report, vbInformation, "GitAutoSync 完成"
End If

' ============================================================
'  工具函数
' ============================================================

' 执行命令并返回输出（使用临时文件捕获输出，兼容中文路径）
Function RunCmd(cmd)
    Dim tmpFile, oExec, output
    tmpFile = Environ("TEMP") & "\gitsync_tmp_" & Int(Rnd() * 99999) & ".txt"

    ' 通过重定向捕获输出
    oShell.Run "cmd /c " & Chr(34) & cmd & " > """ & tmpFile & """ " & Chr(34), 0, True

    On Error Resume Next
    If oFSO.FileExists(tmpFile) Then
        Dim oTmp
        Set oTmp = oFSO.OpenTextFile(tmpFile, 1)
        output = oTmp.ReadAll()
        oTmp.Close
        oFSO.DeleteFile tmpFile
    End If
    On Error GoTo 0

    RunCmd = Trim(output)
End Function

' 写日志
Sub WriteLog(msg)
    If LOG_FILE <> "" And Not IsNull(oLog) Then
        oLog.WriteLine "[" & Now() & "] " & msg
    End If
End Sub

' 补零格式化（个位数补0）
Function Format2(n)
    If n < 10 Then
        Format2 = "0" & n
    Else
        Format2 = CStr(n)
    End If
End Function
