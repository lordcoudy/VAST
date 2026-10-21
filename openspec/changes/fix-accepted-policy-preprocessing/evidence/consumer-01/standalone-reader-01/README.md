# Fresh Standalone Default Reader Boundary

The complete positive fixture now keeps its existing same-process independent
default cold read and also launches a fresh interpreter before leaving the
prepared engine custody context. That child imports the actual guardian reader
first, with the selected frozen project's script directory at the front of
`sys.path`. It verifies the current module's exact path and SHA-256, calls only
the actual default project-root/contract/receipt/capability API, and requires the
actual contract semantic hash to agree with both the receipt and materializer.
Only after successful cold validation does it import the data-only provenance
helper to record the actual loaded production module paths and hashes.

No reader, assessor, fragment, pilot, acceptance or custody dependency is
substituted. Exact command, UTC start/finish, original stdout/stderr, original
exit code, byte lengths and hashes are retained exclusively in the fixture
namespace. A nonzero or malformed child result cannot become a positive proof.

- `red.*`: original exit 1 because the new standalone helper did not yet exist.
- `green.*`: original exit 0, one test in 0.118 seconds. A genuinely fresh child
  imports the actual current default reader and refuses missing in-root inputs;
  the parent preserves its real nonzero child exit and raw stderr. No in-root
  input or qualification output is created by this test.

This portable regression proves command selection, fresh import viability and
honest refusal retention only. It does not establish positive full-chain cold
validation. That assertion remains pending the explicitly authorized complete
physical-input fixture run. The module is included in the focused suite.
