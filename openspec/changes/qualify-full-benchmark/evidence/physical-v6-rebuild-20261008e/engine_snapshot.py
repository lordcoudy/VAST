"""Write the live Docker engine identity and compare it with the 6A.2 record. usage: engine_snapshot.py <out.json>"""
import json, subprocess, sys
from datetime import datetime, timezone
RECORD = "/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008e/docker-engine-identity.6A2.v1.json"
def info(*argv):
    return json.loads(subprocess.run(["/usr/bin/docker", *argv, "--format", "{{json .}}"], check=True, capture_output=True, text=True).stdout)
v, i = info("version"), info("info")
obs = {"platform_name": v["Server"].get("Platform", {}).get("Name"), "server_version": v["Server"]["Version"],
       "api_version": v["Server"]["ApiVersion"], "client_version": v["Client"]["Version"], "daemon_id": i["ID"],
       "name": i["Name"], "driver": i["Driver"], "driver_type": dict(i.get("DriverStatus") or []).get("driver-type")}
eq = obs == json.load(open(RECORD))["identity"]
json.dump({"observed_at_utc": datetime.now(timezone.utc).isoformat(), "boot_id": open("/proc/sys/kernel/random/boot_id").read().strip(),
           "observed": obs, "equal": eq}, open(sys.argv[1], "w"), indent=1)
sys.exit(0 if eq else 5)
