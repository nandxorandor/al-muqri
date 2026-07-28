@echo off
setlocal
REM ============================================================
REM  Build AL-MUQRI (المقرئ) as a portable Windows folder.
REM  Run this INSIDE the quran_teacher conda env.
REM
REM  Choose your torch BEFORE building:
REM    CPU edition (runs anywhere):
REM      pip install torch --index-url https://download.pytorch.org/whl/cpu
REM    GPU edition (NVIDIA only): keep the CUDA torch you already have.
REM ============================================================

call conda activate quran_teacher

echo Installing PyInstaller...
pip install --quiet pyinstaller || goto :err

echo.
echo Building... (several minutes; needs several GB of free disk)
pyinstaller al-muqri.spec --noconfirm || goto :err

set DEST=dist\al-muqri
echo.
echo Copying runtime data next to the exe...
copy /Y index.html "%DEST%\" >nul
copy /Y page_layout_full.json "%DEST%\" >nul
if exist page_layout.json copy /Y page_layout.json "%DEST%\" >nul
echo   ...fonts
xcopy /E /I /Y fonts "%DEST%\fonts\" >nul
echo   ...reference_audio (large - be patient)
xcopy /E /I /Y reference_audio "%DEST%\reference_audio\" >nul

echo.
echo ============================================================
echo  DONE.  Portable app folder:  %DEST%\
echo  Launch:  %DEST%\al-muqri.exe
echo  (First launch downloads the model once - needs internet.)
echo ============================================================
pause
goto :eof

:err
echo.
echo BUILD FAILED — see the errors above.
pause
