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
    print("education package:", o.win_package("education"))
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

if os.environ.get("FULL"):
    o.ensure("education", print)
    assert o.installed("education"), "Minecraft Education not found after installing"
    print("installed:", o.win_package("education") if o.IS_WIN else o.mac_app())
    print("launch:", o.launch_command("education")[:4])
    o.ensure("education", print)             # second time: already up to date, no download
print("OFFICIAL OK")
