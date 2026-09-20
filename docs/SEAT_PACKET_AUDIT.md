# Seat packet audit

`tools/export_seat_packets.py` exports one seat's preserved model input/output records
without modifying or replaying a started game. The game O operator requested
Reaminatour at turns 1–4, 17–20, and 25–28 (rounds 1, 5, and 7).

```sh
python tools/export_seat_packets.py \
  --cohort runs/web-campaign-20260916-o \
  --output archive/telemetry/game-o-reaminatour --watch
```

The collector follows historical and current role registrations from a read-only
SQLite snapshot and reads only those registered seat transcripts. It refreshes
three CSVs every 30 seconds. A local lock prevents duplicate collectors. Write
`STOP` in the output directory to stop collection; this does not pause gameplay.

Rows include instructions/configuration, recorded input messages, tool calls,
tool replies (including errors and waiting calls), output messages, and technical
help request/answer records. Event mirrors are excluded to avoid double counting.
Encrypted internal reasoning is counted as unavailable, never decrypted or represented
as readable content. Transport logs are not a complete serialized API request for
every internal inference; retained context is linked, not counted as freshly sent.

**Board metadata and round membership refer to the role's delivered snapshot.**
They are not invented live-state timestamps for asynchronous planner outputs.
The `decision #` column is the accepted global prefix of that snapshot where its
revision is available. Missing numbers remain blank. Opening/setup turn 0 is
included as a labelled prelude to round 1. Technical supervisor records instead
use their exact recorded accepted prefix and have no fabricated timestamp.
Length is UTF-8 bytes of the linked JSON record, not token count.

Every source copy links to the preceding packet in that physical conversation;
intervening rounds remain available as context dependencies. Full historical
transcripts from other seats are neither loaded nor exported. Manifests distinguish
unreached windows, collecting windows, passed windows, missing transcripts, and
decoding gaps. This is an operator communication audit, not a terminal cardwise
or learning report. It does not change the bound host implementation.

## Browser access

`tools/serve_packet_audit.py` wraps the existing dashboard on its existing port
and adds `/audit/`. It runs outside the game-bound package. The page uses the same
session authorization key as the dashboard; all packet data, CSV and ZIP routes
require bearer authentication. The public HTML shell contains no private packets.

```sh
# EDH_DASHBOARD_KEY and EDH_PRIMITIVE_RELEASE_RECEIPT come from the existing server environment.
python tools/serve_packet_audit.py --runs runs \
  --audit archive/telemetry/game-o-reaminatour \
  --public-url https://YOUR-CODESPACE-8765.app.github.dev
```

Download individual CSVs for browser packet hyperlinks, or the ZIP for portable
relative hyperlinks beside a `packets` folder. Plaintext spreadsheet cells are
escaped against formula injection; only exporter-generated hyperlinks are formulas.
The packet viewer displays escaped source text and offers a copy button.
