@echo off
REM Run this yourself, in a normal window, so you can see the browser flow.
REM It writes .yt-refresh-token and prints only the length, never the token.
cd /d "%~dp0"
py mint_token.py
echo.
echo Done. Leave this window open and tell Claude.
pause
