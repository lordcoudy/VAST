# Preserved Prelaunch Wrapper Failure

The original operational script invocation closed with exit code 1 before any
overlay copying or regression execution. This is not a RED test result.

The original Linux `ps -eo pid,ppid,args` observation completed naturally with
exit code 0, UTC 2026-10-12T11:30:36.7265747Z through
2026-10-12T11:30:36.8305484Z. Its raw streams and receipt remain unchanged.
No SOURCE06/CI06 or complete-consumer producer commands matched that snapshot.
Windows worker observation was not reached and is not claimed as verified.

The wrapper stopped at line 72 because `Invoke-Original` returned two unwanted
`System.Threading.Tasks.VoidTaskResult` objects alongside its intended receipt.
A memory-only PowerShell diagnostic confirmed that the actual generic task
awaiter emits one such object per unassigned `GetResult()` call. Suppressing
only those two await results preserves the original child command, raw byte
streams, natural wait and original exit code.

Original script: `../Run-GuardianLifetimeRed01.v1.ps1`.
Original script SHA256:
`a0b1d4184966a6a45521d486f6f869620bdbf2b28c91bc57e9418f423fd34e22`.
Original ps receipt SHA256:
`7e168229a92433d98ab06c6932a5ca4f333cf4be1d0679d3d1f9480f22624624`.

No external overlay or test-original result existed after this invocation.
The unchanged regression test SHA256 is
`19543d86e69094d36f4ef6a6268d486218f8eeab3d4358f89d77d046f4952c4d`.
A corrected invocation requires separately reviewed fresh controls and overlay;
it does not replace or repair these preserved original observations.
