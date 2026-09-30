"""Artifact-only decoder research: bounded physical evidence and original AU protocol.

This module has no GI import, decoder, model, guardian or publication authority.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import stat
import struct
import threading
import time

HEADER = struct.Struct('>8sHHQQQQQQIIIQ')
MISSING = (1 << 64) - 1
PAYLOAD_MAX = 64 * 1024 * 1024
RAW_MAX = 128 * 1024 * 1024
RUN_MAX = 256 * 1024 * 1024
METADATA_MAX = 32 * 1024 * 1024
CHANNEL_MAX = 1024 * 1024
EVENT_MAX = 16384
EVENT_COUNT = 512
CADENCE_MIN = 999999600
COUNT = 32
EVENT_FIELDS = frozenset(('protocol_version', 'source_process_id', 'sequence', 'run_id',
    'dataset_id', 'stream_id', 'admission_id', 'input_frame_key', 'source_sha256',
    'source_cycle', 'access_unit_pts_ns', 'payload_sha256', 'payload_size_bytes',
    'schedule_offset_ns', 'admission_timestamp_ms', 'event_provenance'))


class ResearchError(RuntimeError):
    pass


def require(test, message):
    if not test:
        raise ResearchError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode('ascii')


def strict_object(raw, maximum=EVENT_MAX):
    require(len(raw) <= maximum, 'JSON record exceeds cap')
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ResearchError('nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise ResearchError('invalid JSON') from exc
    require(type(value) is dict, 'JSON object required')
    return value


def seal(value):
    require('sha256' not in value, 'already sealed')
    return dict(value, sha256=hashlib.sha256(canonical(value)).hexdigest())


def verify_seal(value):
    copied = dict(value)
    digest = copied.pop('sha256', None)
    require(digest == hashlib.sha256(canonical(copied)).hexdigest(), 'self seal mismatch')
    return value


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns]


def _pin_stat(info):
    if info is None:
        return None
    kind = next((name for name, check in (('regular', stat.S_ISREG), ('directory', stat.S_ISDIR),
        ('symlink', stat.S_ISLNK), ('fifo', stat.S_ISFIFO), ('socket', stat.S_ISSOCK),
        ('character_device', stat.S_ISCHR), ('block_device', stat.S_ISBLK)) if check(info.st_mode)), 'other')
    return {'epoch': epoch(info), 'mode': info.st_mode, 'type': kind,
        'nlink': info.st_nlink, 'size_bytes': info.st_size}


class Pin:
    """Keep the actual file and every resolved ancestor's identity until close."""
    def __init__(self, path, expected=None, maximum=2 * 1024 * 1024 * 1024, deadline=None):
        self.deadline = deadline
        self.path = None
        self.fd = None
        self.directories = []
        info = None
        stage = 'resolve'
        try:
            self.path = Path(path).resolve(strict=True)
            stage = 'open'
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            stage = 'ancestors'
            for parent in reversed(self.path.parents):
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                ancestor_info = os.fstat(fd)
                self.directories.append((parent, fd, (ancestor_info.st_dev, ancestor_info.st_ino, ancestor_info.st_mode)))
            stage = 'fstat_predicate'
            info = os.fstat(self.fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum,
                'pin is not a bounded single-link regular file')
            self.initial_epoch = epoch(info)
            stage = 'digest_and_descriptor'
            self.descriptor = {'path': str(self.path), 'size_bytes': info.st_size,
                'sha256': self.digest()}
            if expected is not None:
                stage = 'expected_descriptor'
                require(self.descriptor['size_bytes'] == expected['size_bytes'] and
                    self.descriptor['sha256'] == expected['sha256'], 'physical input descriptor mismatch')
            stage = 'verify'
            self.verify()
        except BaseException as exc:
            # Preserve the original rejection and its pre-predicate stat before closing this fd.
            try:
                facts = {'requested_path': os.fspath(path),
                    'resolved_path': None if self.path is None else str(self.path), 'pin_stage': stage,
                    'maximum_size_bytes': maximum, 'fstat': _pin_stat(info),
                    'observed_at_ns': time.time_ns(), 'unavailable': {},
                    'predicate_results': None if info is None else {'regular_file': stat.S_ISREG(info.st_mode),
                        'single_link': info.st_nlink == 1, 'within_size_cap': info.st_size <= maximum}}
                for name, observe in (('failure_fstat', lambda: os.fstat(self.fd)),
                        ('requested_lstat', lambda: Path(path).lstat()),
                        ('resolved_lstat', lambda: self.path.lstat())):
                    try:
                        facts[name] = _pin_stat(observe())
                    except BaseException as unavailable:
                        facts[name] = None
                        facts['unavailable'][name] = type(unavailable).__name__ + ': ' + str(unavailable)
                exc.pin_rejection = facts
            except BaseException as metadata_error:
                exc.add_note('original Pin rejection metadata unavailable: ' + str(metadata_error))
            try:
                self.close()
            except BaseException as close_error:
                exc.add_note('original rejected Pin close: ' + str(close_error))
            raise

    def digest(self):
        digest = hashlib.sha256()
        offset = 0
        while block := os.pread(self.fd, 1024 * 1024, offset):
            require(self.deadline is None or time.monotonic() < self.deadline, 'physical hash deadline exceeded')
            digest.update(block)
            offset += len(block)
        return digest.hexdigest()

    def verify(self, rehash=False):
        require(epoch(os.fstat(self.fd)) == self.initial_epoch == epoch(self.path.lstat()),
            'held input changed')
        for path, fd, identity in self.directories:
            for info in (os.fstat(fd), path.lstat()):
                require((info.st_dev, info.st_ino, info.st_mode) == identity, 'held ancestor changed')
        if rehash:
            require(self.digest() == self.descriptor['sha256'], 'held bytes changed')

    def close(self):
        if getattr(self, 'fd', None) is not None:
            os.close(self.fd)
            self.fd = None
        for _, fd, _ in getattr(self, 'directories', []):
            os.close(fd)
        self.directories = []


