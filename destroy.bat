@echo off
REM Destroy all Live Poll App stacks in reverse order
REM Run from the adasheffield project root

echo ========================================
echo  Live Poll App - Full Teardown
echo ========================================
echo.

echo [1/6] Destroying FrontendStack...
call cdk destroy FrontendStack --force
if %ERRORLEVEL% neq 0 (echo WARNING: FrontendStack destroy had issues)
echo.

echo [2/6] Destroying ECSStack...
call cdk destroy ECSStack --force
if %ERRORLEVEL% neq 0 (echo WARNING: ECSStack destroy had issues)
echo.

echo [3/6] Destroying EC2Stack...
call cdk destroy EC2Stack --force
if %ERRORLEVEL% neq 0 (echo WARNING: EC2Stack destroy had issues)
echo.

echo [4/6] Destroying LambdaStack...
call cdk destroy LambdaStack --force
if %ERRORLEVEL% neq 0 (echo WARNING: LambdaStack destroy had issues)
echo.

echo [5/6] Destroying SharedStack...
call cdk destroy SharedStack --force
if %ERRORLEVEL% neq 0 (echo WARNING: SharedStack destroy had issues)
echo.

echo [6/6] Cleaning up SSM parameters...
aws ssm delete-parameter --name /live-poll/lambda-url --region eu-west-2 2>nul
aws ssm delete-parameter --name /live-poll/lambda-ws-url --region eu-west-2 2>nul
aws ssm delete-parameter --name /live-poll/ecs-url --region eu-west-2 2>nul
aws ssm delete-parameter --name /live-poll/ec2-url --region eu-west-2 2>nul
echo.

echo ========================================
echo  All stacks destroyed.
echo ========================================
