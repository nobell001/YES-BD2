@echo off
rem Launch YES-BD2 (bd2-auto) from source with the project virtualenv.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
rem Players unzip GitHub's "Source code" and run this (Bilibili, 2026-10-09);
rem without .venv the window closed with no hint.  chcp runs before the
rem Chinese lines are read, so they show right on any Windows.
chcp 65001 >nul
echo.
echo   这是 YES-BD2 的源码，不是给玩家用的安装包。
echo   玩家请到下面的网址下载 yes-bd2-win32-online-setup.exe，安装后打开 YES-BD2：
echo   https://github.com/nobell001/YES-BD2/releases/latest
echo.
echo   开发者请先照 README「从源码运行」建立 .venv。
echo.
start "" "https://github.com/nobell001/YES-BD2/releases/latest"
pause
exit /b 1

:run
".venv\Scripts\python.exe" main.py