def physical_descriptor(path):
    pin = Pin(path)
    try:
        return pin.descriptor
    finally:
        pin.close()


def owner(pid):
    suffix = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    fields = dict((row.split(':', 1)[0], row.split()[1:])
        for row in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in row)
    return {'pid': pid, 'ppid': int(suffix[1]), 'starttime_ticks': int(suffix[19]),
        'uid': int(fields['Uid'][0]), 'gid': int(fields['Gid'][0]),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


class Evidence:
    """Exclusive namespace, byte reservations before writes, failure receipt capacity."""
    def __init__(self, directory, maximum=RUN_MAX):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700)
        self.maximum = maximum
        self.total = 0
        self.count = 0
        self.lock = threading.RLock()
        self.files = {}
        self.streams = {}
        self.events = self.open('events.jsonl', EVENT_COUNT * EVENT_MAX)

    def open(self, name, maximum):
        require('/' not in name and name not in self.files, 'output name already owned or invalid')
        fd = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.files[name] = [0, maximum]
        self.streams[name] = fd
        return name

    def append(self, name, raw, final=False, sync=False):
        with self.lock:
            count, limit = self.files[name]
            require(count + len(raw) <= limit, 'channel/file byte cap exceeded')
            require(self.total + len(raw) <= self.maximum - (0 if final else 2 * EVENT_MAX),
                'namespace byte cap exceeded')
            # Reserve first. A failed partial write can never be accepted or silently reused.
            self.files[name][0] += len(raw)
            self.total += len(raw)
            view = memoryview(raw)
            while view:
                size = os.write(self.streams[name], view)
                require(size > 0, 'output write made no progress')
                view = view[size:]
            if sync:
                os.fsync(self.streams[name])

    def event(self, kind, observed_ns=None, **facts):
        with self.lock:
            require(self.count < EVENT_COUNT - 1, 'event count cap exceeded')
            value = {'event_seq': self.count + 1, 'kind': kind,
                'observed_monotonic_ns': time.monotonic_ns() if observed_ns is None else observed_ns, **facts}
            raw = canonical(value) + b'\n'
            require(len(raw) <= EVENT_MAX, 'event byte cap exceeded')
            self.append(self.events, raw, sync=True)
            self.count += 1
            return value

    def document(self, name, value, final=False):
        raw = canonical(seal(value)) + b'\n'
        self.open(name, EVENT_MAX if final else METADATA_MAX)
        self.append(name, raw, final=final, sync=True)
        return physical_descriptor(self.directory / name)

    def close(self):
        errors = []
        for name, fd in list(self.streams.items()):
            try:
                os.fsync(fd)
            except OSError as exc:
                errors.append(str(exc))
            finally:
                os.close(fd)
                self.streams.pop(name)
        require(not errors, 'evidence close failure: ' + '; '.join(errors))


