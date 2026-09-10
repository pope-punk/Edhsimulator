"""Human-readable operator projections. Never used as pilot input."""
import json,re
from pathlib import Path


def decisions(directory):
    path=Path(directory)/'decisions.jsonl'
    if not path.exists():return []
    rows=[]
    for line in path.read_text(encoding='utf8').splitlines():
        if line.strip():rows.append(json.loads(line))
    result=[]
    for row in rows:
        label=row.get('chosen_label')
        if label is None and 'chosen_labels' in row:
            label='; '.join(str(x) for x in row['chosen_labels']) or 'Choose none'
        if label is None and 'choice_value' in row:
            value=row['choice_value']
            label=('Declare blocks for '+str(len(value))+' attackers') if isinstance(value,dict) and all(isinstance(v,list) for v in value.values()) else 'Submit a structured choice'
        elif label is None:label='Pass'
        label=re.sub(r'^(CAST COMMANDER|CAST|ACTIVATE|ESCAPE|CONCEDE)\b',lambda m:m[0].capitalize(),str(label))
        result.append({'id':row['decision_id'],'actor':row.get('actor','Unknown seat'),
                       'action':label,'rationale':row.get('rationale') or '',
                       'accepted_at':row.get('accepted_at','')})
    return result


def decision_markdown(rows,game):
    lines=[f'# Game {game} decision log','', 'Accepted pilot choices on the current branch, in order. Reasons are private operator information.','']
    for row in rows:
        lines += [f"## {row['id']} — {row['actor']}",'',row['action'],'']
        if row['rationale']:lines += ['Reason: '+row['rationale'],'']
    return '\n'.join(lines)


def published_short_term(operator,actor):
    if not actor:return ''
    slug=actor.lower().replace(' ','_').replace('&','and')
    text=operator.get(slug,'')
    section=text.partition('**Short-term plan**')[2].partition('**Long-term plan**')[0]
    return '\n'.join(line[2:] if line.startswith('> ') else '' for line in section.splitlines()).strip()


def runtime_health(path):
    """Bounded saved telemetry only; never opens transcripts or polls a model."""
    if not Path(path).exists():return {}
    value=json.loads(Path(path).read_text());events=value.get('retained_events',[])
    usage=[e.get('usage',{}).get('inputTokens',0) for e in events if e.get('event')=='usage' and not e.get('repeated_usage')]
    calls=[e.get('request') for e in events if e.get('event')=='tool_arrived']
    return {'scope':'Last recorded host session; retained events only',
            'input_samples':len(usage),'largest_input':max(usage,default=0),
            'inputs_over_64k':sum(n>=64000 for n in usage),
            'duplicate_request_ids':len(calls)-len(set(calls)),
            'rejected_tools':sum(e.get('event')=='tool_returned' and not e.get('success',True) for e in events)}
