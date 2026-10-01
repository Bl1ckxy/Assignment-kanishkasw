@echo off
net start MySQL80 > H:\kanishka\project\logs\service_start.log 2>&1
echo exit=%errorlevel% >> H:\kanishka\project\logs\service_start.log
exit /b %errorlevel%
