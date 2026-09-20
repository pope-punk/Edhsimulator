# Sparse object packet preview

`tools/sparse_packet.py` is an offline presentation prototype. No running game
has this encoding enabled and no source packet or replay record is overwritten.

`encode(packet)` removes allowlisted defaults from recognized object snapshots
(name, types, zone and exact object reference). A shared schema and small `_s`
marker preserve original field presence, including absence versus explicit false.
Zero power/toughness, costs, identities, unknown fields, and scalar delta operations
remain explicit. `decode()` reconstructs the exact original packet.

`group_locations()` replaces object lists with ordered location groups. Shared
zone/controller/owner values appear once; exceptions remain on individual objects.
Contiguous groups preserve the original order. Decode locations first, then sparse
defaults, then existing board deltas/references and their original hashes.

The authenticated `/audit/sparse/` page compares the original Reaminatour packet at
accepted prefix 895 with both prototype renderings. It uses the same dashboard
key and displays full packet contents without downloads. Source data remains in
ignored `archive/telemetry/game-o-reaminatour/sparse-preview.json`.

Measured compact UTF-8 JSON sizes, including new encoding instructions:

| Representation | Bytes | Reduction |
| --- | ---: | ---: |
| Original packet | 125,858 | — |
| Sparse object defaults | 119,378 | 5.15% |
| Sparse defaults + location groups | 117,588 | 6.57% |

This is packet text size, not tokenizer-measured inference savings. The larger
transcript record also includes an escaped JSON envelope. Rules programs, plans,
and conversation content are unchanged, which limits whole-packet savings.

Four focused tests cover round-trip equality, absent fields, meaningful zeros,
unknown fields, explicit reset deltas, marker collisions, ownership exceptions,
and order preservation. The real packet also passes exact reconstruction.

Before production use, bind the format to a fresh release, integrate it at every
inference-recipient delivery boundary, and update inspection/packet decoders.
Never silently change an existing game's contract.

## Pilot-facing working document

The revised default preview uses `tools/pilot_text_preview.py`. It reorganizes
object snapshots under headings such as “Reaminatour’s battlefield — Lands”.
Zone, controller and complete card-type combinations are implied by the heading;
owner appears only for exceptions. Mixed card types receive composite headings.
Subtypes/supertypes, non-default state, meaningful zeros, and exact references remain.
Front-face labels and catalog definition IDs are omitted from card prose. Ordered
zones retain original positions; battlefield display order is reorganized.

This is a semantic presentation, not an exact reconstruction of every internal
serialization field. Original JSON remains available. The previous reversible
sparse encodings remain independent experiments. The full working document is
113,501 UTF-8 bytes versus 125,858 for compact original JSON (9.82% smaller).
Rules programs and conversation contents have not been rewritten or summarized.
Three focused presentation tests cover inherited headings, ownership exceptions,
multi-type cards, meaningful zeros, exact references, graveyard positions and
explicit delta resets. Browser checks verify the rendered grouping and original
packet toggle. The live host still does not use this experimental representation.
