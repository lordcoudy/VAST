"""Read closed original bind leaves and /proc twice; never invoke Docker."""
from pathlib import Path
import hashlib, json, os, stat, time

SOURCE = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/benchmark_recovery_20260930/component-ext4-bind-original-v1')
OUTPUT = Path(__file__).parent/'review.v1.json'
EXPECTED = '530adaaf31da050891005aa956e05241af44abca55444567d1b553707229c32d'
IMAGE = 'sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
CID = '4e14a7d73811531299937ee4a1929968b4a445dc5b774b0b5bdf13fc724762f1'
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
START = time.monotonic()
held, witnesses = [], []

def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def read(path, maximum=1048576):
    assert time.monotonic()-START < 20
    assert path.resolve(strict=True) == path
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum
        before = epoch(info)
        raw = os.read(fd, maximum+1)
        assert len(raw) == info.st_size and before == epoch(os.fstat(fd)) == epoch(path.lstat())
        row = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch': before}
        held.append((fd, path, row))
        return raw, row
    except BaseException:
        os.close(fd)
        raise

def scan(pids, groups):
    rows = []
    entries = list(Path('/proc').iterdir())
    assert len(entries) < 8192
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            values = (entry/'stat').read_text().rsplit(')', 1)[1].split()
        except FileNotFoundError:
            continue
        pid, ppid, pgid, session = int(entry.name), int(values[1]), int(values[2]), int(values[3])
        if pid in pids or ppid in pids or pgid in groups or session in groups:
            rows.append({'pid':pid,'ppid':ppid,'pgid':pgid,'session':session,'startticks':int(values[19])})
    return {'wall_time_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),
            'original_named_pids_absent':all(not Path('/proc',str(pid)).exists() for pid in pids),
            'matching_members':rows}

try:
    assert not OUTPUT.exists()
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    raw, execution_ref = read(SOURCE/'execution.v1.json')
    assert len(raw) == 18399 and execution_ref['sha256'] == EXPECTED
    execution = json.loads(raw)
    assert execution['status'] == 'passed' and execution['primary_error'] is None and execution['cleanup_errors'] == []
    assert execution['all_held_fds_released'] is True and execution['container_id'] == CID
    assert execution['container_removed_without_force'] is True and execution['elapsed_s'] < 30
    dispatch_raw, dispatch_ref = read(SOURCE/'dispatch.v1.json')
    dispatch = json.loads(dispatch_raw)
    assert dispatch['owner']['pid'] == 41539 and dispatch['owner']['pgid'] == 41538
    assert dispatch['owner']['boot_id'] == BOOT and dispatch['image'] == IMAGE
    assert dispatch['inputs_before'] == execution['inputs_after']
    name = dispatch['container_name']
    label = dispatch['owner_label']
    raw_by_command = []
    pids, groups = {41538,41539}, {41538}
    expected_names = {'execution.v1.json','dispatch.v1.json','positive-original-container.v1.json'}
    for ordinal, command in enumerate(execution['commands']):
        assert command['owner']['boot_id'] == BOOT and command['owner']['ppid'] == 41539
        assert command['owner']['uid'] == command['owner']['gid'] == 1000
        assert command['failure'] is None and command['cleanup_errors'] == [] and command['signals'] == []
        assert command['both_eof'] and command['original_pid_absent'] and command['original_group_absent']
        pids.add(command['original_pid']);groups.add(command['owner']['pgid'])
        channels = {}
        for channel, descriptor in command['channels'].items():
            data, physical = read(Path(descriptor['path']), 65536)
            assert all(physical[key] == descriptor[key] for key in ('path','size_bytes','sha256'))
            assert len(data) == command['captured_bytes_counter'][channel]
            channels[channel] = data
            expected_names.add(Path(descriptor['path']).name)
        for kind in ('launch','terminal'):
            leaf = 'command%02d.%s.v1.json' % (ordinal,kind)
            data, _ = read(SOURCE/leaf)
            value = json.loads(data)
            assert value['argv'] == command['argv'] and value['owner'] == command['owner']
            if kind == 'terminal':
                assert value == command
            expected_names.add(leaf)
        raw_by_command.append(channels)
    assert len(execution['commands']) == 10
    assert raw_by_command[0]['stdout'] == (dispatch['source_commit']+'\n').encode()
    assert raw_by_command[2]['stdout'] == (IMAGE+'\n').encode()
    assert raw_by_command[3]['stdout'] == (CID+'\n').encode()
    assert raw_by_command[7]['stdout'] == (CID+'\n').encode() and execution['commands'][7]['argv'][-3:] == ['container','rm',CID]
    for ordinal, identifier in ((1,name),(8,CID),(9,name)):
        command = execution['commands'][ordinal]
        assert command['returncode'] == 1 and command['argv'][-3:] == ['container','inspect',identifier]
        assert raw_by_command[ordinal]['stdout'] == b'[]\n'
        assert raw_by_command[ordinal]['stderr'] == ('Error response from daemon: No such container: '+identifier+'\n').encode()
    expected_payload = {'sha256':'61874c718d6140d0d5cf745988bc301b916077af8f80e96742184f80a0805db7','size_bytes':7049}
    assert json.loads(raw_by_command[5]['stdout']) == expected_payload
    container = json.loads(raw_by_command[6]['stdout'])[0]
    assert container['Id'] == CID and container['Image'] == IMAGE and container['Name'] == '/'+name
    assert all(container['Config']['Labels'][key] == value for key,value in label.items())
    state = container['State']
    assert state['Running'] is False and state['Pid'] == 0 and state['ExitCode'] == 0 and state['OOMKilled'] is False
    assert container['Config']['User'] == '1000:1000' and container['HostConfig']['ReadonlyRootfs'] is True
    mounts = [row for row in container['Mounts'] if row['Destination'] == '/vast-root']
    assert len(mounts) == 1 and mounts[0]['Source'] == str(SOURCE.parents[2]) and mounts[0]['RW'] is False
    positive_raw, positive_ref = read(SOURCE/'positive-original-container.v1.json')
    positive = json.loads(positive_raw)
    assert positive['container'] == container and positive['probe_payload'] == expected_payload
    assert {p.name for p in SOURCE.iterdir()} == expected_names
    current_inputs = []
    for row in execution['inputs_after']:
        path = Path(row['path'])
        assert row['epoch'] == epoch(path.lstat())
        if path == Path('/usr/bin/docker'):
            current_inputs.append({'path':str(path),'current_epoch_equal':True,'raw_rehash_by_reviewer':False})
        else:
            _, physical = read(path)
            assert physical['sha256'] == row['sha256'] and physical['size_bytes'] == row['size_bytes']
            current_inputs.append({'path':str(path),'current_epoch_equal':True,'raw_rehash_by_reviewer':True})
    socket = Path('/run/docker.sock').lstat()
    assert epoch(socket)[:4] == dispatch['socket_before']
    assert {'uid':socket.st_uid,'gid':socket.st_gid} == dispatch['socket_owner_before']
    scans = [scan(pids,groups)]
    time.sleep(.1)
    scans.append(scan(pids,groups))
    assert all(row['original_named_pids_absent'] and not row['matching_members'] for row in scans)
    for fd,path,row in held:
        assert row['epoch'] == epoch(os.fstat(fd)) == epoch(path.lstat())
        os.lseek(fd,0,os.SEEK_SET)
        assert hashlib.sha256(os.read(fd,row['size_bytes']+1)).hexdigest() == row['sha256']
    witnesses = [row for _,_,row in held]
