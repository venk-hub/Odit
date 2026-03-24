@echo off
echo.
echo ==========================================
echo    Odit - Tracking Auditor
echo ==========================================
echo.

where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker is not installed or not in PATH.
    echo Please install Docker Desktop: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker daemon is not running. Please start Docker Desktop.
    pause
    exit /b 1
)

echo Creating data directories...
if not exist "data\audits" mkdir "data\audits"
if not exist "data\proxy_flows" mkdir "data\proxy_flows"
if not exist "data\certs" mkdir "data\certs"

if not exist ".env" (
    echo Creating .env from .env.example...
    copy .env.example .env
)

echo Building and starting Odit containers...
docker compose up -d --build

echo.
echo Waiting for services to be ready...
timeout /t 15 /nobreak >nul

:WAIT_LOOP
curl -sf http://localhost:8000/health >nul 2>&1
if %ERRORLEVEL% EQU 0 goto READY
echo Waiting for app...
timeout /t 5 /nobreak >nul
goto WAIT_LOOP

:READY
echo.
echo ==========================================
echo  Odit is running at: http://localhost:8000
echo ==========================================
echo.
echo To view logs:  docker compose logs -f
echo To stop:       docker compose down
echo.
pause
