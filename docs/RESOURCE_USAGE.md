# Run storage and memory

Campaign journals are read line by line and written through a temporary file,
then published with the existing replacement behavior. Reads still return the
full parsed decision list required by replay; they no longer also retain the
whole source text and a list of every source line. Writes consume an iterable
one row at a time. Serialization failures leave the published journal intact.
Transaction image serialization is unchanged because recovery binds exact text.

Post-game generation releases the completed seat's evidence before constructing
the next seat's packet. Replay evidence and review coverage are unchanged.

When learning is disabled at initialization, terminal processing omits private learning
packets entirely. Gameplay journals, terminal results and observer views remain.

Generated runs, transcripts and diagnostics are excluded from source control. Retain
only the evidence needed for an active run, and summarize finished telemetry before
operator-authorized cleanup. Do not delete a running host's tape, claims or recovery
journals. File compression is a local filesystem choice, not a portability guarantee.

Use host context thresholds and exact conversation reference reuse to control
inference input. Inspect metadata before fetching full transcripts. File size,
process working set and remote model context are different measurements; report them
separately. No claim of a fixed end-to-end speedup follows from serialization savings.
