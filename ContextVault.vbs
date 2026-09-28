
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = strScriptDir

strPythonW = strScriptDir & "\.venv\Scripts\pythonw.exe"

If Not objFSO.FileExists(strPythonW) Then
    strPythonW = "pythonw.exe"
End If

strCommand = """" & strPythonW & """ """ & strScriptDir & "\run.py"" desktop"
objShell.Run strCommand, 0, False
