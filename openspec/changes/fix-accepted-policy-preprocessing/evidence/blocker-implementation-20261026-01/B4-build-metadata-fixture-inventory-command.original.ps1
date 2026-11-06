& wsl.exe --distribution Ubuntu --user s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST --exec /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/.venv/bin/python -B -c 'from pathlib import Path
import json,os,stat
totals={"files":0,"directories":0,"logical_bytes":0,"file_4k_units":0,"roots":0}
phases={}
for phase in ("red","green"):
 root=Path("/var/tmp/vast-pr9-b2-prep-buildmeta-"+phase+"-01")
 assert root.is_dir() and not root.is_symlink()
 rows={"files":0,"directories":1,"logical_bytes":0,"file_4k_units":0,"roots":0}
 pending=[root]
 while pending:
  parent=pending.pop()
  with os.scandir(parent) as entries:
   for entry in entries:
    assert len(entry.name)<=255 and not entry.is_symlink()
    info=entry.stat(follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
     rows["directories"]+=1
     if parent==root:rows["roots"]+=1
     pending.append(Path(entry.path))
    else:
     assert stat.S_ISREG(info.st_mode) and info.st_nlink==1
     rows["files"]+=1;rows["logical_bytes"]+=info.st_size
     rows["file_4k_units"]+=(info.st_size+4095)//4096
    assert rows["files"]<=256 and rows["directories"]<=256 and rows["logical_bytes"]<=65536 and len(pending)<=256
 phases[phase]=rows
 for key in totals:totals[key]+=rows[key]
assert totals["roots"]<=64 and totals["files"]<=256 and totals["directories"]<=256 and totals["logical_bytes"]<=65536
print(json.dumps({"scope":"retained_fixture_inventory_only","phases":phases,"total":totals,"cleanup_credit":False,"physical_acceptance":False},sort_keys=True,separators=(",",":")))'
