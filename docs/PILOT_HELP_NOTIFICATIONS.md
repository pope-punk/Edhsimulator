# Operator wake-up for pilot help

`tools/watch_pilot_help.py` is an opt-in local watcher for pending `await_pilot_help`
lifecycle requests. It queues a message to an explicitly authorized operator Codex
thread, using the installed `codex queue` command. It never answers for a pilot,
submits a gameplay choice, resumes a host or changes a game's contract.

```sh
python tools/watch_pilot_help.py --runs /path/to/runs \
  --state-dir /path/to/notification-state --thread OPERATOR_THREAD_UUID
```

It polls every two seconds without inference. A file lock prevents duplicate
watchers using the same state directory. Each run/game/request/prefix receives
one durable notification receipt. The receipt is written before sending: uncertain
queue outcomes require operator reconciliation rather than blind retries. Keep
this directory across watcher restarts. `process.json` identifies the watcher;
individual receipts distinguish queued delivery from uncertain delivery.

An operator pause marker suppresses notifications for that run. Create `STOP` in
the state directory to stop the watcher; later user stop/pause instructions take
precedence over queued notifications. Every notification directs the assistant to
recheck the current request and avoid duplicate recovery if another turn already
handled it. Do not treat stale notifications as permission to resume.

The watcher can run independently of a stopped gameplay host. It must itself remain
running, and the local Codespace/Codex environment must be available. It cannot
wake a suspended Codespace. The existing primitive help-status, answer-help and
fenced Resume workflow still handles the actual request.


## Independent background support

`--mode support` runs one fresh `codex exec` conversation for each new request,
separately from the development thread. The same local watcher lock serializes
support workers. The request/prefix receipt is written before launch, preventing
repeat execution after an uncertain outcome. Idle polling performs no inference.
Workers inherit the local Codex login and default model configuration, use
approval policy never, and receive technical-only instructions with explicit
stop/pause and stopped-prefix requirements. They may answer and resume through
the existing supported lifecycle but may not choose game actions or edit source.

The worker's JSONL and final report are retained beside its receipt. The watcher
checks durable help state after completion; unresolved/uncertain attempts queue
one escalation to the development thread rather than launch a duplicate worker.
A different pending request receives its own fresh conversation on the next poll.
This remains a local Codespace service: it needs the Codespace running and does
not add a gameplay lane or change the game's contract.
