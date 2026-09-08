# Static standing plans

Fresh split-architecture cohorts bind `static_standing:1`. Already initialized
games retain their recorded configuration and their original initialization.

Each deck has a reviewed Markdown file in `data/strategy/standing_plans/`.
The catalog records the seed text hash used for its review. A changed seed
requires review of the corresponding standing file and catalog entry before a
new game starts; the harness never silently regenerates doctrine with inference.
Each game freezes the four references once in `standing_plan_snapshot.json`.
Later source edits cannot change an existing game. Missing or damaged frozen
references stop initialization/replay rather than substituting new text.

Python installs the reference as an immutable `standing` component with writer
`static_reference`. There is no standing job or model publication stage. The
existing immutable component store and replacement current pointers are reused;
the text is not copied into every plan publication or decision packet.

The pilot receives its standing reference during mulligans and keeps using it
until the initial long-term goal arrives, including main-phase decisions. A pending
initial goal does not gate gameplay in static-standing games. The host replaces the retained strategic
reference on the next real decision input; there is no adoption inference.
The short-term planner retains standing doctrine. The long-term planner retains
the complete seed, deck and roles, without the standing summary.

Each seat's settled-hand boundary queues its own initial long-term goal as soon
as keep and any London bottom choices finish, even while other seats are still
mulliganing. No long-term work is queued for a provisional hand. A material
`long_term_validity:invalid` assessment later queues/coalesces a revision through
the existing goal-version checks. A revised goal requires a new diplomacy brief,
and every reviewed brief requires a diplomat post, including an unchanged KEEP.

Mandatory brief posting leads the independent diplomacy lane. Short-term and
long-term inference can continue concurrently. Legacy serialized hosts retain the
previous shared-slot priority until explicitly upgraded. Routine strategic watches
do not block mandatory posting. Before admitting the diplomat, Python refreshes its public snapshot and
checks authorization: an expired brief transfers directly to one strategic
refresh job, without a wasted diplomat inference. Publication and commit still
revalidate authorization, and no scheduler invents public text or commitments.