def post_receipt_deadline(evidence, receipt, started, deadline, phase, cleanup_deadline=None):
    """A late immutable final append fails this attempt and cannot enable the next run."""
    observed = time.monotonic()  # Called immediately after the final streams close.
    late = observed > deadline or (cleanup_deadline is not None and observed > cleanup_deadline)
    if not late:
        return True, None
    try:
        failure = evidence.document('receipt-time-limit-failure.v1.json', {
            'artifact_kind': 'vast_decoder_research_time_limit_failure_v1', 'phase': phase,
            'provisional_terminal': receipt, 'observed_after_final_close_monotonic_s': observed,
            'elapsed_after_final_close_s': observed-started, 'deadline_monotonic_s': deadline,
            'cleanup_deadline_monotonic_s': cleanup_deadline, 'failed': True,
            'original_execution_completed': False, 'accepted': False, 'publication_ready': False,
            'benchmark_arm_count': 0, 'native_pair_count': 0, 'qualification_count': 0}, final=True)
    finally:
        evidence.close()
    return False, failure


def read_exact(fd, size, deadline, aborted, clean_eof=False, capture=None, capacity=None):
    require(capacity is None or capacity() >= size, 'raw capture capacity before read/allocation')
    result = bytearray(size)
    offset = 0
    while offset < size:
        require(not aborted.is_set() and time.monotonic() < deadline, 'pipe deadline/abort')
        if not select.select([fd], [], [], min(0.1, max(0, deadline - time.monotonic())))[0]:
            continue
        block = os.read(fd, min(size - offset, 65536))
        if block and capture is not None:
            capture(block)  # Retain each actually consumed bounded block, including failed prefixes.
        if not block and offset == 0 and clean_eof:
            return None
        require(bool(block), 'truncated binary frame')
        result[offset:offset + len(block)] = block
        offset += len(block)
    return result


class LineReader:
    """Bounded read-ahead; retain consumed raw bytes even when a line truncates."""
    def __init__(self,fd,deadline,aborted,capture,maximum=EVENT_MAX,capacity=None):
        self.fd,self.deadline,self.aborted,self.capture,self.maximum=fd,deadline,aborted,capture,maximum
        self.capacity=capacity
        self.pending=bytearray()

    def read(self):
        while b'\n' not in self.pending:
            require(len(self.pending)<self.maximum,'source line cap exceeded before read')
            require(not self.aborted.is_set() and time.monotonic()<self.deadline,'source line deadline/abort')
            if not select.select([self.fd],[],[],0.1)[0]:
                continue
            available=self.maximum-len(self.pending) if self.capacity is None else min(
                self.maximum-len(self.pending),self.capacity())
            require(available>0,'raw line channel cap before read')
            block=os.read(self.fd,min(4096,available))
            if not block:
                require(not self.pending,'truncated source line')
                return None
            self.capture(block)
            self.pending.extend(block)
        end=self.pending.index(b'\n')+1
        line=bytes(self.pending[:end]);del self.pending[:end]
        return line


def read_line(fd, deadline, aborted, maximum=EVENT_MAX):
    result = bytearray()
    while True:
        block = read_exact(fd, 1, deadline, aborted, clean_eof=True)
        if block is None:
            require(not result, 'truncated source line')
            return None
        result += block
        require(len(result) <= maximum, 'source line cap exceeded')
        if block == b'\n':
            return bytes(result)


def u64(value, label):
    require(type(value) is int and 0 <= value <= MISSING, 'invalid unsigned ' + label)
    return value


