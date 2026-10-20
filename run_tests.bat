@echo off
chcp 65001 >nul
setlocal
set "PYTHONPATH=%~dp0.venv\Lib\site-packages"
set "HF_ENDPOINT=https://hf-mirror.com"
set "PYTHONUTF8=1"
cd /d "%~dp0"

if /i "%~1"=="smoke"  goto smoke
if /i "%~1"=="all"    goto all
if /i "%~1"=="stability" goto stability
if /i "%~1"=="report" goto report

echo 用法: run_tests.bat [smoke^|all^|stability^|report]
echo.
echo   smoke      只跑冒烟子集，用 MockEmbedding，不需要 API Key
echo   all        跑除慢用例外的全部用例（需要 DeepSeek Key）
echo   stability  连续 10 次稳定性测试
echo   report     用已生成的结果打开 allure 报告
exit /b 1

:smoke
set "USE_MOCK_EMBED=1"
".venv\Scripts\python.exe" -m pytest -m "smoke and not llm"
goto end

:all
".venv\Scripts\python.exe" -m pytest -m "not slow"
goto end

:stability
".venv\Scripts\python.exe" -m pytest -m "slow"
goto end

:report
".venv\Scripts\python.exe" -m allure serve reports\allure-results
goto end

:end
endlocal
