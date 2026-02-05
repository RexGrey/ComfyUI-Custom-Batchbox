@echo off
chcp 65001 >nul
cls
echo ========================================================
echo           Batchbox 代码上传助手 (Upload Helper)
echo ========================================================
echo.
echo [1/4] 正在保存修改... (Saving changes)
git add .
git commit -m "Update: Separate providers config to secrets.yaml"
echo.

echo [2/4] 设置远程仓库 (Setting up remote)
echo 这里的“账号不一样”意味着你需要把代码上传到属于你新账号的仓库。
echo 请先登录你的新 GitHub 账号，创建一个新的【空仓库】(Empty Repository)。
echo.
set /p REPO_URL="请粘贴新的仓库 HTTPS 链接 (例如 https://github.com/你的名字/项目名.git): "
echo.

if "%REPO_URL%"=="" goto error

echo [3/4] 切换链接至新仓库...
git remote remove origin
git remote add origin %REPO_URL%
git branch -M main

echo.
echo [4/4] 开始上传... (可能会弹出登录窗口，请登录新账号)
git push -u origin main

if errorlevel 1 (
    echo.
    echo [!] 普通上传受阻，尝试强制上传...
    git push -u origin main --force
)

echo.
echo ========================================================
echo                   全部完成 (All Done)
echo ========================================================
echo 现在你可以去 GitHub 刷新页面，查看代码是否已上传。
echo 注意检查：secrets.yaml 应该不会被上传。
pause
exit

:error
echo [!] 错误：未输入链接。脚本已退出。
pause
