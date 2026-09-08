# GitHub migration and paused-game handoff

The source repository is https://github.com/pope-punk/Edhsimulator. GitHub stores
the code; a persistent compute environment runs Python and the isolated Codex
agents. No local game is started by installation, CI or repository publication.

## Development in GitHub

The optional Codespaces development container installs Python 3.12 and this
package. It supports editing and `python -m edh_gauntlet verify`. It does not
install or authenticate a model runtime, resume a game, or claim that live gameplay
has been validated on Linux. The checked-in CI verifies the package on Windows
and Linux; live hosting has been exercised on Windows.

Actual remote play additionally requires a compatible Codex App Server build,
account authorization with the configured role models, persistent run storage,
and explicit operator start/resume. The current Windows telemetry collector and
launch/recovery scripts are not a Linux host supervisor. GitHub Actions verification
does not run games or spend model capacity.

## Preserved decision 305

The local test remains paused by its operator after 305 accepted decisions in
game 1, seed 2026090805. The next decision is 306. No terminal result, learning
pass or test-game win rate is implied. Learning and rules hotfixes remain deferred
under the game's original conditions. The game does not bind the newer full-turn
batching policy, and transferring it must not silently add that policy.

A separate, checksummed local `handoff/paused-game-305.zip` preserves the cohort's exact
files and a per-file manifest. The source cohort is also retained locally until a
destination is validated. Run archives are excluded from Git history. The archive
contains game evidence and observer information; it contains no Codex credentials
or machine-wide model-session database.

The public release distributes only `paused-game-305.zip.aesgcm`, authenticated
AES-256-GCM ciphertext. Its separate random key stays in the local ignored
`handoff/paused-game-305.key`; never upload it or paste it into GitHub/chat. Transfer
that file privately to the destination when preparing the hosted continuation.
To recover the ZIP after obtaining the key:

```sh
python -m pip install cryptography
python tools/open_handoff.py paused-game-305.zip.aesgcm --key-file paused-game-305.key --output paused-game-305.zip
```

The helper authenticates before writing, refuses to overwrite a file, and neither
extracts nor resumes the game. The release checksum describes ciphertext; the
embedded manifest verifies original plaintext files after decryption.

This is a preservation archive, **not an automatic remote import**. It contains
Windows absolute artifact paths and machine-local App Server conversation IDs.
The existing stopped-host recovery command verifies conversations on the same host;
it must not be pointed at a different machine as though those conversations exist.

Before continuing on a new host:

1. Verify the archive and accepted decision-tape hashes against its manifest.
2. Keep the destination paused while reconciling artifact paths and all references.
   Do not blindly rewrite content-addressed evidence or its fingerprints.
3. Preserve the original configuration, published plans, rationales, snoozes,
   approval/execution prefix, decision claim and pending work. Reconstruct isolated
   role contexts from their own retained memory, never from operator views.
4. Validate deterministic reconstruction at decision 306, with the same legal
   menu and unchanged accepted prefix, before admitting inference.
5. Start only the destination host after its authentication and recovery validation.

Cross-machine import and live remote continuation are follow-up work; publishing
the repository does not certify them. Never unpause the local copy to accomplish
the transfer.

## Authentication

Use Git Credential Manager's browser authorization for GitHub. Do not put passwords,
tokens, `.codex` state or model credentials in the repository or game archive.
The hosting environment authenticates its own model runtime separately. No website
accounts or login interface are introduced by this migration.
