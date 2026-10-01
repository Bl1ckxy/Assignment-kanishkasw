@echo off
REM Kanishka challenge — run the analysis pipeline end to end.
REM Prereqs: MySQL service MySQL80 running; MYSQL_PWD set (setx MYSQL_PWD <pw>).
REM Import must already be done (see README.md); this runs stages 1-6.
setlocal
if "%MYSQL_PWD%"=="" (
  echo MYSQL_PWD is not set. Run: setx MYSQL_PWD ^<password^> then open a new shell.
  exit /b 1
)
set PY=H:\kanishka\project\venv\Scripts\python.exe
set SRC=H:\kanishka\project\src
set LOGS=H:\kanishka\project\logs

echo [1/6] explore...
%PY% %SRC%\01_explore.py > %LOGS%\01_explore.log 2>&1 || goto :fail
echo [2/6] clean...
%PY% %SRC%\02_clean.py > %LOGS%\02_clean.log 2>&1 || goto :fail
echo [3/6] EDA...
%PY% %SRC%\03_eda.py > %LOGS%\03_eda.log 2>&1 || goto :fail
echo [4/6] forecast...
%PY% %SRC%\04_forecast.py > %LOGS%\04_forecast.log 2>&1 || goto :fail
echo [5/6] holdout check...
%PY% %SRC%\05_holdout_check.py > %LOGS%\05_holdout.log 2>&1 || goto :fail
echo [6/6] timezone chart...
%PY% %SRC%\06_tz_chart.py > %LOGS%\06_tz_chart.log 2>&1 || goto :fail
echo all stages OK. See REPORT.md and outputs\
exit /b 0

:fail
echo stage failed - check %LOGS% and the last log above.
exit /b 1
