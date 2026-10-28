# Cycle bench template (Windows Task Scheduler example)
# Pattern: disable supervisor -> per-config server cycles with gates -> restore.
# On Linux/systemd: stop the service, run cycles, restart.
# CAVEATS (read before running on your box):
#  - KillServer stops EVERY llama-server process on the host — stop unrelated
#    inference first; this is not selective.
#  - Edit the $rt/$model/$draft/$scratch/$log/$task paths below; the shipped
#    values are placeholders.
#  - Restoration re-enables $task at the end; if the script is killed mid-run,
#    re-enable the supervisor manually (schtasks /Change /TN $task /Enable).
#  - A probe failure does not abort the round — check for NEVER_READY /
#    NO VALID REPS lines in the log before trusting any cycle's numbers.
$ErrorActionPreference = "Continue"

$rt      = "C:\path\to\llama.cpp\build\bin"                 # llama-server dir
$model   = "C:\models\Ornith-1.5-35B-A3B-APEX-MTP-I-Compact.gguf"
$draft   = "C:\models\mtp-Ornith-1.5-35B-A3B-Q8_0.gguf"
$alias   = "ornith-35b-a3b"                                  # must match probe aliases
$scratch = "C:\bench\scratch"
$log     = "C:\bench\results.log"
$task    = "TurbofitRuntime"                                 # supervisor service/task

$baseArgs = @("--model",$model,"--host","127.0.0.1","--port","8092","--alias",$alias,
              "--ctx-size","65536","--parallel","1","--n-gpu-layers","99","--n-cpu-moe","30",
              "--fit","on","--flash-attn","on","--jinja","--metrics","--load-mode","mlock",
              "--model-draft",$draft,"-ngld","99","--spec-type","draft-mtp","--spec-draft-n-max","1")

schtasks /Change /TN $task /Disable 2>&1 | Out-Null

function KillServer {
  Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
  $tries = 0
  while ((Get-Process llama-server -ErrorAction SilentlyContinue) -and ($tries -lt 15)) {
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2; $tries++
  }
}

function FreeRAM {
  $os = Get-CimInstance Win32_OperatingSystem
  "{0:N1}" -f ($os.FreePhysicalMemory/1MB)
}

function Cycle($label, $extra) {
  "=== $label  $(Get-Date -Format HH:mm:ss)  freeRAM_GB=$(FreeRAM) ===" | Out-File $log -Append -Encoding utf8
  KillServer
  $srvArgs = $baseArgs + $extra
  $srvErr = "$scratch\srv_${label}_err.log"
  Start-Process -FilePath "$rt\llama-server.exe" -ArgumentList $srvArgs `
    -RedirectStandardOutput "$scratch\srv_${label}.log" -RedirectStandardError $srvErr -WindowStyle Hidden
  python "$scratch\decode-probe.py" 8092 $label 2>&1 | Out-File $log -Append -Encoding utf8
  python "$scratch\copy-probe.py" 8092 2>&1 | Out-File $log -Append -Encoding utf8
  python "$scratch\ckpt-reuse-probe.py" 8092 $label 2>&1 | Out-File $log -Append -Encoding utf8
  "spec-lines:" | Out-File $log -Append -Encoding utf8
  Select-String -Path $srvErr -Pattern "draft acceptance|ngram|failed to mlock|NEVER" -ErrorAction SilentlyContinue | ForEach-Object { $_.Line } | Select-Object -Last 4 | Out-File $log -Append -Encoding utf8
  KillServer
  Start-Sleep -Seconds 3
}

# Gate first, candidates in the middle, gate LAST (first cycle after a kill reads depressed).
Cycle "gate" @()
Cycle "candidate" @("--spec-type","draft-mtp,ngram-mod","--spec-draft-n-max","8")
Cycle "gate2" @()

"--- restoring production runtime ---" | Out-File $log -Append -Encoding utf8
schtasks /Change /TN $task /Enable 2>&1 | Out-Null
schtasks /Run /TN TurbofitRuntime 2>&1 | Out-Null
"=== ALL DONE $(Get-Date -Format HH:mm:ss) ===" | Out-File $log -Append -Encoding utf8