finally:
    for fd,_,_ in held:
        os.close(fd)

report = {'schema_version':1,'artifact_kind':'vast_original_ext4_bind_actual_independent_review_v1',
          'disposition':'passed_bind_reachability_and_original_owned_cleanup_only','source_commit':dispatch['source_commit'],
          'original_execution':execution_ref,'original_dispatch':dispatch_ref,'original_positive_container':positive_ref,
          'container_id':CID,'actual_image':IMAGE,'actual_terminal_state':state,'actual_readonly_mount':mounts[0],
          'actual_user':'1000:1000','returned_original_receipt':expected_payload,'original_elapsed_s':execution['elapsed_s'],
          'nonforce_removal_and_both_original_absence_verified':True,'command_count':10,'closed_namespace_leaf_count':len(expected_names),
          'original_named_pids':sorted(pids),'original_groups':sorted(groups),'two_actual_process_scans':scans,
          'original_reported_FD_release':True,'reviewer_FDs_released':True,'current_input_metadata':current_inputs,
          'held_original_small_leaf_witnesses':witnesses,'reviewer_owner':{'pid':os.getpid(),'uid':os.getuid(),'gid':os.getgid(),'boot_id':BOOT},
          'elapsed_s':time.monotonic()-START,'engine_queries_or_mutations_by_reviewer':False,
          'model_native_gpu_or_benchmark_acceptance':False,'new_host_closure_verified':False,'publication_ready':False,
          'limits':['Only retained original commands prove container state/removal/absence; no fresh daemon query.',
                    'Current Docker file epoch was compared; its45MB raw bytes were not rehashed by reviewer.',
                    'Actual new stock host closure and fresh benchmark remain separate gates.']}
raw = (json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
assert len(raw) < 1048576 and time.monotonic()-START < 20
with OUTPUT.open('xb') as stream:
    stream.write(raw);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'path':str(OUTPUT),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'elapsed_s':time.monotonic()-START}))
