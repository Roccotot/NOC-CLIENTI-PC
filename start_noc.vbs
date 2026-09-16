' Avvia il sito senza nemmeno la finestra del prompt, lasciando l'icona
' vicino all'orologio: da li' si apre il sito e si ferma.
' Ricava la cartella da questo file invece di usare un percorso fisso.
Set fso = CreateObject("Scripting.FileSystemObject")
cartella = fso.GetParentFolderName(WScript.ScriptFullName)

pyw = "C:\Users\Sigrafilm\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw"

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = cartella
shell.Run """" & pyw & """ tray.py", 0, False
