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
