@echo off
TITLE qwen2API Enterprise Gateway
cd /d "%~dp0"

:: Faxina inicial: Garante que não existam processos órfãos travando a porta ou memória
echo [CLEANUP] Realizando limpeza de processos antigos...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM chrome.exe /T >nul 2>&1
taskkill /F /IM node.exe /T >nul 2>&1
timeout /t 1 >nul

echo ==================================================
echo   Iniciando qwen2API Enterprise Gateway (Guardian)
echo ==================================================

:: Verifica se o ambiente virtual existe
:start
echo [INFO] Iniciando qwen2API Enterprise Gateway em %date% %time%
echo ==================================================
"venv\Scripts\python.exe" start.py
echo ==================================================
echo [WARNING] O servidor fechou inesperadamente ou foi encerrado. 
echo [INFO] Reiniciando automaticamente em 5 segundos (Ctrl+C para parar)...
timeout /t 5
goto start
