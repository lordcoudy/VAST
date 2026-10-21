"""Portable fixed-retention controls; no old Git objects, native calls or raw copies."""
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component


class FixedLimitsTests(unittest.TestCase):
    def test_one_authority_preserves_combined_and_successor_bounds(self):
        self.assertEqual(component.TOTAL_F2_LIMIT_V1, 8388608)
        self.assertEqual(component.OLD_F2_PROOF_UPPER_V1, 393216)
        self.assertEqual(component.ACTIVE_F2_LIMIT_V1, 7995392)
        self.assertEqual(component.ACTIVE_F2_LIMIT_V1 + component.OLD_F2_PROOF_UPPER_V1,
                         component.TOTAL_F2_LIMIT_V1)
        self.assertEqual(dict(component.F2_CONTROL_CAPS_V1), {
            "f2.originals.v1.json": 262144, "f2.supplement.v1.json": 262144,
            "f2.failure.v1.json": 262144, "f2.final-accounting.v1.json": 16384})
        self.assertEqual(component.PRIOR_CARRY_BYTES_V1, 6291456)
        with self.assertRaises(TypeError):
            component.F2_CONTROL_CAPS_V1["f2.failure.v1.json"] = 1

    def test_frozen_index_has_no_commit_or_self_hash_cycle(self):
        root = Path(__file__).resolve().parents[1]
        bindings = component.retained_source_bindings_v1(root)
        self.assertEqual(bindings["index"], {"size_bytes": 9637, "sha256":
            "8925428192e339d52d2bcc7a2f99587303765796dc0769f47dcf192ce40ce006"})
        self.assertEqual(len(bindings["sources"]), 13)
        self.assertEqual(len({row["path"] for row in bindings["sources"]}), 13)
        self.assertEqual(bindings["source_rows_sha256"], hashlib.sha256(
            component.canonical_json_v1(bindings["sources"])).hexdigest())

    def test_index_hash_canonical_and_link_guards_are_real(self):
        root = Path(__file__).resolve().parents[1]
        raw = (root / component.RETENTION_INDEX_REL_V1).read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            path = repo / component.RETENTION_INDEX_REL_V1
            path.parent.mkdir(parents=True)
            for bad in (raw + b" ", raw.replace(b'"physical_acceptance":false',
                                                  b'"physical_acceptance":true')):
                path.write_bytes(bad)
                with self.assertRaises(component.ComponentRecipeError):
                    component.retained_source_bindings_v1(repo)
            path.write_bytes(raw)
            self.assertEqual(len(component.retained_source_bindings_v1(repo)["sources"]), 13)
            alias = path.with_suffix(".alias")
            alias.hardlink_to(path)
            with self.assertRaises(component.ComponentRecipeError):
                component.retained_source_bindings_v1(repo)


class NativeRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve() / "repo"
        self.repo.mkdir()
        self.old = self.repo.parent / "old"
        self.temp = self.repo.parent / "temp"
        self.temp.mkdir()
        original = Path(__file__).resolve().parents[1] / component.RETENTION_INDEX_REL_V1
        self.index = json.loads(original.read_bytes())
        self.raws = {}
        for number, row in enumerate(self.index["src"]):
            raw = ("controlled source %d\n" % number).encode()
            row[1:] = [hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                       len(raw), hashlib.sha256(raw).hexdigest()]
            self.raws[number] = raw
        for relative in ("", "scripts", "tests", "tests/fixtures"):
            (self.old / relative).mkdir(parents=True, exist_ok=True)
        names = [row[0] for row in self.index["src"]]
        for number in range(11):
            name = names[number]
            relative = ("scripts/publication_operational_request_domain_v1.py" if name == "@script" else
                        "physical-plan.v8.md" if name == "@v8" else
                        "tests/fixtures/accepted_policy_fixture_compiler" + name)
            (self.old / relative).write_bytes(self.raws[number])
        for category in ("F2", "AUX"):
            folder = Path(str(self.old) + self.index["retained"][category]["suffix"])
            folder.mkdir()
            for row in self.index["retained"][category]["files"]:
                raw = ("controlled " + row[0]).encode() if row[1] else b""
                (folder / row[0]).write_bytes(raw)
                row[1:] = [len(raw), (folder / row[0]).stat().st_blocks, hashlib.sha256(raw).hexdigest()]
        self.windows = []
        for number, row in enumerate(self.index["retained"]["win"]):
            path = self.temp / ("window%d" % number)
            raw = ("controlled window%d" % number).encode()
            path.write_bytes(raw)
            row[1:4] = [len(raw), path.stat().st_blocks, hashlib.sha256(raw).hexdigest()]
            self.windows.append(path)
        transcript = b"controlled actual held transcript"
        self.transcript = self.temp / "transcript"
        self.transcript.write_bytes(transcript)
        self.index["retained"]["transcript"][1:3] = [len(transcript), hashlib.sha256(transcript).hexdigest()]
        self.index_path = self.repo / component.RETENTION_INDEX_REL_V1
        self.index_path.parent.mkdir(parents=True)
        self.index_raw = component.canonical_json_v1(self.index) + b"\n"
        self.index_path.write_bytes(self.index_raw)
        self.component_path = self.repo / "tests/fixtures/accepted_policy_fixture_compiler_component_v1.py"
        self.component_path.parent.mkdir(parents=True)
        self.component_path.write_bytes(b"# controlled current authenticated component\n")
        self.patches = [patch.object(component, "RETENTION_INDEX_SHA256_V1", hashlib.sha256(self.index_raw).hexdigest()),
                        patch.object(component, "RETENTION_INDEX_SIZE_V1", len(self.index_raw)),
                        patch.object(component, "_OLD_ROOT_V1", self.old),
                        patch.object(component, "_old_windows_paths_v1", return_value=tuple(self.windows)),
                        patch.object(component, "_old_transcript_path_v1", return_value=self.transcript)]
        for effect in self.patches:
            effect.start()
            self.addCleanup(effect.stop)
        bindings = component.retained_source_bindings_v1(self.repo)
        raw = self.component_path.read_bytes()
        self.observation = {"component": {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()},
            "index": dict(bindings["index"], git_blob=hashlib.sha1(
                b"blob " + str(len(self.index_raw)).encode() + b"\0" + self.index_raw).hexdigest()),
            "old_git_sha256": bindings["source_rows_sha256"]}

    def verify(self):
        return component.verify_prior_retention_v1(self.repo, git_observation=self.observation)

    def test_fresh_exact_inventory_returns_bounded_receipt(self):
        receipt = self.verify()
        self.assertEqual(receipt["node_count"], 28)
        self.assertEqual(receipt["owned_upper_bytes"], 2102272)
        self.assertEqual(receipt["old_f2_upper_bytes"], 333056)
        self.assertFalse(receipt["physical_acceptance"])
        self.assertLessEqual(len(component.canonical_json_v1(receipt)), 1024)

    def test_missing_extra_and_tampered_originals_refuse(self):
        target = Path(str(self.old) + ".f2") / "RPC03.reply.original"
        raw = target.read_bytes()
        for failure in ("missing", "extra", "changed", "hardlink"):
            with self.subTest(failure=failure):
                extra = target.with_name("unexpected")
                if failure == "missing":
                    target.unlink()
                elif failure == "extra":
                    extra.write_bytes(b"new")
                elif failure == "changed":
                    target.write_bytes(raw + b"x")
                else:
                    extra.hardlink_to(target)
                with self.assertRaises((component.ComponentRecipeError, FileNotFoundError)):
                    self.verify()
                if extra.exists():
                    extra.unlink()
                target.write_bytes(raw)

    def test_windows_transcript_source_and_git_observation_drift_refuse(self):
        for path in (self.windows[0], self.transcript, self.component_path):
            raw = path.read_bytes()
            path.write_bytes(raw + b"x")
            with self.subTest(path=path), self.assertRaises(component.ComponentRecipeError):
                self.verify()
            path.write_bytes(raw)
        self.observation["old_git_sha256"] = "0" * 64
        with self.assertRaises(component.ComponentRecipeError):
            self.verify()

    def test_unknown_or_excess_native_blocks_and_receipt_types_refuse(self):
        self.verify()
        actual = component._retention_blocks_v1
        for blocks in (None, True, 2 ** 40):
            with self.subTest(blocks=blocks), patch.object(component, "_retention_blocks_v1", return_value=blocks):
                with self.assertRaises(component.ComponentRecipeError):
                    self.verify()
        receipt = self.verify()
        for key, value in (("node_count", True), ("physical_acceptance", True),
                           ("owned_upper_bytes", 2162689), ("old_f2_upper_bytes", 393217)):
            with self.subTest(key=key), self.assertRaises(component.ComponentRecipeError):
                component.validate_prior_retention_receipt_v1(dict(receipt, **{key: value}),
                    source_rows_sha256=self.observation["old_git_sha256"])

    def test_old_proof_allocation_cannot_borrow_unused_code_blocks(self):
        target=Path(str(self.old)+".f2")/"RPC03.reply.original"
        inode=target.stat().st_ino
        blocks=component._retention_blocks_v1
        # Whole native inventory still fits633856, but this single proof
        # allocation exceeds its106496 allforms reserve. Code slack is irrelevant.
        with patch.object(component,"_retention_blocks_v1",side_effect=lambda s:
                blocks(s)+256 if s.st_ino==inode else blocks(s)):
            with self.assertRaisesRegex(component.ComponentRecipeError,"category"):
                self.verify()

    def test_block_extent_drift_during_original_read_refuses(self):
        original=component.os.fstat
        count=[0]
        def fstat(fd):
            observed=original(fd); count[0]+=1
            if count[0]==2:
                fields={key:getattr(observed,key) for key in ("st_dev","st_ino","st_mode","st_nlink","st_size",
                    "st_mtime_ns","st_ctime_ns","st_blocks")}
                fields["st_blocks"]+=8
                return SimpleNamespace(**fields)
            return observed
        with patch.object(component.os,"fstat",side_effect=fstat):
            with self.assertRaisesRegex(component.ComponentRecipeError,"drift"):
                self.verify()

    def test_nonregular_refuses_before_any_blocking_open(self):
        with patch.object(Path,"lstat",return_value=SimpleNamespace(st_mode=stat.S_IFIFO,st_nlink=1,st_size=0)),\
                patch.object(Path,"open",side_effect=AssertionError("blocking open must not start")):
            with self.assertRaises(component.ComponentRecipeError):
                component._retention_read_v1(self.index_path,12288)

    def test_kind_change_at_open_is_nonblocking_and_refuses_fd_identity(self):
        original=component.os.open
        flags=[]
        def opened(path,mode,*args,**kwargs):
            flags.append(mode)
            return original(self.component_path,mode,*args,**kwargs)
        with patch.object(component.os,"open",side_effect=opened):
            with self.assertRaisesRegex(component.ComponentRecipeError,"identity"):
                component._retention_read_v1(self.index_path,12288)
        self.assertTrue(flags[0]&os.O_NONBLOCK)
        self.assertTrue(flags[0]&os.O_NOFOLLOW)

    def test_unknown_inventory_refuses_without_enumerating_unbounded_directory(self):
        consumed=[]
        class UnknownEntries:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def __iter__(self): return self
            def __next__(self):
                consumed.append(1)
                if len(consumed)>1: raise AssertionError("unbounded inventory enumeration")
                return SimpleNamespace(name="unexpected",is_dir=lambda:False,is_symlink=lambda:False)
        with patch.object(component.os,"scandir",return_value=UnknownEntries()):
            with self.assertRaises(component.ComponentRecipeError): self.verify()
        self.assertEqual(len(consumed),1)

    def test_windows_cross_api_ctime_differs_but_fd_ctime_must_remain_stable(self):
        original=os.stat(self.index_path)
        def shape(ctime):
            data={key:getattr(original,key) for key in ("st_dev","st_ino","st_mode","st_nlink","st_size",
                "st_mtime_ns","st_blocks")}
            return SimpleNamespace(**data,st_ctime_ns=ctime,st_birthtime_ns=123)
        effects={name:getattr(os,name) for name in ("open","fdopen","close","O_RDONLY","O_NONBLOCK","O_NOFOLLOW","O_CLOEXEC")}
        for drift in (False,True):
            count=[0]
            def fstat(fd):
                count[0]+=1
                return shape(456+(1 if drift and count[0]>1 else 0))
            fake=SimpleNamespace(**effects,name="nt",fstat=fstat)
            with self.subTest(drift=drift),patch.object(component,"os",fake),\
                    patch.object(Path,"lstat",return_value=shape(123)):
                if drift:
                    with self.assertRaisesRegex(component.ComponentRecipeError,"drift"):
                        component._retention_read_v1(self.index_path,12288)
                else:
                    self.assertEqual(component._retention_read_v1(self.index_path,12288)[0],self.index_raw)