class AdmissionGate:
    """Declaration n before ACKn; actual packet n before either push or ACK(n+1)."""
    def __init__(self, contract):
        self.contract = contract
        self.declared = {}
        self.validated = {}
        self.reserved_raw_bytes = 0
        self.condition = threading.Condition()
        self.failed = None

    def fail(self, exc):
        with self.condition:
            self.failed = str(exc)
            self.condition.notify_all()

    def declare(self, event, deadline, aborted):
        require(set(event) == EVENT_FIELDS, 'source event exact fields differ')
        for field in ('sequence', 'stream_id', 'source_cycle', 'access_unit_pts_ns',
                'payload_size_bytes', 'schedule_offset_ns', 'admission_timestamp_ms'):
            u64(event[field], field)
        seq = event['sequence']
        with self.condition:
            require(self.failed is None, 'earlier admission failure')
            require(seq == len(self.declared) + 1 and seq <= COUNT, 'actual admission count/sequence differs')
            c = self.contract
            expected = {'protocol_version': 1, 'source_process_id': c['source_process_id'],
                'run_id': c['run_id'], 'dataset_id': c['dataset_id'], 'stream_id': c['stream_id'],
                'source_sha256': c['source_sha256'], 'source_cycle': 0,
                'admission_id': f"{c['run_id']}:{c['stream_id']}:admission:{seq}",
                'input_frame_key': f"{c['dataset_id']}:{c['stream_id']}:{c['source_sha256']}:0:{event['access_unit_pts_ns']}",
                'event_provenance': 'native_common_source_coordinator'}
            for field, value in expected.items():
                require(type(event[field]) is type(value) and event[field] == value, 'source event identity differs: ' + field)
            require(c['window_start_ms'] <= event['admission_timestamp_ms'] < c['window_end_ms'],
                'actual admission outside reviewed source window')
            digest = event['payload_sha256']
            require(type(digest) is str and len(digest) == 64 and all(x in '0123456789abcdef' for x in digest),
                'source declaration SHA invalid')
            text = [event[field].encode('utf8') for field in ('admission_id', 'input_frame_key', 'payload_sha256')]
            require(all(0 < len(raw) <= 8192 for raw in text), 'declared text lengths exceed protocol')
            size = event['payload_size_bytes']
            require(0 < size <= PAYLOAD_MAX, 'declared payload exceeds protocol')
            reservation = HEADER.size + sum(map(len, text)) + size
            require(self.reserved_raw_bytes + reservation <= RAW_MAX-HEADER.size,
                'raw aggregate cap exceeded before ACK (reserve failed next header)')
            if seq == 1:
                require(event['schedule_offset_ns'] == 0, 'first source schedule origin differs')
            else:
                # The next declaration can legally arrive while the previous sender is still writing.
                while seq - 1 not in self.validated:
                    require(self.failed is None and not aborted.is_set() and time.monotonic() < deadline,
                        'previous packet validation deadline/abort')
                    self.condition.wait(0.1)
                previous = self.validated[seq - 1]
                expected_offset = self.declared[seq - 1]['schedule_offset_ns'] + previous['duration_ns']
                require(event['schedule_offset_ns'] == expected_offset and
                    event['schedule_offset_ns'] - self.declared[seq - 1]['schedule_offset_ns'] >= CADENCE_MIN,
                    'actual duration/schedule cadence differs')
            self.reserved_raw_bytes += reservation
            self.declared[seq] = dict(event)
            self.condition.notify_all()
        return event

    def receive(self, fd, deadline, aborted, evidence, raw_name):
        capture=lambda block:evidence.append(raw_name,block)
        capacity=lambda:evidence.files[raw_name][1]-evidence.files[raw_name][0]
        header = read_exact(fd, HEADER.size, deadline, aborted, clean_eof=True,capture=capture,capacity=capacity)
        if header is None:
            return None
        values = HEADER.unpack(header)
        magic, version, flags, seq, cycle, aupts, pts, dts, duration, a, k, h, size = values
        require(magic == b'VASTAU01' and version == 1 and flags & ~1 == 0, 'binary magic/version/flags differ')
        require(0 < a <= 8192 and 0 < k <= 8192 and h == 64 and 0 < size <= PAYLOAD_MAX,
            'binary lengths rejected before allocation')
        require(1 <= seq <= COUNT and seq == len(self.validated) + 1, 'binary sequence differs')
        with self.condition:
            require(self.failed is None and seq in self.declared, 'binary lacks enabling validated declaration')
            declared = self.declared[seq]
        texts = [declared[f].encode('utf8') for f in ('admission_id', 'input_frame_key', 'payload_sha256')]
        require([a, k, h] == list(map(len, texts)) and size == declared['payload_size_bytes'],
            'actual packet lengths differ from reserved declaration')
        require(cycle == declared['source_cycle'] == 0 and aupts == declared['access_unit_pts_ns'],
            'binary source/cycle/PTS identity differs')
        require(pts == cycle * self.contract['source_duration_ns'] + aupts * 600,
            'actual transport PTS differs from original600scale')
        require(duration >= CADENCE_MIN and duration != MISSING, 'unsupported source duration cadence')
        for length, expected in zip((a, k, h), texts):
            raw = read_exact(fd, length, deadline, aborted,capture=capture,capacity=capacity)
            require(bytes(raw) == expected, 'binary text identity differs')
        payload = bytearray(size)  # All payload/aggregate/actual header checks already passed.
        sha = hashlib.sha256()
        offset = 0
        while offset < size:
            block = read_exact(fd, min(65536, size - offset), deadline, aborted,capture=capture,capacity=capacity)
            payload[offset:offset + len(block)] = block
            sha.update(block)
            offset += len(block)
        require(sha.hexdigest() == declared['payload_sha256'], 'actual full AU payload digest differs')
        packet = {'sequence': seq, 'source_cycle': cycle, 'access_unit_pts_ns': aupts,
            'transport_pts_ns': pts, 'access_unit_dts_ns': dts, 'duration_ns': duration,
            'keyframe': bool(flags & 1), 'payload_size_bytes': size,
            'payload_sha256': sha.hexdigest(), 'payload': payload}
        return packet

    def mark_validated(self, packet):
        with self.condition:
            require(self.failed is None and packet['sequence'] == len(self.validated) + 1,
                'validated packet order differs')
            self.validated[packet['sequence']] = {k: v for k, v in packet.items() if k != 'payload'}
            self.condition.notify_all()


