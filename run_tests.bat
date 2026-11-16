@echo off
REM Quotelytics Automated Test Suite Runner
REM Executes all 53 verification tests across the codebase
echo ======================================================================
echo QUOTELYTICS INC. - AUTOMATED TEST SUITE RUNNER
echo ======================================================================
python run_tests.py %*
pause
