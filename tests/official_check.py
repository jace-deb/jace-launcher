"""Checks jace/official.py on Windows / macOS runners.

Quick (every build): the PowerShell parts parse and run, Microsoft's download links resolve.
FULL=1 (manual "Official apps" workflow): really install Minecraft Education from Microsoft
and check Jace Launcher finds it and can build its launch command.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from jace import official as o  # noqa: E402

url, ver = o._latest(o.EDU_WIN_URL if o.IS_WIN else o.EDU_MAC_URL)
print("latest Education:", ver, url)
assert ver, "no version in the download URL"

if o.IS_WIN:
    print("bedrock package:", o.win_package("bedrock"))
    print("education package:", o.win_package("education"), o.win_education())
    real = o.win_package
    o.win_package = lambda kind: {"name": "X", "version": "1.2.3.4", "location": "C:\\Program Files\\WindowsApps\\X",
                                  "aumid": "X_8wekyb3d8bbwe!App"}
    for kind in ("bedrock", "education"):
        script = o.launch_command(kind)[-1]
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseInput("
                            "$env:S, [ref]$null, [ref]$e); if ($e) { $e | Out-String; exit 1 }"],
                           env={**os.environ, "S": script}, capture_output=True, text=True)
        assert r.returncode == 0, f"{kind} launch script doesn't parse:\n{r.stdout}{r.stderr}"
    o.win_package = real

def status(msg, _last=[""]):
    if msg.startswith("Downloading") and "%" in msg:
        pct = msg.split("…")[1].split("%")[0].strip()
        if pct == _last[0] or int(pct) % 10:
            return
        _last[0] = pct
    print(msg, flush=True)


if os.environ.get("FULL"):
    os.environ["JACE_NO_INTERACTIVE"] = "1"
    try:
        o.ensure("education", status)
    except o.OfficialError:
        if o.IS_WIN:                             # what did the installer do?
            print(o._ps(r"""
"--- appx:"; Get-AppxPackage -AllUsers | Where-Object { $_.Name -match 'minecraft|edu|mojang' } | Format-List Name, PackageFullName, InstallLocation, Status | Out-String
"--- provisioned:"; Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -match 'minecraft|edu' } | Out-String
"--- uninstall entries:"; Get-ChildItem HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall, HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall, HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall | Get-ItemProperty | Where-Object { $_.DisplayName -match 'minecraft|edu' } | Format-List DisplayName, InstallLocation, UninstallString | Out-String
"--- files:"; Get-ChildItem 'C:\Program Files', 'C:\Program Files (x86)', "$env:LOCALAPPDATA\Programs", 'C:\XboxGames' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'minecraft|edu' } | Format-List FullName | Out-String
"--- recent temp logs:"; Get-ChildItem $env:TEMP -Recurse -Include *.log -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object { "== " + $_.FullName; Get-Content $_.FullName -Tail 40 }
"--- appx deployment events:"; Get-WinEvent -LogName 'Microsoft-Windows-AppXDeploymentServer/Operational' -MaxEvents 15 -ErrorAction SilentlyContinue | Format-List TimeCreated, Message | Out-String -Width 300
""", timeout=180))
        raise
    assert o.installed("education"), "Minecraft Education not found after installing"
    print("installed:", (o.win_education() or o.win_package("education")) if o.IS_WIN else o.mac_app())
    if o.IS_WIN and o.win_education():
        print("files:", sorted(p.name for p in __import__("pathlib").Path(o.win_education()["location"]).iterdir()))
    print("launch:", o.launch_command("education")[:4])
    o.ensure("education", status)            # second time: already up to date, no download
print("OFFICIAL OK")
