"""Nonqualifying probe: empty failed-measurement channel on a real drvfs root.

Usage: python -B empty_channel_drvfs_probe.py <repo> <process_custody_module.py> <temp-base>

Loads the given publication_operational_process_custody_v1.py (HEAD copy or the
working-tree fix), opens PhysicalRootCustodyV1 on a fresh temporary root under
<temp-base> and writes one zero-byte failure channel through the production
_write_failure_channel path (O_EXCL create, fstat type/nlink/size/mode/identity,
uid/gid, fstat==lstat epoch, adopt_exact_durable_identity, held-channel
re-verification). No engine, socket, guardian or qualification state is used.
"""

import importlib.util
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


repo, module_path, base = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(repo / "scripts"))
spec = importlib.util.spec_from_file_location("process_custody_under_test", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from publication_physical_io_v1 import PhysicalRootCustodyV1  # noqa: E402

print(f"module={module_path}")
print(f"python={sys.version.split()[0]} temp_base={base}")
with tempfile.TemporaryDirectory(prefix="empty-channel-probe-", dir=base) as tmp:
    root = Path(tmp).resolve()
    (root / "outputs").mkdir()
    with PhysicalRootCustodyV1.open(root, label="drvfs empty channel probe root") as custody:
        print(f"root={root} permission_modes_enforced={custody.permission_modes_enforced}")
        capture = SimpleNamespace(custody=custody, controller=module._owner(os.getpid()), empty_failure_channels=[])
        path = root / "outputs" / "engine_01.failure.stderr.raw"
        try:
            descriptor = module._write_failure_channel(capture, path, b"")
            for fd, held_path, epoch in capture.empty_failure_channels:
                # Same re-verification as _Capture.verify for held empty channels.
                custody.adopt_exact_durable_identity(held_path, b"", label="held empty failed original channel",
                    mode=0o444, expected_identity=(epoch[0], epoch[1]), allow_empty=True)
            print(f"result=accepted descriptor={descriptor}")
        except Exception as error:  # noqa: BLE001 - the probe reports the outcome
            print(f"result=rejected {type(error).__name__}: {error}")
        finally:
            for fd, _, _ in capture.empty_failure_channels:
                os.close(fd)
        if os.path.lexists(path):
            info = path.lstat()
            print(f"leaf mode={oct(stat.S_IMODE(info.st_mode))} size={info.st_size} nlink={info.st_nlink} "
                  f"uid={info.st_uid} gid={info.st_gid}")
            os.chmod(path, 0o600)
