"""Controlled resume SOURCE/retention checks; no native operation or Git mutation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))  # Ordinary controlled imports; native entry uses verified buffers.
INDEX = ("openspec/changes/fix-accepted-policy-preprocessing/evidence/"
         "compiler-component-01/gate2-p0-465-retention.v1.json")


def descriptor(raw):
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


class ResumeSourceFormsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.index = json.loads((REPO / INDEX).read_bytes())
        old_index = self.root / component.RETENTION_INDEX_REL_V1
        old_index.parent.mkdir(parents=True, exist_ok=True)
        old_index.write_bytes((REPO / component.RETENTION_INDEX_REL_V1).read_bytes())
        self.sources = {}
        for slot, relative in enumerate(self.index["source_slots"]):
            raw = ((REPO / relative).read_bytes() if slot != 13 else b"controlled resume operator\n")
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.sources[slot] = descriptor(raw)
        self.code = {relative: self.sources[n] for n, relative in enumerate(self.index["source_slots"][:10])}
        self.write_index()

    def write_index(self):
        raw = component.canonical_json_v1(self.index) + b"\n"
        path = self.root / INDEX
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.index_descriptor = descriptor(raw)

    def quote(self):
        return component.resume_code_forms_quote_v1(self.root, code=self.code,
            plan=self.sources[10], operator=self.sources[13], index_descriptor=self.index_descriptor)

    def replace_source(self, slot, raw):
        (self.root / self.index["source_slots"][slot]).write_bytes(raw)
        self.sources[slot] = descriptor(raw)
        if slot < 10:
            self.code[self.index["source_slots"][slot]] = self.sources[slot]

    def maximum_sources(self):
        self.replace_source(0, b"C" * 131072)
        self.replace_source(1, b"M" * 32768)
        self.replace_source(13, b"R" * 32768)

    def test_reviewed_12k_plan_history_remains_inside_source_budget(self):
        self.maximum_sources()
        current = self.sources[10]
        row = [10, current["git_blob"], current["size_bytes"], current["sha256"]]
        self.assertEqual(len(self.index["source_versions"]), 22)
        self.assertEqual(self.index["source_versions"][21], row)
        self.assertIsNone(self.index["current_bindings"][10])
        self.assertEqual(self.quote(), 991232)
        self.assertEqual(component.RESUME_CODE_FORMS_V1, 1032192)

    def test_scoped_budget_keeps_legacy_and_counts_full_current_and_superseded_forms(self):
        self.maximum_sources()
        self.assertEqual(component.CURRENT_CODE_FORMS_V1, 524288)
        self.assertEqual(component.RESUME_CODE_FORMS_V1, 1032192)
        self.assertEqual(self.quote(), 991232)

    def test_extra_intermediate_plan_git_is_additive_even_when_current_bytes_unchanged(self):
        self.maximum_sources()
        self.assertEqual(self.quote(), 991232)
        raw = b"intermediate plan\n" * 2377
        raw = raw[:40421].ljust(40421, b"X")
        d = descriptor(raw)
        self.index["source_versions"].append([10, d["git_blob"], len(raw), d["sha256"]])
        self.write_index()
        with self.assertRaisesRegex(component.ComponentRecipeError, "forms bound"):
            self.quote()  # 991232 + 45056 = 1036288 > 1032192.

    def test_duplicate_version_and_unfunded_source_slot_refuse(self):
        for row in (self.index["source_versions"][0], [99, "a" * 40, 1, "b" * 64],
                    [8, "a" * 40, 1, "b" * 64]):
            with self.subTest(row=row):
                original = copy.deepcopy(self.index)
                self.index["source_versions"].append(row)
                self.write_index()
                with self.assertRaises(component.ComponentRecipeError):
                    self.quote()
                self.index = original

    def test_current_git_alias_requires_size_and_sha256_as_well_as_blob_identity(self):
        self.maximum_sources()
        current = self.sources[0]
        self.index["source_versions"].append([0, current["git_blob"],
            current["size_bytes"], current["sha256"]])
        self.write_index()
        self.assertEqual(self.quote(), 991232)
        self.index["source_versions"][-1][3] = "0" * 64
        self.write_index()
        with self.assertRaisesRegex(component.ComponentRecipeError, "forms bound"):
            self.quote()  # A claimed SHA1 collision is never full-blob alias credit.

    def test_wrong_index_source_identity_or_unchanged_alias_refuses(self):
        self.quote()
        for slot in (0, 2, 10, 13):
            path = self.root / self.index["source_slots"][slot]
            old = path.read_bytes()
            with self.subTest(slot=slot):
                path.write_bytes(old + b"drift")
                with self.assertRaises(component.ComponentRecipeError):
                    self.quote()
                path.write_bytes(old)
        self.index_descriptor = dict(self.index_descriptor, size_bytes=True)
        with self.assertRaises(component.ComponentRecipeError):
            self.quote()

    def test_unfunded_working_allocation_and_unknown_allocation_refuse(self):
        for allocation in (None, True, -1, 2**63, 2**30):
            with self.subTest(allocation=allocation), patch.object(component, "_resume_fd_allocation_v1",
                    return_value=allocation), self.assertRaises(component.ComponentRecipeError):
                self.quote()


class ResumeAuthenticatedReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name).resolve() / "source.py"
        self.path.write_bytes(b"authenticated bytes\n")

    def test_read_and_binding_failure_keep_primary_when_owned_close_also_fails(self):
        opened=component.os.fdopen
        for kind in ('read','binding'):
            for allocation in (False,True):
                closes=[]
                class Reader:
                    def __init__(self,file):self.file=file
                    def __enter__(self):return self
                    def __exit__(self,*args):self.close()
                    def fileno(self):return self.file.fileno()
                    def read(self,count):
                        if kind=='read':raise OSError('initiating read failure')
                        return self.file.read(count)[:-1]
                    def close(self):
                        closes.append(self.file.fileno());self.file.close()
                        raise OSError('distinct close failure')
                def fdopen(fd,*args,**kwargs):return Reader(opened(fd,*args,**kwargs))
                with self.subTest(kind=kind,allocation=allocation),patch.object(component.os,'fdopen',side_effect=fdopen):
                    with self.assertRaises(component.ComponentRecipeError) as caught:
                        component._retention_read_v1(self.path,4096,_allocation=allocation)
                    error=caught.exception
                    expected='retention_read_OSError' if kind=='read' else 'retention file drift'
                    self.assertEqual(error.cause,expected)
                    self.assertEqual(error.causes,[expected,'retention_close_OSError'])
                    self.assertEqual(error.facts['causes'],error.causes)
                    self.assertFalse(error.facts['close_completed']);self.assertTrue(error.facts['unknown_closure'])
                    self.assertEqual(len(closes),1)

    def test_fdopen_failure_and_release_failure_remain_ordered_without_release_retry(self):
        closed=[];close=component.os.close
        def failed_close(fd):closed.append(fd);close(fd);raise OSError('release failure')
        with patch.object(component.os,'fdopen',side_effect=ValueError('transfer failure')), \
                patch.object(component.os,'close',side_effect=failed_close):
            with self.assertRaises(component.ComponentRecipeError) as caught:
                component._retention_read_v1(self.path,4096)
        self.assertEqual(caught.exception.causes,['retention_fdopen_ValueError','retention_close_OSError'])
        self.assertTrue(caught.exception.facts['unknown_closure']);self.assertEqual(len(closed),1)

    def test_close_only_failure_is_not_a_successful_authenticated_read(self):
        fdopen=component.os.fdopen
        class Reader:
            def __init__(self,file):self.file=file
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def fileno(self):return self.file.fileno()
            def read(self,count):return self.file.read(count)
            def close(self):self.file.close();raise OSError('close failure')
        with patch.object(component.os,'fdopen',side_effect=lambda fd,*a,**kw:Reader(fdopen(fd,*a,**kw))):
            with self.assertRaises(component.ComponentRecipeError) as caught:
                component._resume_read_v1(self.path,4096)
        self.assertEqual(caught.exception.causes,['retention_close_OSError'])
        self.assertTrue(caught.exception.facts['unknown_closure'])

    def test_real_platform_allocation_and_bytes_are_read_together(self):
        raw, observed, allocation = component._resume_read_v1(self.path, 4096)
        self.assertEqual(raw, b"authenticated bytes\n")
        self.assertEqual(observed.st_size, len(raw))
        self.assertIs(type(allocation), int)
        self.assertGreaterEqual(allocation, 0)

    def test_known_allocation_is_observed_twice_on_same_authenticated_open_fd(self):
        fds = []
        def allocation(fd, observed):
            fds.append(fd)
            self.assertEqual(os.fstat(fd).st_ino, observed.st_ino)
            return 4096
        with patch.object(component, "_resume_fd_allocation_v1", side_effect=allocation):
            raw, observed, allocated = component._resume_read_v1(self.path, 4096)
        self.assertEqual(raw, b"authenticated bytes\n")
        self.assertEqual(allocated, 4096)
        self.assertEqual(len(fds), 2)
        self.assertEqual(fds[0], fds[1])
        with self.assertRaises(OSError):
            os.fstat(fds[0])

    def test_legal_short_regular_reads_accumulate_without_reopening_or_overreading(self):
        real_fdopen = component.os.fdopen
        requests = []
        class ShortReader:
            def __init__(self, file):
                self.file = file
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self.file.__exit__(*args)
            def close(self):
                return self.file.close()
            def fileno(self):
                return self.file.fileno()
            def read(self, count):
                requests.append(count)
                return self.file.read(min(7, count))
        def opened(fd, *args, **kwargs):
            return ShortReader(real_fdopen(fd, *args, **kwargs))
        with patch.object(component.os, "fdopen", side_effect=opened) as opening:
            raw, observed, allocated = component._resume_read_v1(self.path, 4096)
        self.assertEqual(raw, b"authenticated bytes\n")
        self.assertEqual(observed.st_size, len(raw))
        self.assertIs(type(allocated), int)
        self.assertEqual(opening.call_count, 1)
        self.assertEqual(requests, [4097, 13, 6])

    def test_allocation_drift_or_unknown_refuses_even_when_bytes_and_identity_match(self):
        for amounts in ([4096, 8192], [None, None], [True, True]):
            with self.subTest(amounts=amounts), patch.object(component, "_resume_fd_allocation_v1",
                    side_effect=amounts), self.assertRaises(component.ComponentRecipeError):
                component._resume_read_v1(self.path, 4096)

    def test_nonregular_or_link_refuses_before_potentially_blocking_open(self):
        directory, link = self.path.with_name("directory"), self.path.with_name("link")
        directory.mkdir()
        os.link(self.path, link)
        paths = [directory, link]
        if hasattr(os, "mkfifo"):
            fifo = self.path.with_name("fifo")
            os.mkfifo(fifo)
            paths.append(fifo)
        for path in paths:
            with self.subTest(kind=path.name), patch.object(component.os, "open",
                    side_effect=AssertionError("must not open")), self.assertRaises(component.ComponentRecipeError):
                component._resume_read_v1(path, 4096)


class ResumeReceiptTests(unittest.TestCase):
    setUp = ResumeSourceFormsTests.setUp
    write_index = ResumeSourceFormsTests.write_index

    def receipt(self):
        return {"node_count": 70, "native_code_quote_bytes": 586240, "parent_growth_bytes": 8192,
                "f2_quote_bytes": 4372992, "aux_quote_bytes": 39424, "windows_capture_quote_bytes": 32768,
                "diagnostic_quote_bytes": 16384, "diagnostic_sha256": self.index["refs"][3][3],
                "manifest_sha256": self.index["refs"][4][3], "physical_acceptance": False}

    def verify(self, receipt):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as resume
        # These two filesystem boundaries are controlled. No old native root is read.
        with patch.object(component, "verify_prior_retention_v1", return_value={"controlled_prior": True}), \
                patch.object(resume, "verify_retained_v1", return_value=receipt):
            return component.verify_resume_retention_v1(self.root, git_observation={},
                index_descriptor=self.index_descriptor)

    def test_closed_receipt_binds_independent_prior_and_fixed_native_evidence(self):
        native = self.receipt()
        result = self.verify(native)
        self.assertEqual(result["native"], native)
        self.assertEqual(result["prior"], {"controlled_prior": True})
        self.assertFalse(result["physical_acceptance"])
        self.assertEqual(result["index_sha256"], self.index_descriptor["sha256"])
        self.assertEqual(result["source_versions_sha256"], hashlib.sha256(
            component.canonical_json_v1(self.index["source_versions"])).hexdigest())

    def test_unknown_or_extra_forms_typed_limits_and_foreign_proof_refuse(self):
        for field, value in (("node_count", True), ("node_count", 69), ("parent_growth_bytes", 8193),
                ("native_code_quote_bytes", 586241), ("f2_quote_bytes", None),
                ("windows_capture_quote_bytes", 32769), ("diagnostic_quote_bytes", 16385),
                ("diagnostic_sha256", "0" * 64), ("physical_acceptance", True), ("extra_form", 0)):
            with self.subTest(field=field), self.assertRaises(component.ComponentRecipeError):
                self.verify(dict(self.receipt(), **{field: value}))


if __name__ == "__main__":
    unittest.main()
