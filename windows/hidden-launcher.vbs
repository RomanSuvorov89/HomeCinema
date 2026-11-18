Option Explicit
Dim fso, shell, root, mode, script, command, result
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
If WScript.Arguments.Count < 1 Then WScript.Quit 2
mode = WScript.Arguments(0)
Select Case mode
  Case "worker"
    If WScript.Arguments.Count <> 2 Then WScript.Quit 2
    script = "wsl-keepalive.ps1"
  Case "panel"
    result = shell.Run(Quote(fso.BuildPath(root, "server-panel.exe")), 1, False)
    WScript.Quit result
  Case Else
    WScript.Quit 2
End Select
command = Quote(shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe")
command = command & " -NoProfile -NonInteractive -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Quote(fso.BuildPath(root, script))
If mode = "worker" Then command = command & " -Distribution " & Quote(WScript.Arguments(1))
' GUI subsystem host plus hidden child: there is no console window to close.
' Wait so Task Scheduler tracks the keepalive lifetime and recovery exit code.
result = shell.Run(command, 0, True)
WScript.Quit result
Function Quote(value)
  Quote = Chr(34) & Replace(value, Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
