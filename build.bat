@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === mailbox-gui 打包 ===
python build.py %*
if errorlevel 1 (
  echo.
  echo [失败] 打包出错，看上面的日志。
  pause
  exit /b 1
)
echo.
echo [完成] 产物在 dist\ 目录。
pause
