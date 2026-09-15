# Primitive campaign and web release

## Scope

The release target is the fixed four-deck pod, multi-game campaigns (1–1000 games),
learning disabled, isolated hosted roles, and the existing private web interface.
All 334 unique card programs are authored. This is not general Magic certification.

The web interface includes live table and all four seat views, current plans,
accepted decisions with rationales, public messages, result history and Aminatou
cardwise statistics/CSV. Operator information remains outside every pilot input.

Seeds increase by one and starting players rotate through the fixed seat order.
Each new game has a fresh game binding and isolated role registrations. Campaign
schedule, deck and strategy stay frozen. Automatic advancement requires a clean
terminal result, matching learning-skip receipt, verified journals and unloaded
previous transport. Rules-review draws, horizon stops and pauses require attention.
A paused existing game is never migrated to this engine or release.

## Validation checkpoint

Commit acc22da merged through PR #5 into main at 45acd50 on 2026-09-15. Its local
release passed 2,843 tests, isolated installed assets and source/install fingerprint
comparison. Windows and Linux CI passed. Receipt SHA-256:
`d4b26448d407c1c4bdeda2ba7ac7f219c4c6af356fde79a312a149ad73cee925`.

The campaign/dashboard extension passed 2,857 local tests and isolated installed
asset/fingerprint verification. Runtime receipt SHA-256:
`6fac056447b64bbbcc05aef50a0255d3713b7a47e47bcc26f1add651679aa437`.
The receipt remains bound to the runtime, web assets, policies and frozen strategy.

Offline fixtures exercise complete two-game advancement, clean role state,
unchanged prior-game storage, blocker/pause gates, report tampering, full-deck
cardwise tables and all four operator views. HTTP checks cover the interface,
snapshots, cardwise JSON/CSV, decision export, result CSV and authentication.
Fixture decisions are not live pilot or model validation. The final release notes
must separately record the real hosted-game outcome and CI results before
publication; a running game is not a completed validation result.

## Retained trials

- `primitive-hosted-test-20260915`: rules-review draw at accepted sequence 39,
  caused by lost decision ownership after a rejected command. Fixed in PR #4.
- `primitive-hosted-test-20260915-b`: rules-review draw at accepted sequence 561,
  caused by omitted guidance for declining optional resolution mana payments.
  Fixed in PR #5; the engine already supported `payment: null`.
- The legacy `first-dashboard-run` remains paused in game 4 after 222 decisions.

Both failed primitive trials retain their terminal evidence and skipped-learning
receipts; neither may resume or be counted as a successful hosted validation.
Historical September 8 migration notes and earlier primitive progress entries
retain their original scope. They do not describe this release's current status.

## Run

Use the README's release validation and dashboard commands. Release receipts are
local, implementation-bound build evidence; regenerate after bound source changes.
Keep the Codespace port private and enter its capability key in the interface.
The server and model hosts stop when the Codespace stops. Ten-minute task reminders
are local process reminders and cannot wake a stopped Codespace.
