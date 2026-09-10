# Plan recovery after rewind

The plans disappeared because rewind correctly changed seat branch identities, but static-standing publication reused the game-wide `static_standing` operation receipt. The previous operation had the same doctrine content, so its idempotency check returned without installing the new branch's component pointers. Dynamic planners consequently lacked their standing prerequisite. The dashboard correctly rejected the stale plans; restoring those old plans would have reintroduced discarded-branch information.

The static installation operation now includes the seat's branch identity. Identical installation retries remain idempotent within a branch, while a new branch gets its own installation receipt. A regression test exercises old branch → new branch → same-branch retry.

Paused at 276 accepted decisions, installed the frozen standing reference for all four current-branch snapshots, and resumed the same registered deciders through fenced host recovery. No accepted choices were discarded or supplied by the coordinator. New dynamic plans are authored by the registered planners. All 84 tests pass.

Live verification: all four seats published fresh short-term plans (435, 422, 448 and 447 characters respectively at the check). Each operator display exactly matched its valid publication. Gameplay continued to pending decision 285 with no pause marker.
