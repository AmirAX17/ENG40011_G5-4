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
set "FAILED=0"
echo Downloading phi4-mini...
ollama pull phi4-mini
if errorlevel 1 set "FAILED=1"
echo Downloading qwen3.5:4b...
ollama pull qwen3.5:4b
if errorlevel 1 set "FAILED=1"
echo Downloading qwen3.5:2b...
ollama pull qwen3.5:2b
if errorlevel 1 set "FAILED=1"
echo Downloading gemma3:4b...
ollama pull gemma3:4b
if errorlevel 1 set "FAILED=1"
ollama list
if "%FAILED%"=="1" (
 echo Some downloads failed. Run this again to retry, or use individual installers.
 pause
 exit /b 1
)
echo All four models installed. Launch START_LOCAL.bat in the main folder.
pause
