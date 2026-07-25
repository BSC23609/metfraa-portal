@echo off
REM ============================================================
REM  Metfraa Portal - Push helper (Vercel auto-deploys on push)
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Metfraa Portal - Git Push
echo ============================================================
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not a git repository.
    pause
    exit /b 1
)

echo [1/3] Python syntax checks...
py -3 -m py_compile api\index.py                       || goto :err
py -3 -m py_compile app\main.py                        || goto :err
py -3 -m py_compile app\models.py                      || goto :err
py -3 -m py_compile app\database.py                    || goto :err
py -3 -m py_compile app\access.py                      || goto :err
py -3 -m py_compile app\routes\cron.py                 || goto :err
py -3 -m py_compile app\routes\ehs.py                  || goto :err
py -3 -m py_compile app\routes\expense.py              || goto :err
py -3 -m py_compile app\routes\people.py               || goto :err
py -3 -m py_compile app\ehs\forms.py                   || goto :err
py -3 -m py_compile app\expense\policy.py              || goto :err
py -3 -m py_compile app\expense\validators.py          || goto :err
py -3 -m py_compile app\services\ehs_pdf.py            || goto :err
py -3 -m py_compile app\services\ehs_excel_log.py      || goto :err
py -3 -m py_compile app\services\expense_artifacts.py  || goto :err
py -3 -m py_compile app\services\portal_notify.py      || goto :err
py -3 -m py_compile app\services\onedrive.py           || goto :err
py -3 -m py_compile scripts\migrate_phase3.py          || goto :err
echo    OK - all Python files pass
echo.

echo [2/3] Git status
git status --short
echo.

set "UNTRACKED="
for /f %%i in ('git ls-files --others --exclude-standard') do set UNTRACKED=1
git diff --quiet
set WORKING_DIFF=%errorlevel%
git diff --cached --quiet
set CACHED_DIFF=%errorlevel%
if "%CACHED_DIFF%"=="0" if "%WORKING_DIFF%"=="0" if not defined UNTRACKED (
    echo No changes to commit. Working tree is clean.
    pause
    exit /b 0
)

echo [3/3] Commit + push
set /p MSG="Commit message (Enter = timestamped): "
if "!MSG!"=="" set MSG=portal update %date% %time%

git add -A                 || ( echo ERROR: git add failed. & pause & exit /b 1 )
git commit -m "!MSG!"      || ( echo ERROR: git commit failed. & pause & exit /b 1 )
git push                   || ( echo ERROR: git push failed - check connection/credentials. & pause & exit /b 1 )

echo.
echo ============================================================
echo  SUCCESS - Pushed. Vercel deploys in ~1-2 min.
echo  Verify: https://app.metfraa.com/health
echo ============================================================
pause
goto :end

:err
echo.
echo ============================================================
echo  SYNTAX ERROR in a Python file - fix before pushing
echo ============================================================
pause

:end
endlocal
