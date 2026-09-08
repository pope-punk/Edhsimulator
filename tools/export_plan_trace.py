"""User-requested private plan audit; never imported into gameplay packets."""
import argparse,json
from pathlib import Path


def read(path):return json.loads(path.read_text(encoding='utf8'))
def quote(text):return '\n'.join('> '+line for line in (text or '(none)').splitlines())
def link(path,label):return f'[{label}](<{path.resolve().as_posix()}>)'
def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('cohort',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();game=args.cohort.resolve()/'game_01';directory=game/'continuity'
    rows=[json.loads(line) for line in (game/'decisions.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    publications={read(p)['plan_id']:read(p) for p in (directory/'publications').glob('*.json')}
    plans={pid:read(directory/'plans'/(pid+'.json')) for pid in publications}
    mapped={pid:[] for pid in plans};no_plan={};batch_plan={}
    for row in rows:
        aux=row.get('auxiliary_payload',{});batch=aux.get('batch');runtime=aux.get('runtime')
        pid=batch['plan_id'] if batch else None
        if batch:batch_plan[batch['id']]=pid
        if not pid and runtime:
            pid=read(game/'handoffs/attachments'/(runtime['attachment_id']+'.json')).get('plan_id')
        if pid in mapped:mapped[pid].append(row)
        else:no_plan.setdefault(row['actor'],[]).append(row['decision_id'])
    approvals={}
    for p in (game/'handoffs/sequences/approvals').glob('*.json'):
        pid=batch_plan.get(p.stem)
        if pid:approvals.setdefault(pid,[]).append((p,read(p)))
    actors=sorted({p['actor'] for p in plans.values()});lines=['# Every published plan and its pilot trace — decisions 1–150','',
        'Private audit requested by the user, exported outside the cohort. Do not provide this cross-seat report to any pilot or planner. The game remains paused.', '',
        'Scope: all published planner snapshots in this game, not only the latest 60 decisions. Prose is quoted verbatim. Identical long-term text is printed once per seat; KEEP publications reference it. Short-term prose is also deduplicated by exact text. The immutable seed is separate from these planner-authored snapshots.', '',
        'Evidence limits: a frozen plan attachment establishes availability during a decision; it does not establish that a plan caused that choice. There is no separate prose approval turn. Batch approve/reject lists are explicit verdicts on symbolic actions, not endorsements of every prose claim. “Adopted planner rationale” is planner-written text accepted by the pilot, not a fresh pilot explanation. No hidden reasoning is reconstructed.', '',
        'Rules caveat: four recoverable engine issues remain recorded and unpatched. Executed actions below describe the accepted ledger, not an independent rules-correctness certification.', '',
        '| Player | Published snapshots | Distinct long-term prose | Distinct short-term prose | Accepted rows with a plan |','|---|---:|---:|---:|---:|']
    summary=[]
    for actor in actors:
        selected=[(pid,p) for pid,p in plans.items() if p['actor']==actor]
        count=(len(selected),len({p['long_term_plan'] for _,p in selected}),len({p['short_term_plan'] for _,p in selected}),sum(len(mapped[pid]) for pid,_ in selected))
        lines.append(f'| {actor} | '+ ' | '.join(map(str,count))+' |');summary.append({'actor':actor,'snapshots':count[0],'unique_long':count[1],'unique_short':count[2],'accepted_rows':count[3]})
    for actor in actors:
        selected=sorted([(pid,p) for pid,p in plans.items() if p['actor']==actor],key=lambda item:publications[item[0]]['published_at'])
        longs={};shorts={}
        for _,p in selected:
            longs.setdefault(p['long_term_plan'],'L'+str(len(longs)+1));shorts.setdefault(p['short_term_plan'],'S'+str(len(shorts)+1))
        lines+=['',f'## {actor}','',f"Decisions before/without a published plan attachment: {', '.join(no_plan.get(actor,[])) or 'none'}.",'','### Unique long-term plans']
        for text,lid in longs.items():
            uses=[(pid,p) for pid,p in selected if p['long_term_plan']==text];first=uses[0]
            lines+=['',f'#### {lid}','',quote(text),'',f"Source: {link(directory/'plans'/(first[0]+'.json'),first[0][:12])}. Used by short-term snapshots: {', '.join(shorts[p['short_term_plan']] for _,p in uses)}."]
        lines+=['','### Short-term plans and pilot behavior']
        seen=set()
        for number,(pid,p) in enumerate(selected,1):
            sid=shorts[p['short_term_plan']];lid=longs[p['long_term_plan']];decisions=mapped[pid]
            lines+=['',f'#### Snapshot {number}: {sid} with {lid}','',f"Planner input was frozen after {p['source_session']['accepted_prefix_count']} accepted decisions. Long-term disposition: **{p['long_term_action'].upper()}**. {link(directory/'plans'/(pid+'.json'),'Exact snapshot')}.",'',f"Planner’s long-term rationale: {p.get('long_term_rationale') or '(none)'}",'']
            if sid not in seen:lines += [quote(p['short_term_plan'])];seen.add(sid)
            else:lines += [f'Short-term prose unchanged: see {sid} above.']
            lines+=['',f"Accepted decisions tied to this exact plan: {', '.join(r['decision_id'] for r in decisions) or 'none — publication is not evidence of pilot use' }."]
            for path,binding in approvals.get(pid,[]):
                approval=binding['approval'];steps={step['id']:step for step in p.get('action_sequence',[])}
                steps.update({step['id']:step for step in approval.get('add',[])})
                executed=[r for r in decisions if r.get('auxiliary_payload',{}).get('batch',{}).get('id')==path.stem]
                lines+=['','**Explicit pilot batch response** — '+link(path,path.stem[:12]),'',
                    'Approved execution order: '+(', '.join(approval.get('approve',[])) or 'none')+'.',
                    'Rejected proposed items: '+(', '.join(approval.get('reject',[])) or 'none')+'.',
                    'Pilot additions: '+(', '.join(step['id'] for step in approval.get('add',[])) or 'none')+'.',
                    'Resume after opponents only pass: '+str(approval.get('resume_after_passes',False))+'.','']
                for key in approval.get('approve',[])+approval.get('reject',[]):
                    step=steps.get(key,{})
                    lines += [f"- `{key}`: {step.get('phase','')} / {step.get('kind','')} — `{compact(step.get('choice'))}`. Original item rationale: {step.get('rationale','(none)')} Snooze policy: `{compact(step.get('scheduler'))}`."]
                if approval.get('overrides'):lines+=['','Pilot overrides: `'+compact(approval['overrides'])+'`.']
                lines+=['','Executed batch items: '+(', '.join(r['auxiliary_payload']['batch']['step']+' at '+r['decision_id'] for r in executed) or 'none')+'.']
            if decisions:
                lines+=['','<details>','<summary>Every accepted action and recorded rationale with this plan available</summary>','']
                for row in decisions:
                    batch=row.get('auxiliary_payload',{}).get('batch',{})
                    source={'adopted_planner':'Adopted planner rationale','pilot_override':'Pilot override rationale','pilot_added':'Pilot-added item rationale'}.get(batch.get('rationale_source'),'Pilot decision rationale')
                    choice=row.get('chosen_label',row.get('chosen_labels',row.get('choice_value','PASS')))
                    lines += [f"**{row['decision_id']} — {choice if isinstance(choice,str) else compact(choice)}**",'',f'{source}:',quote(row.get('rationale')),'']
                lines+=['</details>']
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'report':str(args.output.resolve()),'bytes':args.output.stat().st_size,'summary':summary},indent=2))


if __name__=='__main__':main()