class CurrentCodeFormsTests(unittest.TestCase):
    def setUp(self):
        NativeRetentionTests.setUp(self)
        self.bindings=component.retained_source_bindings_v1(self.repo)
        self.code={}
        for number,row in enumerate(self.bindings["sources"][:11]):
            path=self.repo/row["path"]
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(self.raws[number])
            descriptor={key:row[key] for key in ("size_bytes","sha256","git_blob")}
            if number<10: self.code[row["path"]]=descriptor
            else: self.plan=descriptor

    def quote(self):
        return component.current_code_forms_quote_v1(self.repo,code=self.code,plan=self.plan)

    def changed(self,raw):
        path=self.repo/self.bindings["sources"][0]["path"]
        path.write_bytes(raw)
        self.code[self.bindings["sources"][0]["path"]]={"size_bytes":len(raw),
            "sha256":hashlib.sha256(raw).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
        return path

    def test_unchanged_aliases_and_changed_full_working_plus_git_forms(self):
        self.assertEqual(component.CURRENT_CODE_FORMS_V1,524288)
        self.assertEqual(self.quote(),0)
        path=self.changed(b"changed source\n"*700)
        rounded=((path.stat().st_size+4095)//4096)*4096
        self.assertEqual(self.quote(),max(path.stat().st_blocks*512,rounded)+4096+rounded+4096)
        path.write_bytes(b"drift")
        with self.assertRaises(component.ComponentRecipeError): self.quote()

    def test_exact_keys_typed_descriptors_and_unknown_or_excess_native_allocation_refuse(self):
        name=next(iter(self.code)); original=dict(self.code[name])
        for key,value in (("size_bytes",float(original["size_bytes"])),("size_bytes",True),
                          ("sha256","0"*64),("git_blob","0"*40)):
            with self.subTest(key=key,value=value):
                self.code[name]=dict(original,**{key:value})
                with self.assertRaises(component.ComponentRecipeError): self.quote()
        self.code[name]=original
        for changed in ({**self.code,"unknown":original},{k:v for k,v in self.code.items() if k!=name}):
            with patch.object(self,"code",changed),self.assertRaises(component.ComponentRecipeError): self.quote()
        with patch.object(self,"plan",dict(self.plan,path="unknown")),self.assertRaises(component.ComponentRecipeError):
            self.quote()
        self.changed(b"changed")
        for blocks in (None,True,2**20):
            with self.subTest(blocks=blocks),patch.object(component,"_retention_blocks_v1",return_value=blocks),\
                    self.assertRaises(component.ComponentRecipeError): self.quote()

    def test_windows_missing_block_field_uses_rounding_without_claiming_native_blocks(self):
        path=self.changed(b"changed")
        fake=SimpleNamespace(**{name:getattr(os,name) for name in (
            "open","fdopen","close","fstat","O_RDONLY","O_NONBLOCK","O_NOFOLLOW","O_CLOEXEC")},name="nt")
        with patch.object(component,"os",fake),patch.object(component,"_retention_blocks_v1",return_value=None):
            self.assertEqual(self.quote(),16384)

    def test_unchanged_byte_identity_cannot_alias_unbounded_working_allocation(self):
        self.assertEqual(self.quote(),0)
        with patch.object(component,"_retention_blocks_v1",return_value=2**20):
            with self.assertRaises(component.ComponentRecipeError): self.quote()
