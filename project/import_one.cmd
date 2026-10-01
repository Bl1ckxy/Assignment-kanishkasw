@echo off
rem Import one SQL file into the `cafe` database.
rem Usage: import_one.cmd "C:\path\file.sql" label
rem Password comes from env MYSQL_PWD (never stored in files).
setlocal
set FILE=%~1
set LABEL=%~2
set LOGDIR=H:\kanishka\project\logs

"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -uroot cafe --default-character-set=utf8mb4 --max_allowed_packet=1G --init-command="SET time_zone='+00:00', foreign_key_checks=0, unique_checks=0, sql_log_bin=0, sql_mode='NO_AUTO_VALUE_ON_ZERO'" < "%FILE%" > "%LOGDIR%\import_%LABEL%.log" 2>&1
set RC=%errorlevel%
echo %DATE% %TIME% %LABEL% exit=%RC% >> "%LOGDIR%\import_status.log"
exit /b %RC%
