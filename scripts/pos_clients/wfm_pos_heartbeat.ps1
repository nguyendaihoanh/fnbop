# ==============================================================================
# WFM / F&B POS IP HEARTBEAT & CHANGE DETECTION (3-LAYER ENGINE)
# ==============================================================================
param(
    [switch]$Force,
    [string]$Secret = $(if ($env:WFM_POS_SECRET) { $env:WFM_POS_SECRET } elseif ($env:FNBOP_POS_SECRET) { $env:FNBOP_POS_SECRET } else { $env:POS_SECRET })
)

$AppDir = if (Test-Path "C:\FNBOPS_POS") { "C:\FNBOPS_POS" } else { "C:\WFM_POS" }
$LogFile = "$AppDir\pos_heartbeat.log"
$CacheFile = "$AppDir\current_ip.txt"
$Endpoint = if ($env:FNBOPS_ENDPOINT) { $env:FNBOPS_ENDPOINT } else { "http://localhost:8100/api/v1/attendance/pos/heartbeat" }

# Secure Secret Retrieval:
# 1. Parameter -Secret
# 2. Environment variable $env:WFM_POS_SECRET or $env:FNBOP_POS_SECRET
# 3. Local secret file: $AppDir\secret.txt
if ([string]::IsNullOrEmpty($Secret)) {
    $secretFile = "$AppDir\secret.txt"
    if (Test-Path $secretFile) {
        $Secret = (Get-Content $secretFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($Secret) { $Secret = $Secret.Trim() }
    }
}

if ([string]::IsNullOrEmpty($Secret)) {
    Write-Error "POS Heartbeat: Missing secret. Set WFM_POS_SECRET env, pass -Secret, or create $AppDir\secret.txt"
    exit 1
}

# 1. Lay IP WAN hien tai (sieu nhanh, timeout 3s, fallback AWS)
$currentIp = $null
try {
    $currentIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 3 -ErrorAction Stop).Trim()
} catch {
    try {
        $currentIp = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com" -TimeoutSec 3 -ErrorAction Stop).Trim()
    } catch {
        $currentIp = $null
    }
}

# 2. Doc IP da luu trong cache local
$lastIp = ""
$cacheAgeMinutes = 999
if (Test-Path $CacheFile) {
    $lastIp = (Get-Content $CacheFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($lastIp) { $lastIp = $lastIp.Trim() }
    $cacheAgeMinutes = ((Get-Date) - (Get-Item $CacheFile).LastWriteTime).TotalMinutes
}

# 3. Kiem tra khung gio vang truoc 2 ca truc (05:45-05:55 hoac 16:10-16:20)
$now = Get-Date
$isShiftCheck = ($now.Hour -eq 5 -and $now.Minute -ge 45 -and $now.Minute -le 55) -or ($now.Hour -eq 16 -and $now.Minute -ge 10 -and $now.Minute -le 20)

# 4. Danh gia dieu kien dong bo (3 LOP CHAY NGAM)
# - Lop 1: Khoi dong may / Dang nhap (Chua co cache hoac Force)
# - Lop 2: Phat hien IP bien dong (Change Detection: $currentIp != $lastIp)
# - Lop 3: Chot chan truoc ca (isShiftCheck) HOAC nhip tim dinh ky (cache >= 20 phut)
$needSync = $false
$reason = ""

if ($Force) {
    $needSync = $true
    $reason = "Forced Trigger"
} elseif ([string]::IsNullOrEmpty($lastIp)) {
    $needSync = $true
    $reason = "Initial Startup"
} elseif ($null -ne $currentIp -and $currentIp -ne $lastIp) {
    $needSync = $true
    $reason = "IP Changed ($lastIp -> $currentIp)"
} elseif ($isShiftCheck) {
    $needSync = $true
    $reason = "Pre-Shift Safety Check"
} elseif ($cacheAgeMinutes -ge 20) {
    $needSync = $true
    $reason = "Periodic Liveness Heartbeat ($([int]$cacheAgeMinutes)m)"
}

# 5. Neu khong co thay doi va nhip tim chua toi 20 phut -> Thoat ngay lap tuc sau 1 giay
if (-not $needSync) {
    exit 0
}

# 6. Gui ban tin cap nhat len Production Server
$Headers = @{
    "X-POS-Secret" = $Secret
    "User-Agent"   = "FnBOps-POS-Heartbeat/1.0"
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
try {
    $body = @{}
    if ($currentIp) { $body["override_ip"] = $currentIp }
    $jsonBody = $body | ConvertTo-Json

    $response = Invoke-RestMethod -Uri $Endpoint -Method POST -Headers $Headers -Body $jsonBody -ContentType "application/json" -TimeoutSec 10 -ErrorAction Stop
    $serverIp = $response.cafe_ip
    
    $finalIp = if ($serverIp) { $serverIp } else { $currentIp }
    if ($finalIp) {
        Set-Content -Path $CacheFile -Value $finalIp -Encoding UTF8
    }

    $logMsg = "[$timestamp] Heartbeat OK - Cafe IP: $finalIp ($reason)"
    Add-Content -Path $LogFile -Value $logMsg -Encoding UTF8
} catch {
    Add-Content -Path $LogFile -Value "[$timestamp] Heartbeat FAILED ($reason): $($_.Exception.Message)" -Encoding UTF8
}

# 7. Tu dong don dep log: Duy tri toi da 200 dong
if (Test-Path $LogFile) {
    $lines = Get-Content $LogFile
    if ($lines.Count -gt 200) {
        $lines[-100..-1] | Set-Content $LogFile -Encoding UTF8
    }
}
