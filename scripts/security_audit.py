#!/usr/bin/env python3
"""
Status Page — Weekly Dependency & Security Audit
Runs: pip-audit for vulnerabilities + pip list for outdated packages.
Outputs to stdout for cron delivery.
"""

import subprocess
import sys
import json
from datetime import datetime

REPO_DIR = "/home/openclaw-user/.hermes/workspaces/status-page"

def run(cmd, cwd=REPO_DIR):
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    return result.stdout, result.stderr, result.returncode

def main():
    print("=" * 60)
    print(f"Status Page — Security Audit")
    print(f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Check for outdated packages
    print("\n[1] Outdated Packages")
    print("-" * 40)
    stdout, stderr, rc = run("pip list --outdated --format=json")
    if rc == 0 and stdout.strip():
        try:
            outdated = json.loads(stdout)
            if outdated:
                for pkg in outdated:
                    print(f"  {pkg['name']:<30} {pkg['version']:<15} -> {pkg['latest_version']}")
                print(f"\n  Total outdated: {len(outdated)}")
            else:
                print("  All packages are up to date.")
        except json.JSONDecodeError:
            print(f"  Could not parse pip list output:\n{stdout}")
    else:
        print(f"  pip list failed: {stderr or 'no output'}")

    # 2. Vulnerability scan (pip-audit)
    print("\n[2] Known Vulnerabilities (pip-audit)")
    print("-" * 40)
    stdout, stderr, rc = run("pip-audit --format=columns 2>&1 || pip-audit 2>&1")
    if rc == 0:
        lines = stdout.strip().splitlines()
        if any("no vulnerabilities found" in l.lower() for l in lines):
            print("  ✅ No known vulnerabilities found.")
        else:
            print(stdout)
    else:
        # pip-audit may not be installed
        print(f"  pip-audit not available: {stderr}")
        print("  Install with: pip install pip-audit")
        # Fallback: safety check
        stdout2, _, rc2 = run("safety check --json 2>&1 || safety check 2>&1")
        if rc2 == 0 and "no vulnerabilities" in stdout2.lower():
            print("  ✅ No known vulnerabilities found (via safety).")
        elif stdout2.strip():
            print("  Safety report:")
            print(stdout2)
        else:
            print("  Could not run vulnerability scan. Install pip-audit: pip install pip-audit")

    # 3. Quick security sanity check on key files
    print("\n[3] Code Security Quick-Check")
    print("-" * 40)
    checks_passed = 0
    checks_failed = 0

    # Check monitor.py for SSRF protections
    with open(f"{REPO_DIR}/app/monitor.py") as f:
        monitor = f.read()

    ssrf_safe = any(keyword in monitor for keyword in [
        "ipaddress", "is_private", "is_loopback", "blocklist", "allowlist",
        "PRIVATE", "10.0.0.0", "169.254"
    ])
    if ssrf_safe:
        print("  ✅ SSRF protection keywords detected in monitor.py")
        checks_passed += 1
    else:
        print("  ⚠️  NO SSRF protection keywords found in monitor.py")
        print("      -> User-supplied URLs/hosts are not validated against private IP ranges")
        checks_failed += 1

    # Check httpx follow_redirects
    if "follow_redirects=False" in monitor or "follow_redirects = False" in monitor:
        print("  ✅ HTTP redirects explicitly disabled")
        checks_passed += 1
    else:
        print("  ⚠️  httpx may follow redirects (not disabled)")
        checks_failed += 1

    # Check CORS settings in main.py
    with open(f"{REPO_DIR}/app/main.py") as f:
        main_content = f.read()

    if 'allow_origins=["*"]' in main_content or "allow_origins=['*']" in main_content:
        print("  ⚠️  CORS is wide open (allow_origins=*) — acceptable for internal use only")
        checks_failed += 1
    else:
        print("  ✅ CORS origins are restricted")
        checks_passed += 1

    # Check for plaintext SMTP password
    with open(f"{REPO_DIR}/app/routers/config.py") as f:
        config_content = f.read()

    if "encrypt" in config_content.lower() or "hash" in config_content.lower():
        print("  ✅ SMTP password appears to be hashed/encrypted")
        checks_passed += 1
    else:
        print("  ⚠️  SMTP password stored in plaintext in DB")
        checks_failed += 1

    print(f"\n  Security checks: {checks_passed} passed, {checks_failed} failed")

    print("\n" + "=" * 60)
    print("Audit complete.")
    print("=" * 60)

if __name__ == "__main__":
    main()
