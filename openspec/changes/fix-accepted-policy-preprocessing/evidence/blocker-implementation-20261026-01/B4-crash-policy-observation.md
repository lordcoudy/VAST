# Actual read-only crash-policy observation, not qualification

Tool return8749cd and exact submitted probe source are retained separately.
The probe only reads bounded kernel/process metadata; it launches no container,
crash, compiler, build, service change or storage allocation. Output<=4096B;
process scan<=8192entries, at most4name matches. These are claimed process names,
not socket/service/executable-identity or bootstrap qualification. Raw proc-file
bytes were parsed by the probe and are not claimed separately captured originals.

Observed Ubuntu bootdf4955d9-4762-42b4-a55b-0106ba3786f8, kernel
6.6.87.2-microsoft-standard-WSL2, core_pattern
`|/wsl-capture-crash %t %E %p %s`, core_pipe_limit0, suid_dumpable0,
pid_max4194304 and threads_max192154. Root observer Python has core soft0/hard
unlimited and filter00000033. Processes named containerd(pid234) and
dockerd(pid1988) each have17threads, unlimited soft/hard core-file limits and
filter00000033. Neither observation proves the future RUN or compiler policy.

Separate wsl.exe --version tool return1d98e0 reports WSL2.5.10.0 and kernel
6.6.87.2-1. That returned text includes UTF-16 NULs; its original tool transcript
is retained in the conversation. No raw CLI stdout-byte capture/hash is claimed
and no normalized version file substitutes for it. Installed handler binary
identity is unknown: the initial whitelist probe looked only for a different
absolute handler path and therefore did not open the actual /wsl-capture-crash.

The outside-S crash-output term remains unresolved. Source review of the exact
WSL version/handler and actual qualified daemon/RUN inheritance or an explicit
outside charge/HOLD is required. CORE1/filter0 alone is not treated as proof;
no global core_pattern change, handler/config mutation or execution occurred.
