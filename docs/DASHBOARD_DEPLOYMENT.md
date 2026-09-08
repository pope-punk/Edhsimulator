# Private Codespace dashboard

The dashboard runs the existing simulator without an alternate rules or scheduling
path. The Python API and static interface are served from the same Codespace; keep
port 8765 **Private** in the Codespaces Ports panel. GitHub authenticates access to
that forwarded URL.

## Start

Confirm that `codex` is signed in with the ChatGPT account whose weekly allowance
should be used. Do not set an OpenAI API key. Then run:

```sh
export EDH_DASHBOARD_KEY="$(openssl rand -base64 32)"
python -m edh_gauntlet.dashboard --host 0.0.0.0 --port 8765 --runs runs
```

Open the private forwarded URL. Enter that same URL and the capability key when
prompted. The key stays in browser session storage and is required for every read
and write request.

When **Start host** is selected, the adapter launches exactly:

```sh
python -m edh_gauntlet.host_runtime --cohort RUN --max-decisions 10000 \
  --context-tokens 64000 --timing-events 4096
```

`OPENAI_API_KEY`, `OPENAI_ORG_ID`, and `OPENAI_PROJECT_ID` are removed from the
host child environment. Missing ChatGPT/Codex authentication therefore fails
closed rather than falling back to API billing.

## Boundaries

- New runs use the simulator's fixed pod, contract 4, split architecture, and
  optional asynchronous diplomacy. The UI does not invent unsupported deck inputs.
- The API exposes no shell, arbitrary paths, pilot answers, or App Server RPC.
- Pause writes the documented cooperative `HOST_PAUSED.json` marker; it does not
  kill a process or discard accepted work.
- A stopped Codespace stops the web process. Cohort artifacts under `runs/` remain
  the source of truth and can be recovered only through the simulator's fenced
  recovery workflow.
- GitHub Pages can host the static files, but private Pages availability depends on
  the repository organization and plan. The private Codespace URL is the default.
