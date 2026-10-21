@echo off
setlocal
where ollama >nul 2>&1
if errorlevel 1 (
 echo Ollama was not found. Install it from https://ollama.com/download/windows
 echo Then reopen this installer. If already installed, restart Windows or your terminal.
 pause
 exit /b 1
)
ollama list >nul 2>&1
if errorlevel 1 (
 echo Open the Ollama application first, or run ollama serve in a separate terminal.
 pause
 exit /b 1
)
ollama pull qwen3.5:4b
if errorlevel 1 (
 echo Download failed. Check internet and disk space, then run this installer again.
 pause
 exit /b 1
)
echo Installed qwen3.5:4b.
pause
