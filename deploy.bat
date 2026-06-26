@echo off
REM Deploy all Live Poll App stacks in order
REM Run from the adasheffield project root

echo ========================================
echo  Live Poll App - Full Deployment
echo ========================================
echo.

echo [1/6] Deploying SharedStack (DynamoDB tables)...
call cdk deploy SharedStack --require-approval never
if %ERRORLEVEL% neq 0 (echo FAILED: SharedStack && exit /b 1)
echo.

echo [2/6] Deploying LambdaStack (Lambda + API Gateway)...
call cdk deploy LambdaStack --require-approval never
if %ERRORLEVEL% neq 0 (echo FAILED: LambdaStack && exit /b 1)
echo.

echo [3/6] Deploying EC2Stack (EC2 + ALB)...
call cdk deploy EC2Stack --require-approval never
if %ERRORLEVEL% neq 0 (echo FAILED: EC2Stack && exit /b 1)
echo.

echo [4/6] Deploying ECSStack (Fargate + ALB)...
call cdk deploy ECSStack --require-approval never
if %ERRORLEVEL% neq 0 (echo FAILED: ECSStack && exit /b 1)
echo.

echo [5/6] Seeding DynamoDB with poll data...
call .venv\Scripts\python.exe seed_db.py
if %ERRORLEVEL% neq 0 (echo FAILED: Seed script && exit /b 1)
echo.

echo [6/6] Deploying FrontendStack (S3 + CloudFront)...
call cdk deploy FrontendStack --require-approval never
if %ERRORLEVEL% neq 0 (echo FAILED: FrontendStack && exit /b 1)
echo.

echo ========================================
echo  All stacks deployed successfully!
echo ========================================
echo.
echo Run the following to see all outputs:
echo   aws cloudformation describe-stacks --region eu-west-2 --query "Stacks[*].[StackName,Outputs]" --output table
