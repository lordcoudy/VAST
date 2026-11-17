"""Portable data checks for the D15 compiler seccomp profile.

Upstream: moby/profiles 836ae4d37ef2ec995c77c99fc55f5b5f3af3a897,
seccomp/default.json, 13470 bytes, SHA256
536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74.
Its Go generator uses JSON tab indentation without a final newline. The inverse
below recovers those exact bytes; no network or compressed baseline is needed.

The seven --red-baseline cases use that hash-proven original profile, through
the SAME assertions as GREEN. These are declarative profile checks, not a
kernel/libseccomp interpreter or proof of installed enforcement, CORE limits,
toolchain/ABI, container closure, component admission or whole-chain capacity.
No subprocess, socket, resource-limit or seccomp operation is performed.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest


PROFILE = Path(__file__).parent / "fixtures" / "accepted_policy_fixture_compiler_seccomp_v1.json"
PROFILE_BYTES = 31921
PROFILE_SHA256 = "ee45f10961781d812e88d185659b74e893031a4bd4e90d3cce0857d5308ba8cf"
BASELINE_BYTES = 13470
BASELINE_SHA256 = "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74"
MAX_PROFILE_BYTES = 65536
ALLOW = "SCMP_ACT_ALLOW"
ERRNO = "SCMP_ACT_ERRNO"
MASK = "SCMP_CMP_MASKED_EQ"
RED_BASELINE = False
UPSTREAM_ARCH_MAP = json.loads(r'''[
    {
        "architecture": "SCMP_ARCH_X86_64",
        "subArchitectures": [
            "SCMP_ARCH_X86",
            "SCMP_ARCH_X32"
        ]
    },
    {
        "architecture": "SCMP_ARCH_AARCH64",
        "subArchitectures": [
            "SCMP_ARCH_ARM"
        ]
    },
    {
        "architecture": "SCMP_ARCH_MIPS64",
        "subArchitectures": [
            "SCMP_ARCH_MIPS",
            "SCMP_ARCH_MIPS64N32"
        ]
    },
    {
        "architecture": "SCMP_ARCH_MIPS64N32",
        "subArchitectures": [
            "SCMP_ARCH_MIPS",
            "SCMP_ARCH_MIPS64"
        ]
    },
    {
        "architecture": "SCMP_ARCH_MIPSEL64",
        "subArchitectures": [
            "SCMP_ARCH_MIPSEL",
            "SCMP_ARCH_MIPSEL64N32"
        ]
    },
    {
        "architecture": "SCMP_ARCH_MIPSEL64N32",
        "subArchitectures": [
            "SCMP_ARCH_MIPSEL",
            "SCMP_ARCH_MIPSEL64"
        ]
    },
    {
        "architecture": "SCMP_ARCH_S390X",
        "subArchitectures": [
            "SCMP_ARCH_S390"
        ]
    },
    {
        "architecture": "SCMP_ARCH_RISCV64",
        "subArchitectures": null
    },
    {
        "architecture": "SCMP_ARCH_LOONGARCH64",
        "subArchitectures": null
    }
]''')


def _baseline_bytes(profile):
    """Undo only the declared fixed delta, then hash all original records."""
    value = copy.deepcopy(profile)
    value["syscalls"] = value["syscalls"][:-65]
    names = value["syscalls"][0]["names"]
    names.insert(names.index("process_mrelease"), "prlimit64")
    names.insert(names.index("set_robust_list"), "setrlimit")
    original = {
        "defaultAction": value["defaultAction"],
        "defaultErrnoRet": value["defaultErrnoRet"],
        "archMap": UPSTREAM_ARCH_MAP,
        "syscalls": value["syscalls"],
    }
    return json.dumps(original, indent="\t", ensure_ascii=True).encode("ascii")


def _new_rules():
    """Expected closed 32+32+1 rule inventory, never used as a live profile."""
    result = []
    for name, index in (("setrlimit", 0), ("prlimit64", 1)):
        for bit in range(32):
            mask = 1 << bit
            result.append({
                "names": [name], "action": ALLOW,
                "args": [{"index": index, "value": mask,
                          "valueTwo": 0 if bit == 2 else mask, "op": MASK}],
            })
    result.append({
        "names": ["prlimit64"], "action": ALLOW,
        "args": [
            {"index": 1, "value": 0xFFFFFFFF, "valueTwo": 4, "op": MASK},
            {"index": 2, "value": 0, "op": "SCMP_CMP_EQ"},
        ],
    })
    return result


def _selected(row, *, caps, kernel):
    """Evaluate only the upstream selector vocabulary for controlled contexts."""
    for field, exclude in (("includes", False), ("excludes", True)):
        spec = row.get(field)
        if spec is None:
            continue
        if not set(spec) <= {"arches", "caps", "minKernel"}:
            raise AssertionError("unreviewed selector vocabulary")
        if exclude:
            if "arches" in spec and "amd64" in spec["arches"]:
                return False
            if "caps" in spec and any(cap in caps for cap in spec["caps"]):
                return False
            if "minKernel" in spec and kernel >= tuple(map(int, spec["minKernel"].split("."))):
                return False
        else:
            if "arches" in spec and "amd64" not in spec["arches"]:
                return False
            if "caps" in spec and not all(cap in caps for cap in spec["caps"]):
                return False
            if "minKernel" in spec and kernel < tuple(map(int, spec["minKernel"].split("."))):
                return False
    return True


def _matches(condition, args):
    value = args[condition["index"]]
    expected = condition["value"]
    op = condition["op"]
    if op == MASK:
        return value & expected == condition.get("valueTwo", 0)
    if op == "SCMP_CMP_EQ":
        return value == expected
    if op == "SCMP_CMP_LT":
        return value < expected
    if op == "SCMP_CMP_GT":
        return value > expected
    raise AssertionError("unreviewed comparison operator")


def _decision(profile, name, args=(0, 0, 0, 0, 0, 0), *, caps=(), kernel=(6, 6)):
    """Test-only JSON predicate evaluator; it does not install/compile a filter."""
    if len(args) != 6 or not all(type(x) is int and 0 <= x < 1 << 64 for x in args):
        raise AssertionError("native unsigned-64 test arguments required")
    outcomes = set()
    for row in profile["syscalls"]:
        if name in row["names"] and _selected(row, caps=set(caps), kernel=kernel):
            conditions = row.get("args", [])
            if len({x["index"] for x in conditions}) != len(conditions):
                raise AssertionError("repeated argument index is not an AND condition")
            if all(_matches(x, args) for x in conditions):
                outcomes.add((row["action"], row.get("errnoRet", profile["defaultErrnoRet"])))
    if len(outcomes) > 1:
        raise AssertionError("conflicting selected profile actions")
    return next(iter(outcomes), (profile["defaultAction"], profile["defaultErrnoRet"]))


class FixtureCompilerSeccompTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with PROFILE.open("rb") as stream:
            cls.raw = stream.read(MAX_PROFILE_BYTES + 1)
        if len(cls.raw) > MAX_PROFILE_BYTES:
            raise AssertionError("profile exceeds bounded reader")
        cls.profile = json.loads(cls.raw)
        if RED_BASELINE:
            baseline = _baseline_bytes(cls.profile)
            if (len(baseline) != BASELINE_BYTES
                    or hashlib.sha256(baseline).hexdigest() != BASELINE_SHA256):
                raise AssertionError("original RED profile is not the pinned baseline")
            cls.profile = json.loads(baseline)

    def test_derived_raw_bytes_are_pinned(self):
        self.assertEqual(len(self.raw), PROFILE_BYTES)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), PROFILE_SHA256)
        self.assertTrue(self.raw.endswith(b"\n"))

    def test_only_native_amd64_architecture_is_selected(self):
        self.assertFalse("archMap" in self.profile, "legacy compatibility architecture map remains")
        self.assertEqual(self.profile.get("architectures"), ["SCMP_ARCH_X86_64"])

    def test_total_rule_count_is_98(self):
        self.assertEqual(len(self.profile["syscalls"]), 98)

    def test_no_blanket_resource_setter_allow_remains(self):
        blanket = [name for row in self.profile["syscalls"]
                   if row["action"] == ALLOW and not row.get("args")
                   for name in row["names"] if name in {"setrlimit", "prlimit64"}]
        self.assertEqual(blanket, [])

    def test_exact_65_rule_inventory(self):
        self.assertEqual(self.profile["syscalls"][-65:], _new_rules())
        self.assertTrue(all(type(arg["index"]) is int and type(arg["value"]) is int
                            for row in self.profile["syscalls"][-65:]
                            for arg in row["args"]))

    def test_inverse_recovers_full_upstream_bytes(self):
        baseline = _baseline_bytes(self.profile)
        self.assertEqual(len(baseline), BASELINE_BYTES)
        self.assertEqual(hashlib.sha256(baseline).hexdigest(), BASELINE_SHA256)

    def test_closed_top_level_and_default_errno(self):
        self.assertEqual(set(self.profile),
                         {"defaultAction", "defaultErrnoRet", "architectures", "syscalls"})
        self.assertEqual((self.profile["defaultAction"], self.profile["defaultErrnoRet"]),
                         (ERRNO, 1))

    def test_core_setrlimit_writes_are_denied(self):
        self.assertEqual(_decision(self.profile, "setrlimit", (4, 1, 0, 0, 0, 0)),
                         (ERRNO, 1))

    def test_core_prlimit_writes_are_denied(self):
        self.assertEqual(_decision(self.profile, "prlimit64", (0, 4, 1, 0, 0, 0)),
                         (ERRNO, 1))

    def test_upper_resource_alias_cannot_bypass_core_write_denial(self):
        aliases = [4, (1 << 32) | 4, (0x7FFFFFFF << 32) | 4, (0xFFFFFFFF << 32) | 4]
        self.assertTrue(all(_decision(self.profile, "setrlimit", (r, 1, 0, 0, 0, 0))[0] != ALLOW
                            and _decision(self.profile, "prlimit64", (0, r, 1, 0, 0, 0))[0] != ALLOW
                            for r in aliases))

    def test_high_nonnull_native_pointer_is_still_a_core_write(self):
        pointers = [1, 1 << 32, 1 << 63, (1 << 64) - 1]
        self.assertTrue(all(_decision(self.profile, "prlimit64", (0, 4, p, 0, 0, 0))[0] != ALLOW
                            for p in pointers))

    def test_native_core_query_and_resource_alias_queries_remain_allowed(self):
        for r in (4, (1 << 32) | 4, (0xFFFFFFFF << 32) | 4):
            with self.subTest(resource=r):
                self.assertEqual(_decision(self.profile, "prlimit64", (0, r, 0, 1, 0, 0))[0], ALLOW)
        self.assertEqual(_decision(self.profile, "getrlimit", (4, 1, 0, 0, 0, 0))[0], ALLOW)

    def test_every_low32_complement_bit_preserves_noncore_calls(self):
        resources = [4 ^ (1 << bit) for bit in range(32)] + [0, 3, 5, 15, 0xFFFFFFFF]
        for r in resources:
            for high in (0, 1, 0xFFFFFFFF):
                value = (high << 32) | r
                with self.subTest(resource=value):
                    self.assertEqual(_decision(self.profile, "setrlimit", (value, 1, 0, 0, 0, 0))[0], ALLOW)
                    self.assertEqual(_decision(self.profile, "prlimit64", (0, value, 1, 0, 0, 0))[0], ALLOW)
        # ALLOW here means only that the original kernel range/error decision is preserved.

    def test_baseline_denials_and_clone3_errno_are_preserved(self):
        for family in (38, 40):
            self.assertEqual(_decision(self.profile, "socket", (family, 0, 0, 0, 0, 0)), (ERRNO, 1))
        self.assertEqual(_decision(self.profile, "socket", (39, 0, 0, 0, 0, 0))[0], ALLOW)
        self.assertEqual(_decision(self.profile, "clone3"), (ERRNO, 38))
        for name in ("bpf", "mount", "unshare"):
            self.assertEqual(_decision(self.profile, name), (ERRNO, 1))

    def test_dynamic_kernel_and_bounding_cap_selectors_are_retained(self):
        self.assertEqual(_decision(self.profile, "ptrace", kernel=(4, 7)), (ERRNO, 1))
        self.assertEqual(_decision(self.profile, "ptrace", kernel=(6, 6))[0], ALLOW)
        self.assertEqual(_decision(self.profile, "bpf", caps=("CAP_BPF",))[0], ALLOW)
        self.assertEqual(_decision(self.profile, "clone3", caps=("CAP_SYS_ADMIN",))[0], ALLOW)
        # These are synthetic data contexts; the D15 live profile must drop all capabilities.

    def test_required_native_reader_and_process_calls_keep_baseline_allow(self):
        for name in ("read", "write", "close", "openat", "fork", "execve", "wait4"):
            with self.subTest(name=name):
                self.assertEqual(_decision(self.profile, name)[0], ALLOW)


RED_METHODS = (
    "test_only_native_amd64_architecture_is_selected",
    "test_total_rule_count_is_98",
    "test_no_blanket_resource_setter_allow_remains",
    "test_core_setrlimit_writes_are_denied",
    "test_core_prlimit_writes_are_denied",
    "test_upper_resource_alias_cannot_bypass_core_write_denial",
    "test_high_nonnull_native_pointer_is_still_a_core_write",
)


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--red-baseline"]):
        raise SystemExit("only the closed --red-baseline fixture selection is supported")
    RED_BASELINE = sys.argv[1:] == ["--red-baseline"]
    if RED_BASELINE:
        suite = unittest.TestSuite(FixtureCompilerSeccompTests(name) for name in RED_METHODS)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixtureCompilerSeccompTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "group": "original_baseline_red" if RED_BASELINE else "derived_profile_green",
        "tests_run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skips": len(result.skipped),
        "success": result.wasSuccessful(), "portable_data_checks_only": True,
        "kernel_seccomp_enforcement_qualified": False, "core_limit_qualified": False,
        "compiler_or_abi_qualified": False, "component_admitted": False,
        "whole_chain_capacity_accepted": False,
        "profile_sha256": hashlib.sha256(FixtureCompilerSeccompTests.raw).hexdigest(),
        "original_baseline_sha256": BASELINE_SHA256,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if result.wasSuccessful() else 1)
