"""Single original container owner for the reviewed, nonpromoting decoder experiment.

Creating an output namespace consumes that attempt. No resume/retry/replacement path.
The code is artifact-only; it must be reviewed before its first execution.
"""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import select
import stat
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_protocol import (CHANNEL_MAX, Evidence, METADATA_MAX, Pin, ResearchError,
    canonical, epoch, owner, physical_descriptor, post_receipt_deadline, require, strict_object, verify_seal)

PLANNING_COMMIT = 'a84e0e734678aa9ecc9e0a4f16dcc3036c5c8f02'
IMAGE_ID = 'sha256:70696f057232acd382f60beaaf12cd9279b317b0ba9a7ade29f0b955ce90481a'
DAEMON_ID = 'aa8f3d33-e1dc-4ed2-ad06-488b46b332d0'
ENGINE_SHA = 'a429e235ef670ea83357a5c8c7451f0a69d485a6fee49f9032fd938a0ab4969d'
FIXED_ORDER = [['front_gate','default'], ['front_gate','zero'], ['underbody','zero'], ['underbody','default']]


class Controller:
    def __init__(self, root, destination):
        self.root = Path(root).resolve(strict=True)
        self.destination = Path(destination).absolute()
        self.destination.parent.resolve(strict=True)
        require(not self.destination.exists() and self.destination.parent.resolve().is_relative_to(
            self.root / 'artifacts/benchmark_recovery_20260930'), 'output must be a new owned recovery namespace')
        self.destination.mkdir(mode=0o700)
        self.evidence = Evidence(self.destination / 'controller', METADATA_MAX // 2 - 128)
        (self.destination / 'guest').mkdir(mode=0o700)
        self.start = time.monotonic()
        self.deadline = self.start + 600
        self.phase_deadline = self.start + 120
        self.abort = threading.Event()
        self.errors = []
        self.pins = []
        self.process = None
        self.child = None
        self.sequence = 0
        self.container_id = None
        self.cid_fd = None
        self.cid_identity = None
        self.cid_pin = None
        self.cid_ownership_observed = False
        self.cid_last_observation = None
        self.cid_observation_count = 0
        self.cleanup_deadline = None
        self.in_cleanup = False
        self.name = 'vast-decoder-research-' + uuid.uuid4().hex
        self.reserved_at = time.time_ns()
        self.label = hashlib.sha256((PLANNING_COMMIT + IMAGE_ID + self.name).encode()).hexdigest()
        self.cidfile = self.destination / 'controller' / 'original.cid'
        self.socket_path = Path('/run/docker.sock').resolve(strict=True)
        self.socket_fd = os.open(self.socket_path, os.O_PATH | os.O_NOFOLLOW)
        self.socket_before = os.fstat(self.socket_fd)
        require(stat.S_ISSOCK(self.socket_before.st_mode), 'engine socket not actual socket')
        self.environment = {'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C',
            'DOCKER_HOST':'unix://' + str(self.socket_path)}
        self.engine = self.pin('/usr/bin/docker')
        require(self.engine.descriptor['sha256'] == ENGINE_SHA, 'pinned original engine changed')
        sys.path.insert(0, str(self.root / 'scripts'))
        from publication_operational_container_custody_v1 import _confirmed_absent, _state, _successful_terminal, PROJECTION, LABEL
        self.absent, self.state, self.projection, self.label_key = _confirmed_absent, _state, PROJECTION, LABEL
        self.successful_container_terminal=_successful_terminal
        self.pin(self.root/'scripts/publication_operational_container_custody_v1.py')
        self.daemon = None

    def pin(self, path, expected=None):
        pin = Pin(path, expected, deadline=self.phase_deadline)
        self.pins.append(pin)
        return pin

    def check_socket(self):
        before = self.socket_before
        identity = (before.st_dev,before.st_ino,before.st_mode,before.st_uid,before.st_gid)
        for current in (os.fstat(self.socket_fd), self.socket_path.lstat()):
            require((current.st_dev,current.st_ino,current.st_mode,current.st_uid,current.st_gid)==identity,
                'held engine/socket identity changed')
        self.engine.verify()

    def drain(self, stream, name, errors, maximum_deadline):
        try:
            while True:
                require(time.monotonic() < maximum_deadline, 'original pipe drain deadline')
                if not select.select([stream.fileno()], [], [], 0.1)[0]:
                    continue
                block=os.read(stream.fileno(),65536)
                if not block:
                    break
                self.evidence.append(name, block)
        except BaseException as exc:
            errors.append(str(exc)); self.abort.set()

    def command(self, arguments, timeout=10):
        self.check_socket()
        cleanup_deadline=getattr(self,'cleanup_deadline',None)  # The original clock also covers outer finalization.
        if cleanup_deadline is not None:
            timeout=min(timeout,cleanup_deadline-time.monotonic()-1.5)
            require(timeout>0,'original cleanup command reserve exhausted')
        self.sequence += 1
        prefix = f'engine-{self.sequence:02d}'
        stdout = self.evidence.open(prefix+'.stdout', 65536)
        stderr = self.evidence.open(prefix+'.stderr', 65536)
        errors = []
        began = time.monotonic()
        process = subprocess.Popen([str(self.engine.path), *arguments],
            executable=f'/proc/self/fd/{self.engine.fd}', pass_fds=(self.engine.fd,),
            env=self.environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)
        child = None
        threads = []
        timed_out = False
        try:
            child = owner(process.pid)
            for stream, name in ((process.stdout, stdout),(process.stderr,stderr)):
                drain_deadline=began+timeout+(0.5 if cleanup_deadline is not None else 2)
                thread=threading.Thread(target=self.drain,args=(stream,name,errors,drain_deadline),daemon=True)
                thread.start();threads.append(thread)
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL)
            try:
                process.wait(timeout=0.25)
            finally:
                # Drain real EOF before closing. A stuck descendant is an explicit failure.
                for thread in threads:thread.join(timeout=0.125)
                if any(t.is_alive() for t in threads):errors.append('original command pipes did not reach EOF')
                for stream in (process.stdout,process.stderr):stream.close()
        self.evidence.document(prefix+'.v1.json',{'artifact_kind':'vast_decoder_research_engine_observation_v1',
            'argv':[str(self.engine.path),*arguments],'child':child,'controller':owner(os.getpid()),
            'returncode':process.returncode,'timed_out':timed_out,'errors':errors,
            'started_realtime_ns':self.reserved_at if arguments[0]=='info' and self.sequence==1 else None,
            'observed_realtime_ns':time.time_ns(),'elapsed_s':time.monotonic()-began,
            'stdout':physical_descriptor(self.evidence.directory/(prefix+'.stdout')),
            'stderr':physical_descriptor(self.evidence.directory/(prefix+'.stderr')), 'accepted':False})
        require(not timed_out and not errors and all(not t.is_alive() for t in threads), 'engine observation failed')
        require(cleanup_deadline is None or time.monotonic()<cleanup_deadline-1,
            'original cleanup command exceeded final reserve')
        return process.returncode, (self.evidence.directory/(prefix+'.stdout')).read_bytes(), \
            (self.evidence.directory/(prefix+'.stderr')).read_bytes()

    def inspect_owned(self, timeout=10, identifier=None):
        identifier = identifier or self.container_id or self.name
        require(identifier in (self.container_id,self.name),'foreign original inspection identifier')
        rc,out,err = self.command(['container','inspect','--format',self.projection,identifier],timeout=timeout)
        if self.absent(rc,out,err,identifier):
            return None
        require(rc==0 and err==b'', 'owned container inspection unavailable')
        state=self.state(out,{'name':self.name,'label':self.label,
            'container_image':{'image_id':IMAGE_ID},'reserved_at_ns':self.reserved_at},identifier,time.time_ns())
        self.container_id=state['Id']
        return state

    def observe_cid(self):
        """Read the one original live CID inode; incomplete publication is pending."""
        try:
            named=self.cidfile.lstat()
        except FileNotFoundError:
            require(self.cid_fd is None,'original held CID path disappeared')
            if self.cid_last_observation!=('missing',):
                require(self.cid_observation_count<68,'original CID observation cap')
                self.evidence.event('original_cid_observation',path=str(self.cidfile),before=None,after=None,
                    named=None,current=None,owner_uid=None,owner_gid=None,partial_hex='',failure=None,missing=True)
                self.cid_last_observation=('missing',);self.cid_observation_count+=1
            return None
        raw=b''
        before=named
        after=named
        current=None
        failure=None
        try:
            require(stat.S_ISREG(named.st_mode) and named.st_nlink==1 and named.st_size<=65,
                'original CID size/inode')
            if self.cid_fd is None:
                self.cid_fd=os.open(self.cidfile,os.O_RDONLY|os.O_NOFOLLOW)
                held=os.fstat(self.cid_fd)
                self.cid_identity=(held.st_dev,held.st_ino,held.st_mode)
            before=os.fstat(self.cid_fd)
            identity=(named.st_dev,named.st_ino,named.st_mode)
            require(identity==self.cid_identity==(before.st_dev,before.st_ino,before.st_mode) and
                before.st_nlink==1 and before.st_size<=65,'original CID identity substitution')
            raw=os.pread(self.cid_fd,66,0)
            after=os.fstat(self.cid_fd)
            current=self.cidfile.lstat()
            require((current.st_dev,current.st_ino,current.st_mode)==self.cid_identity and
                after.st_nlink==current.st_nlink==1 and after.st_size<=65 and current.st_size<=65,
                'original CID identity substitution')
            require(len(raw)<=65 and all(value in b'0123456789abcdef' for value in raw[:64]) and
                (len(raw)<65 or raw[64:]==b'\n'),'original CID format')
            if epoch(before)!=epoch(after) or epoch(after)!=epoch(current) or len(raw)!=after.st_size:
                return None  # The original publisher is still changing this held file.
            if len(raw)<64:
                return None
            cid=raw[:64].decode('ascii')
            require(self.container_id is None or self.container_id==cid,'CID and original engine ownership differ')
            pin=self.cid_pin
            if pin is None:
                pin=self.pin(self.cidfile)
                self.cid_pin=pin
            pin.verify(rehash=True)
            require(pin.initial_epoch==epoch(after) and pin.descriptor['sha256']==hashlib.sha256(raw).hexdigest(),
                'original completed CID changed before physical binding')
            self.container_id=cid
            return cid
        except BaseException as exc:
            failure=str(exc)
            raise
        finally:
            facts={'path':str(self.cidfile),'before':epoch(before),'after':epoch(after),
                'named':epoch(named),'current':None if current is None else epoch(current),'owner_uid':after.st_uid,
                'owner_gid':after.st_gid,'partial_hex':raw.hex(),'failure':failure}
            signature=(before.st_dev,before.st_ino,before.st_mode,before.st_nlink,before.st_size,
                after.st_size,raw,failure)
            if signature!=self.cid_last_observation:
                require(self.cid_observation_count<68,'original CID observation cap')
                self.evidence.event('original_cid_observation',**facts)
                self.cid_observation_count+=1
                self.cid_last_observation=signature

    def cleanup_original(self, threads):
        begun=time.monotonic()
        self.cleanup_deadline=begun+15  # Includes reap, publication settle, commands, EOF and final facts.
        self.in_cleanup=True
        self.phase_deadline=min(self.deadline,self.cleanup_deadline-1)
        self.absent_after_rm=False
        self.final_state=None
        self.successful_original_state=False
        forced=False
        try:
            # A NotFound response before the original launcher ends is not final absence.
            if self.process.poll() is None:
                forced=True
                try:os.killpg(self.process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid,signal.SIGKILL)
                    self.process.wait(timeout=0.5)
                self.errors.append('original launcher required owned process-group termination')
            else:
                self.process.wait(timeout=0.5)
            self.evidence.event('original_launcher_terminal',returncode=self.process.returncode,
                forced_group_stop=forced,cleanup_elapsed_s=time.monotonic()-begun)
            settle_deadline=min(begun+5,self.cleanup_deadline-10)
            state=None
            while time.monotonic()<settle_deadline:
                try:self.observe_cid()  # Also runs after a fast natural CLI exit.
                except BaseException as exc:self.errors.append('original CID custody: '+str(exc))
                remaining=settle_deadline-time.monotonic()
                if remaining<=0.75:break  # Reserve bounded command teardown; no final tiny-timeout poll.
                try:state=self.inspect_owned(timeout=min(0.5,remaining-0.5))
                except BaseException as exc:
                    self.errors.append('original publication observation: '+str(exc))
                    break
                if state is not None:
                    try:self.observe_cid()  # Complete file, when available, must match engine-observed CID.
                    except BaseException as exc:self.errors.append('original CID custody: '+str(exc))
                    break
                time.sleep(min(0.05,max(0,settle_deadline-time.monotonic())))
            require(state is not None,'original publication/ownership unresolved after launcher terminal')
            if state['Running']:
                rc,out,err=self.command(['container','stop','--time','1',state['Id']],timeout=2)
                require(rc==0 and out==(state['Id']+'\n').encode() and err==b'','exact owned stop failed')
                self.errors.append('original research container required cleanup stop')
                state=self.inspect_owned(timeout=0.5)
            require(state is not None and not state['Running'] and state['Pid']==0,
                'original positive nonrunning terminal unavailable')
            self.final_state=state
            if self.cid_pin is None:self.errors.append('original completed CID physical custody unavailable')
            try:
                self.successful_container_terminal(state,time.time_ns())
                self.successful_original_state=True
            except BaseException as exc:
                self.errors.append('original container terminal: '+str(exc))
            # This original positive observation remains retained before any exact removal.
            self.evidence.event('original_container_terminal_before_remove',state=state)
            rc,out,err=self.command(['container','rm',state['Id']],timeout=0.5)
            require(rc==0 and out==(state['Id']+'\n').encode() and err==b'','exact nonrunning owned remove failed')
            require(self.inspect_owned(timeout=0.5,identifier=state['Id']) is None and
                self.inspect_owned(timeout=0.5,identifier=self.name) is None,
                'removed original CID/name absence unconfirmed')
            self.absent_after_rm=True
        except BaseException as exc:
            self.errors.append('owned cleanup: '+str(exc))
        finally:
            try:
                if self.process.poll() is None:
                    os.killpg(self.process.pid,signal.SIGKILL)
                    self.process.wait(timeout=min(0.5,max(0.01,self.cleanup_deadline-time.monotonic()-1)))
            except BaseException as exc:
                self.errors.append('original launcher reap: '+str(exc))
            finally:
                for thread in threads:
                    thread.join(timeout=min(0.25,max(0,self.cleanup_deadline-time.monotonic()-1)))
                if any(thread.is_alive() for thread in threads):self.errors.append('original pipe reader survived')
                for stream in (self.process.stdout,self.process.stderr):stream.close()
                if self.cid_fd is not None:
                    os.close(self.cid_fd);self.cid_fd=None
            self.evidence.event('original_cleanup_terminal',elapsed_s=time.monotonic()-begun,
                launcher_returncode=self.process.returncode,forced_group_stop=forced,
                original_terminal_observed=self.final_state is not None,
                exact_remove_then_absence=self.absent_after_rm,errors=list(self.errors))
            self.evidence.close()
            self.cleanup_elapsed_s=time.monotonic()-begun
            self.in_cleanup=False
            if time.monotonic()>self.cleanup_deadline:
                self.errors.append('original owned cleanup15s exceeded after final close')

    def preflight(self):
        predeadline=min(self.start+120,self.deadline)
        code=Path(__file__).resolve().parent
        self.code_pins=[self.pin(code/name) for name in ('controller.py','guest_consumer.py','research_protocol.py')]
        ledger_pin=self.pin(self.root/'artifacts/benchmark_recovery_20260930/decoder-experiment-prerequisites/prerequisite-recipe-ledger.v1.json')
        ledger=verify_seal(strict_object(os.pread(ledger_pin.fd,METADATA_MAX,0),METADATA_MAX))
        require(ledger_pin.descriptor['sha256']=='8e99036f2d9e2e21ccf27b9d7f92989b22b7d9d9e7f7b7923e99b9b390fe2654',
            'historical prerequisite ledger differs')
        require(ledger['image_id']==IMAGE_ID, 'research image differs from original build')
        source_pins=[]
        for citation in ledger['source_citations']:
            descriptor=citation['descriptor']
            source_pins.append(self.pin(descriptor['path'],descriptor).descriptor)
        # Planning physical facts remain distinct from unrelated working-tree content.
        planning_pins=[self.pin(self.root/'openspec/changes/fix-benchmark-preparations-spec'/name)
            for name in ('proposal.md','design.md','tasks.md','specs/benchmark-launch-preparation/spec.md')]
        gitdir='/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec'
        completed=subprocess.run(['/usr/bin/git','--git-dir='+gitdir,'--work-tree='+str(self.root),
            'cat-file','-t',PLANNING_COMMIT],stdin=subprocess.DEVNULL,capture_output=True,timeout=5)
        require(completed.returncode==0 and completed.stdout==b'commit\n', 'reviewed planning commit unavailable')
        for pin in planning_pins:
            relative=str(pin.path.relative_to(self.root))
            reviewed=subprocess.run(['/usr/bin/git','--git-dir='+gitdir,'--work-tree='+str(self.root),
                'show',PLANNING_COMMIT+':'+relative],stdin=subprocess.DEVNULL,capture_output=True,timeout=5)
            require(reviewed.returncode==0 and len(reviewed.stdout)<=METADATA_MAX and
                hashlib.sha256(reviewed.stdout).hexdigest()==pin.descriptor['sha256'],
                'current planning bytes differ from exact reviewed commit')
        rc,out,err=self.command(['info','--format','{{json .ID}}'])
        require(rc==0 and err==b'' and out==canonical(DAEMON_ID)+b'\n', 'original pinned daemon differs')
        self.daemon=out
        rc,out,err=self.command(['ps','--all','--no-trunc','--format','{{.ID}}'])
        require(rc==0 and err==b'' and out==b'', 'research quiet interval has another container')
        rc,out,err=self.command(['image','inspect','--format','{{.Id}}',IMAGE_ID])
        require(rc==0 and err==b'' and out==(IMAGE_ID+'\n').encode(), 'original built image unavailable')
        require(self.inspect_owned() is None, 'reserved unique research name collision')
        rows=[]
        self.media_pins=[]
        observation_pin=self.pin(self.root/'artifacts/benchmark_recovery_20260930/decoder-experiment-prerequisites/original-media-physical-observation.v1.json',
            {'size_bytes':3430,'sha256':'1c0be813ac9c62e34a8a633cc566603e8af203ddfcffd4f76cb0d4f4eef843cf'})
        observed=strict_object(os.pread(observation_pin.fd,METADATA_MAX,0),METADATA_MAX)
        observed_media={row['role']:row['descriptor'] for row in observed['media']}
        # Use original physically frozen sizes from the full-byte observation, not ffprobe packet bounds.
        for source in ledger['stock_sources']:
            source=dict(source)
            relative=source['stock_source_parameters']['input_path']
            pin=self.pin(self.root/relative, observed_media[source['role']])
            require(pin.descriptor['sha256']==source['stock_source_parameters']['source_sha256'], 'original media hash differs')
            self.media_pins.append(pin)
            source['media']=pin.descriptor
            source['actual_first_32_au_max_bytes']=None
            rows.append(source)
            require(time.monotonic()<predeadline, 'physical media prelaunch120s cap')
        plan={'schema_version':1,'artifact_kind':'vast_decoder_research_plan_v1','planning_commit':PLANNING_COMMIT,
            'image_id':IMAGE_ID,'fixed_order':FIXED_ORDER,'sources':rows,
            'guest_prelaunch_budget_s':max(0,120-(time.monotonic()-self.start)-1),
            'source_binary':ledger['actual_package_files']['source_binary'],
            'nvcodec_plugin':ledger['actual_package_files']['nvcodec_plugin'],
            'code':[pin.descriptor for pin in self.code_pins], 'source_files':source_pins,
            'planning_files':[pin.descriptor for pin in planning_pins], 'historical_prerequisite':ledger_pin.descriptor,
            'accepted':False,'publication_ready':False,'benchmark_arm_count':0,'native_pair_count':0,
            'qualification_count':0,'model_or_parity_evidence':False}
        self.plan_descriptor=self.evidence.document('execution-plan.v1.json',plan)
        self.plan_pin=self.pin(self.evidence.directory/'execution-plan.v1.json', self.plan_descriptor)
        self.evidence.document('reservation.v1.json', {'artifact_kind':'vast_decoder_research_reservation_v1',
            'name':self.name,'label':self.label,'reserved_at_ns':self.reserved_at,'daemon_id':DAEMON_ID,
            'image_id':IMAGE_ID,'controller':owner(os.getpid()),'engine':self.engine.descriptor,
            'engine_socket':[self.socket_before.st_dev,self.socket_before.st_ino,self.socket_before.st_mode,
                self.socket_before.st_uid,self.socket_before.st_gid], 'plan':self.plan_descriptor,
            'planning_commit':PLANNING_COMMIT,'once_only':True,'accepted':False})
        require(time.monotonic()<predeadline,'prelaunch120s deadline exceeded')

    def completed_document(self,path,kind):
        if not path.exists():
            return None
        info=path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=16384,
            'phase document inode/byte cap')
        try:
            value=verify_seal(strict_object(path.read_bytes()))
        except ResearchError:
            return None  # A zero-byte/partial original append is still pending, never completion.
        require(value.get('artifact_kind')==kind,'original phase document kind differs')
        return value

    def monitor_namespaces(self):
        total=0
        active=[]
        for directory in (self.destination/'guest').iterdir():
            require(directory.is_dir() and not directory.is_symlink(), 'unexpected guest namespace')
            require(not (directory/'receipt-time-limit-failure.v1.json').exists(),
                'original guest final append exceeded its reviewed time limit')
            subtotal=0
            for path in directory.iterdir():
                info=path.lstat()
                require(stat.S_ISREG(info.st_mode) and info.st_nlink==1, 'unexpected guest output inode')
                subtotal+=info.st_size
            require(subtotal <= (METADATA_MAX//2 if directory.name=='metadata' else 256*1024*1024),
                'guest namespace disk cap')
            total+=subtotal
            if directory.name.startswith('run-'):
                started=self.completed_document(directory/'run-started.v1.json','vast_decoder_research_run_started_v1')
                if started is not None:
                    active.append((directory,started))
        require(total + self.evidence.total <= 1024*1024*1024+METADATA_MAX,'whole research disk cap')
        active.sort(key=lambda item:item[1]['run'])
        for (previous,previous_start),(following,following_start) in zip(active,active[1:]):
            prior_terminal=self.completed_document(previous/'terminal.v1.json','vast_decoder_research_run_terminal_v1')
            require(following_start['run']==previous_start['run']+1 and
                prior_terminal is not None and prior_terminal.get('run_successful') is True and
                0<=prior_terminal['elapsed_s']<=120,
                'overlapping or skipped original research runs')
        return active[-1:]

    def launch(self):
        code=Path(__file__).resolve().parent
        argv=['run','--name',self.name,'--cidfile',str(self.cidfile),
            '--label',self.label_key+'='+self.label,'--gpus','all','--network','none','--read-only',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=134217728,mode=1777',
            '--env','HOME=/tmp','--env','XDG_CACHE_HOME=/tmp',
            '--env','NVIDIA_DRIVER_CAPABILITIES=compute,utility,video',
            '--mount','type=bind,src='+str(code)+',dst=/opt/vast/code,readonly',
            '--mount','type=bind,src='+str(self.plan_pin.path)+',dst=/opt/vast/input/plan.json,readonly',
            '--mount','type=bind,src='+str(self.destination/'guest')+',dst=/opt/vast/output']
        for role,pin in zip(('front_gate','underbody'),self.media_pins):
            argv += ['--mount','type=bind,src='+str(pin.path)+',dst=/opt/vast/media/'+role+'.mp4,readonly']
        argv += ['--entrypoint','/usr/bin/python3',IMAGE_ID,'-I','-B','/opt/vast/code/guest_consumer.py',
            '--plan','/opt/vast/input/plan.json','--output-dir','/opt/vast/output']
        self.evidence.document('launch-intent.v1.json', {'artifact_kind':'vast_decoder_research_launch_intent_v1',
            'argv':[str(self.engine.path),*argv], 'plan':self.plan_descriptor,'accepted':False})
        out=self.evidence.open('original.stdout',CHANNEL_MAX)
        err=self.evidence.open('original.stderr',CHANNEL_MAX)
        self.original_launch_monotonic=time.monotonic()
        self.process=subprocess.Popen([str(self.engine.path),*argv],executable=f'/proc/self/fd/{self.engine.fd}',
            pass_fds=(self.engine.fd,),env=self.environment,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        threads=[]
        self.phase_deadline=self.deadline-15
        try:
            self.child=owner(self.process.pid)
            self.evidence.document('process-start.v1.json',{'artifact_kind':'vast_decoder_research_process_start_v1',
                'child':self.child,'controller':owner(os.getpid()),'argv':[str(self.engine.path),*argv],
                'started_realtime_ns':time.time_ns(),'accepted':False})
            for stream,name in ((self.process.stdout,out),(self.process.stderr,err)):
                thread=threading.Thread(target=self.drain,args=(stream,name,self.errors,self.deadline),daemon=True)
                thread.start();threads.append(thread)
            while self.process.poll() is None:
                require(not self.abort.is_set() and time.monotonic()<self.deadline-15,'original controller600s/error cap')
                self.check_socket()
                for pin in self.pins:pin.verify()
                cid=self.observe_cid()
                if cid is not None and not self.cid_ownership_observed:
                    require(self.inspect_owned() is not None,'original container vanished before ownership observation')
                    self.cid_ownership_observed=True
                active=self.monitor_namespaces()
                if not active:
                    require(time.monotonic()<self.start+120,'shared host+guest prelaunch120s cap')
                for directory,started in active:
                    terminal=self.completed_document(directory/'terminal.v1.json','vast_decoder_research_run_terminal_v1')
                    if terminal is not None:
                        require(terminal['run']==started['run'] and type(terminal['elapsed_s']) in (int,float) and
                            0<=terminal['elapsed_s']<=120,'original closed run exceeds120s')
                        continue  # Original receipt-last ended this run; remaining finalization uses whole600s.
                    # Add a guest clock interval to an earlier host launch; never subtract absolute clocks.
                    # Container startup time is conservatively omitted, so this watchdog cannot extend a run.
                    anchor=self.original_launch_monotonic+started['guest_elapsed_at_start_s']
                    require(time.monotonic()-anchor<120,'external original-run120s bound')
                    if self.completed_document(directory/'startup-completed.v1.json','vast_decoder_research_startup_v1') is None:
                        require(time.monotonic()-anchor<45,'external original-startup45s bound')
                    eof=self.completed_document(directory/'source-transport-eof.v1.json','vast_decoder_research_source_transport_eof_v1')
                    drain=self.completed_document(directory/'decoder-drain-completed.v1.json','vast_decoder_research_decoder_drain_v1')
                    if drain is not None:
                        require(0<=drain['elapsed_from_source_eof_s']<=10,'original closed decoder drain exceeds10s')
                    if eof is not None and drain is None:
                        eof_anchor=self.original_launch_monotonic+eof['guest_elapsed_at_eof_s']
                        require(time.monotonic()-eof_anchor<10,'external original sourceEOF/decoder-drain10s bound')
                time.sleep(0.1)
        finally:
            # Preserve any original body exception; cleanup cannot manufacture a successful terminal.
            try:
                self.cleanup_original(threads)
            except BaseException as exc:
                self.errors.append('original cleanup persistence/reap: '+str(exc))
                self.in_cleanup=False
        require(self.process.returncode==0 and not self.errors and self.absent_after_rm and self.successful_original_state,
            'original process/container did not finish successfully')

    def execute(self):
        successful=False
        guest_descriptor=None
        failure=None
        try:
            self.preflight()
            self.launch()
            guest=self.destination/'guest/metadata/research-terminal.v1.json'
            require(guest.stat().st_size<=16384,'guest terminal cap')
            guest_pin=self.pin(guest)
            guest_receipt=verify_seal(strict_object(os.pread(guest_pin.fd,16384,0)))
            require(guest_receipt['result'] is not None and guest_receipt['failure'] is None and
                guest_receipt['runs_completed']==4 and guest_receipt['elapsed_s']<=600 and
                guest_receipt['accepted'] is False and guest_receipt['publication_ready'] is False,
                'guest original result failed')
            guest_descriptor=guest_pin.descriptor
            self.monitor_namespaces()
            self.phase_deadline=min(self.deadline-1,self.cleanup_deadline-1)
            for pin in self.pins:
                pin.deadline=self.phase_deadline
                pin.verify(rehash=True)
            rc,out,err=self.command(['info','--format','{{json .ID}}'])
            require(rc==0 and out==self.daemon and err==b'','original daemon changed')
            require(time.monotonic()<self.deadline,'original whole600s cap exceeded')
            successful=True
        except BaseException as exc:
            failure=str(exc)
        finally:
            try:
                self.evidence.close()
                leaves=[]
                final_deadline=min(self.deadline,self.cleanup_deadline or self.deadline)
                try:
                    for path in sorted(self.evidence.directory.iterdir()):
                        pin=Pin(path,maximum=METADATA_MAX//2,deadline=final_deadline-1)
                        try:leaves.append(pin.descriptor)
                        finally:pin.close()
                    require(time.monotonic()<final_deadline-1,'original finalization reserve exhausted')
                except BaseException as exc:
                    successful=False
                    self.errors.append('closed controller leaf hashing: '+str(exc))
                    if failure is None:failure=str(exc)
                leaves_receipt=self.evidence.document('closed-controller-leaves.v1.json',{
                    'artifact_kind':'vast_decoder_research_closed_controller_leaves_v1','leaves':leaves,
                    'accepted':False,'publication_ready':False})
                terminal=self.evidence.document('terminal.v1.json',{'artifact_kind':'vast_decoder_research_controller_terminal_v1',
                    'planning_commit':PLANNING_COMMIT,'image_id':IMAGE_ID,'name':self.name,'label':self.label,
                    'container_id':self.container_id,'child':self.child,'controller':owner(os.getpid()),
                    'original_cli_returncode':None if self.process is None else self.process.returncode,
                    'cleanup_elapsed_after_close_s':getattr(self,'cleanup_elapsed_s',None),
                    'original_execution_completed':successful,'failure':failure,'errors':self.errors,
                    'success_scope':'Original process/container and guest reported bounded completion; independent physical cold recomputation pending',
                    'independent_cold_recomputed':False,'research_conclusion_authorized':False,
                    'container_not_found_after_owned_remove':getattr(self,'absent_after_rm',None),
                    'final_observed_state':getattr(self,'final_state',None),
                    'oom_killed':None if getattr(self,'final_state',None) is None else self.final_state['OOMKilled'],
                    'elapsed_s':time.monotonic()-self.start,'guest_terminal':guest_descriptor,
                    'closed_controller_leaves':leaves_receipt,
                    'held_inputs':[pin.descriptor for pin in self.pins], 'accepted':False,'publication_ready':False,
                    'native_pair_count':0,'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False},final=True)
            finally:
                self.evidence.close()
                for pin in reversed(self.pins):pin.close()
                os.close(self.socket_fd)
            within_deadline,late_receipt=post_receipt_deadline(
                self.evidence,terminal,self.start,self.deadline,'controller',self.cleanup_deadline)
            successful=successful and within_deadline
            print(canonical({'receipt':terminal,'original_execution_completed':successful,
                'receipt_time_limit_failure':late_receipt,'independent_cold_recomputed':False}).decode(),flush=True)
        return 0 if successful else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    controller=Controller(args.project_root,args.output_dir)
    def interrupted(number,frame):
        controller.abort.set()
        raise ResearchError('original controller interrupted by signal '+str(number))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    return controller.execute()


if __name__=='__main__':
    sys.exit(main())
