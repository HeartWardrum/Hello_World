#IfWinActive ahk_exe Typora.exe
{
^k::
Send, ~~~java
Send, {Enter}
Send, {Enter}
Send, {Enter}
Send, ~~~
Send, {Up}
Return
}