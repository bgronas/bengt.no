@echo off
rem Forwards to publish.sh through Git Bash, so the same commands work from cmd.exe and PowerShell.
rem Example:  publish new my-post-slug en
setlocal
set "BASH_EXE="
for /f "delims=" %%G in ('where git 2^>nul') do if not defined BASH_EXE if exist "%%~dpG..\bin\bash.exe" set "BASH_EXE=%%~dpG..\bin\bash.exe"
if not defined BASH_EXE if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH_EXE=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH_EXE if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "BASH_EXE=%LocalAppData%\Programs\Git\bin\bash.exe"
if not defined BASH_EXE (
  echo Git Bash was not found. Install Git for Windows from https://git-scm.com/download/win
  exit /b 9
)
pushd "%~dp0"
"%BASH_EXE%" ./publish.sh %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
