@echo off
REM Doble click a este archivo para correr el radar manualmente.
REM Si Python no está en el PATH, reemplazá "python" por la ruta completa,
REM por ejemplo: C:\Users\TuUsuario\AppData\Local\Programs\Python\Python312\python.exe

cd /d "%~dp0"
python main.py
echo.
echo ============================================
echo  Radar finalizado. Presiona una tecla para cerrar.
echo ============================================
pause
