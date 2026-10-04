@echo off
echo ====================================================
echo Instalando dependencias de build...
echo ====================================================
python -m pip install pyinstaller

echo.
echo ====================================================
echo Gerando Executavel (.exe) com PyInstaller...
echo ====================================================
python -m PyInstaller --noconsole --onefile --collect-all playwright --add-data "assets;assets" --icon "assets\appLogo.ico" --hidden-import i_rpa_tarefa --hidden-import i_rpa_repositorio --hidden-import rpa_repositorio_sqlite --name "asclabs_AutomatizadorRelatorios" app.py

echo.
echo ====================================================
echo Concluido! Executavel gerado na pasta dist\asclabs_AutomatizadorRelatorios.exe
echo ====================================================
pause
