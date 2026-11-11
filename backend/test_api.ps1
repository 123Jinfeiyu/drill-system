# 演练系统 API 测试脚本
# 前置：先启动后端  ->  py -m uvicorn app.main:app --reload
# 用法：在 backend 目录下执行  ->  . .\test_api.ps1

$ErrorActionPreference = "Continue"
$BASE = "http://localhost:8000"

Write-Host "=== 1. 学员登录 ===" -ForegroundColor Cyan
$resp = Invoke-RestMethod -Uri "$BASE/api/auth/login" -Method Post -ContentType "application/json" -Body (@{username="student01"; password="Test@2025"} | ConvertTo-Json)
$TOKEN = $resp.access_token
Write-Host "Token: $($TOKEN.Substring(0, 30))..."
$H = @{Authorization = "Bearer $TOKEN"}

Write-Host "`n=== 2. 列出剧本 ===" -ForegroundColor Cyan
$sc = Invoke-RestMethod -Uri "$BASE/api/scenarios" -Method Get -Headers $H
$sc | Format-List code, title, difficulty, max_turns

Write-Host "`n=== 3. 创建演练会话 ===" -ForegroundColor Cyan
$resp = Invoke-RestMethod -Uri "$BASE/api/sessions" -Method Post -ContentType "application/json" -Headers $H -Body (@{scenario_id=$sc[0].id} | ConvertTo-Json)
$SESSION_ID = $resp.id
Write-Host "SessionID: $SESSION_ID"

Write-Host "`n=== 4. 启动演练（拿客户开场白）===" -ForegroundColor Cyan
$resp = Invoke-RestMethod -Uri "$BASE/api/sessions/$SESSION_ID/start" -Method Post -Headers $H
Write-Host "客户开场白: $($resp.content)" -ForegroundColor Yellow

Write-Host "`n=== 5. 学员回复 1 ===" -ForegroundColor Cyan
$reply = @{content="工单号是 TK20250901001，刚提交 5 分钟，故障对象是订单服务"} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$BASE/api/sessions/$SESSION_ID/reply" -Method Post -ContentType "application/json" -Headers $H -Body $reply
Write-Host "AI 客户: $($resp.content)" -ForegroundColor Yellow

Write-Host "`n=== 6. 学员回复 2 ===" -ForegroundColor Cyan
$reply = @{content="已查到，确实有一笔相同主题工单，建议关闭后续保留最早的，请确认"} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$BASE/api/sessions/$SESSION_ID/reply" -Method Post -ContentType "application/json" -Headers $H -Body $reply
Write-Host "AI 客户: $($resp.content)" -ForegroundColor Yellow

Write-Host "`n=== 7. 结束并评分 ===" -ForegroundColor Cyan
$resp = Invoke-RestMethod -Uri "$BASE/api/sessions/$SESSION_ID/score" -Method Post -Headers $H
$resp | Format-List total, accuracy, completeness, etiquette, responsiveness, knowledge_use, summary, weak_points

Write-Host "`n=== 8. 查看对话回放 ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$BASE/api/sessions/$SESSION_ID/messages" -Method Get -Headers $H | Format-Table role, turn, content -Wrap
