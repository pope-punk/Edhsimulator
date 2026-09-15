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
