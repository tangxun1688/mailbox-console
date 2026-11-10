' Launch mailbox-gui with no console window.
' Double-click this file, or make a desktop shortcut to it.

Option Explicit

Dim fso, sh, dir, pyw, target, cmd

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
target = dir & "\app.py"

If Not fso.FileExists(target) Then
    MsgBox "app.py not found next to this script.", 16, "mailbox-gui"
    WScript.Quit 1
End If

sh.CurrentDirectory = dir

pyw = "C:\Users\Ryan\AppData\Local\Python\bin\pythonw.exe"
If Not fso.FileExists(pyw) Then
    pyw = "pythonw.exe"
End If

cmd = """" & pyw & """ """ & target & """"
sh.Run cmd, 0, False
