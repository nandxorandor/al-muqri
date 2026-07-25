@echo off
REM ============================================================
REM  AL-MUQRI (المقرئ) - share on the home network (HTTPS on)
REM  Double-click this file to launch in "share with family" mode.
REM
REM  UI port    : 7070  (share link -> https://<this-laptop-IP>:7070)
REM  Engine port: 8000  (internal, on this laptop only)
REM  NOTE: avoid "unsafe" ports browsers block (e.g. 6000, 6666). 7070 is fine.
REM  Firewall   : allow inbound TCP 7070, e.g. (Admin):
REM    netsh advfirewall firewall add rule name="Al-Muqri 7070" ^
REM      dir=in action=allow protocol=TCP localport=7070
REM ============================================================
call conda activate quran_teacher
set HTTPS=1
cd /d "%~dp0"
python run.py
pause
