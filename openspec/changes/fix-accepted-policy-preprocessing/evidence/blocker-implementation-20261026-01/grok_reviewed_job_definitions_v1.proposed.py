class BackendPublicationProcessSupervisorV3Error(RuntimeError):
    """The exact v3 process run failed or could not be contained."""

    def __init__(
        self,
        message: str,
        *,
        observation: dict[str, Any] | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        super().__init__(message)
        self._observation = (
            None if observation is None else copy.deepcopy(observation)
        )
        self._stdout = bytes(stdout)
        self._stderr = bytes(stderr)

    @property
    def observation(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._observation)

    @property
    def stdout(self) -> bytes:
        return self._stdout

    @property
    def stderr(self) -> bytes:
        return self._stderr


class _WindowsJob:
    def __init__(self) -> None:
        if os.name != "nt":
            raise BackendPublicationProcessSupervisorV3Error(
                "Windows Job Object requested on a non-Windows platform"
            )
        from ctypes import wintypes

        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle: int | None = None
        self.assigned_before_resume = False
        self.kill_on_close = False
        create_job = self._kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        handle = create_job(None, None)
        if not handle:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Windows Job Object creation failed"
            )
        self._handle = int(handle)
        try:
            self._set_kill_on_close()
        except BaseException:
            self.close()
            raise

    def _set_kill_on_close(self) -> None:
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        information = EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        set_information = self._kernel32.SetInformationJobObject
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL
        if self._handle is None or not set_information(
            wintypes.HANDLE(self._handle),
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Windows Job Object policy failed"
            )
        self.kill_on_close = True

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        assign = self._kernel32.AssignProcessToJobObject
        assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign.restype = wintypes.BOOL
        process_handle = int(getattr(process, "_handle"))
        if self._handle is None or not assign(
            wintypes.HANDLE(self._handle), wintypes.HANDLE(process_handle)
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process Job Object assignment failed"
            )
        self.assigned_before_resume = True

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        if not self.assigned_before_resume:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process resume preceded Job Object assignment"
            )
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        resume = ntdll.NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        status = int(resume(wintypes.HANDLE(int(getattr(process, "_handle")))))
        if status != 0:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication suspended process resume failed"
            )

    def active_processes(self) -> int:
        from ctypes import wintypes

        class BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        information = BASIC_ACCOUNTING_INFORMATION()
        query = self._kernel32.QueryInformationJobObject
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query.restype = wintypes.BOOL
        returned = wintypes.DWORD()
        if self._handle is None or not query(
            wintypes.HANDLE(self._handle),
            1,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object accounting failed"
            )
        return int(information.ActiveProcesses)

    def terminate(self) -> None:
        from ctypes import wintypes

        terminate = self._kernel32.TerminateJobObject
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        if self._handle is not None and not terminate(
            wintypes.HANDLE(self._handle), 1
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object termination failed"
            )

    def close(self) -> None:
        from ctypes import wintypes

        handle = self._handle
        self._handle = None
        if handle is None:
            return
        close_handle = self._kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(wintypes.HANDLE(handle)):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object close failed"
            )


