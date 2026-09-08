"""Bounded per-tier origins; a new short sequence never rejuvenates an old goal."""
def update(plan, prior, stage, published_at):
    origins=dict((prior or {}).get('tier_origins',{}))
    fields={'standing':'standing_plan','long_term':'long_term_plan','short_term':'short_term_plan'}
    for tier,field in fields.items():
        if not plan.get(field):origins.pop(tier,None)
        elif stage==tier:
            origins[tier]={'after_decision':plan['source_session']['accepted_prefix_count'],
                'event_seq':plan['event_seq'],'published_at':published_at}
    plan['tier_origins']=origins


def label(plan,tier):
    origin=(plan or {}).get('tier_origins',{}).get(tier)
    if not origin:return 'Origin not recorded for this legacy tier.'
    text=f"Written from the snapshot after decision {origin['after_decision']}."
    current=(plan or {}).get('source_session',{}).get('accepted_prefix_count')
    if current is not None:
        text+=f" {max(0,current-origin['after_decision'])} accepted decisions before the latest planning snapshot."
    return text
