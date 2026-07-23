@echo off
REM ============================================================
REM  Metfraa Portal - Push helper (Vercel auto-deploys on push)
REM  Runs Python syntax checks, then stages, commits and pushes.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Metfraa Portal - Git Push
echo ============================================================
echo.

REM Confirm we're in a git repo
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not a git repository.
    echo Run these once first:
    echo    git init
    echo    git remote add origin https://github.com/YOUR-USER/metfraa-portal.git
    echo.
    pause
    exit /b 1
)

REM ---- Syntax checks (all module entry points) ----
echo [1/3] Python syntax checks...
py -3 -m py_compile app\main.py                        || goto :err
py -3 -m py_compile app\models.py                      || goto :err
py -3 -m py_compile app\database.py                    || goto :err
py -3 -m py_compile app\routes\cron.py                 || goto :err
py -3 -m py_compile app\routes\ehs.py                  || goto :err
py -3 -m py_compile app\routes\expense.py              || goto :err
py -3 -m py_compile app\ehs\forms.py                   || goto :err
py -3 -m py_compile app\expense\policy.py              || goto :err
py -3 -m py_compile app\expense\validators.py          || goto :err
py -3 -m py_compile app\services\ehs_pdf.py            || goto :err
py -3 -m py_compile app\services\ehs_excel_log.py      || goto :err
py -3 -m py_compile app\services\expense_artifacts.py  || goto :err
py -3 -m py_compile app\services\onedrive.py           || goto :err
py -3 -m py_compile index.py                           || goto :err
py -3 -m py_compile app\\access.py                     || goto :err
py -3 -m py_compile app\\routes\\people.py              || goto :err
echo    OK - all Python files pass
echo.

REM ---- Show pending changes ----
echo [2/3] Git status
git status --short
echo.

REM Check if there's anything to commit
set "UNTRACKED="
for /f %%i in ('git ls-files --others --exclude-standard') do set UNTRACKED=1
git diff --quiet
set WORKING_DIFF=%errorlevel%
git diff --cached --quiet
set CACHED_DIFF=%errorlevel%
if "%CACHED_DIFF%"=="0" if "%WORKING_DIFF%"=="0" if not defined UNTRACKED (
    echo No changes to commit. Working tree is clean.
    echo.
    pause
    exit /b 0
)

REM ---- Commit + push ----
echo [3/3] Commit + push
set /p MSG="Commit message (Enter = timestamped): "
if "!MSG!"=="" set MSG=portal update %date% %time%

git add -A
if errorlevel 1 ( echo ERROR: git add failed. & pause & exit /b 1 )

git commit -m "!MSG!"
if errorlevel 1 ( echo ERROR: git commit failed. & pause & exit /b 1 )

git push
if errorlevel 1 (
    echo.
    echo ERROR: git push failed.
    echo Check your internet connection and GitHub credentials.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  SUCCESS - Pushed to GitHub
echo  Vercel will auto-deploy in ~1-2 minutes.
echo  Verify at: https://app.metfraa.com/health
echo  (New DB tables in this release? Set INIT_DB=true on
echo   Vercel, redeploy, open /health, then remove the var.)
echo ============================================================
echo.
pause
goto :end

:err
echo.
echo ============================================================
echo  SYNTAX ERROR - fix before pushing
echo ============================================================
pause

:end
endlocal