def active_rgb_digest(data, width, height, stride, offset):
    require(all(type(x) is int for x in (width, height, stride, offset)), 'RGB layout types')
    require(width > 0 and height > 0 and stride >= width * 3 and offset >= 0, 'RGB active layout invalid')
    require(len(data) <= PAYLOAD_MAX and offset + (height - 1) * stride + width * 3 <= len(data),
        'RGB map/layout cap or range exceeded')
    digest = hashlib.sha256()
    view = memoryview(data)
    for row in range(height):
        start = offset + row * stride
        digest.update(view[start:start + width * 3])
    return digest.hexdigest()


def compare_outputs(first, second, expected_pts):
    require(len(expected_pts) == COUNT and len(set(expected_pts)) == COUNT, 'input PTS multiplicity differs')
    for rows in (first, second):
        require(len(rows) == COUNT and sorted(row['pts'] for row in rows) == sorted(expected_pts),
            'output complete PTS multiset differs')
    require([row['pts'] for row in first] == [row['pts'] for row in second], 'paired presentation order differs')
    for left, right in zip(first, second):
        for field in ('pts', 'width', 'height', 'format', 'caps', 'caps_features', 'pixel_sha256'):
            require(left[field] == right[field], 'paired output correctness differs: ' + field)
    return True


def decoder_timings(entries, exits, packets, actual_sink_eos):
    require(len(packets) == COUNT and len(actual_sink_eos) == 1, 'exact packet cohort/actual sink EOS absent')
    eos = actual_sink_eos[0]
    require(type(eos) is int and eos > 0, 'actual sink EOS clock invalid')
    result = []
    for seq in range(1, COUNT + 1):
        packet = packets[seq - 1]
        require(packet['sequence'] == seq, 'timing cohort original sequence differs')
        pts = packet['transport_pts_ns']
        require(pts in entries and pts in exits and exits[pts] >= entries[pts], 'decoder timing join/order invalid')
        result.append({'original_sequence': seq, 'pts': pts, 'decoder_sink_ns': entries[pts],
            'decoder_src_ns': exits[pts], 'residence_ns': exits[pts]-entries[pts],
            'cohort': 'startup' if seq <= 8 else 'central' if seq <= 24 else 'tail',
            'after_actual_decoder_sink_eos': exits[pts] >= eos})
    return result
