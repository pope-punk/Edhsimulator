"""Metadata-only workflow audit at a paused frontier; no model gameplay calls."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from edh_gauntlet import campaign
from edh_gauntlet.referee import ManualGame
from edh_gauntlet.runtime_store import locked, write, read


def report(root, game):
    root=Path(root);directory=campaign.game_dir(root,game);tape=directory/'decisions.jsonl'
    with locked(root):
        if not (root/'HOST_PAUSED.json').exists():raise ValueError('Pause the host before a replay audit.')
        digest=hashlib.sha256(tape.read_bytes()).hexdigest();rows=campaign.read_jsonl(tape)
        config=campaign._game_config_for_run(root,campaign.load_manifest(root),game)
        counts=Counter();seats=defaultdict(Counter)
        original=ManualGame._request_decision
        def observe(runtime,kind,actor,prompt,objects,*args,**kwargs):
            before=runtime.decision_counter
            result=original(runtime,kind,actor,prompt,objects,*args,**kwargs)
            if runtime.decision_counter>before:
                counts[kind]+=1
                if kind=='main_action':
                    only_side=all(isinstance(o,tuple) and o[0] in {'messageboard_open','propose_combo_loop','concede'} for o in objects)
                    seats[actor.name]['main_decisions']+=1
                    if only_side:seats[actor.name]['nonmaterial_only_main_decisions']+=1
            return result
        request_path=directory/'.workflow_audit_request.json'
        try:
            with patch.object(ManualGame,'_request_decision',observe):
                outcome=campaign._run(root,config,tape,request_path)
        finally:request_path.unlink(missing_ok=True)
        assert hashlib.sha256(tape.read_bytes()).hexdigest()==digest
        sequence=directory/'handoffs'/'sequences';stops=Counter();approved=Counter()
        for path in (sequence/'approvals').glob('*.json'):
            value=json.loads(path.read_text(encoding='utf8'))['approval']
            for field in ('approve','reject','add'):approved[field]+=len(value.get(field,[]))
            approved['batches']+=1
        execution_total=0;completed=0
        for path in (sequence/'executions').glob('*.json'):
            record=json.loads(path.read_text(encoding='utf8'));result=record['result']
            if record.get('program_id'):
                program=json.loads((sequence/'programs'/(record['program_id']+'.json')).read_text(encoding='utf8'))
                completed+=int(result['accepted']==len(program['steps']))
            else:completed+=int(result['reason']=='sequence_complete')
            stops[result['reason']]+=1;execution_total+=result['accepted']
        validity=Counter();strategic_revisions=0
        for path in (directory/'continuity'/'stage_publications').glob('*.json'):
            receipt=json.loads(path.read_text(encoding='utf8'));telemetry=receipt.get('telemetry',{})
            if telemetry.get('goal_validity'):validity[telemetry['goal_validity']]+=1
            strategic_revisions+=int(telemetry.get('goal_version_changed',False))
        snoozes=Counter(r.get('auxiliary_payload',{}).get('scheduler',{}).get('mode','unspecified') for r in rows)
        events=Counter(e['type'] for e in outcome['game'].events)
        continuity=directory/'continuity';workboard=read(continuity/'workboard.json',{})
        talk=Counter()
        for path in (continuity/'publications').glob('*.json'):
            receipt=read(path)
            if receipt.get('role')=='diplomacy':talk[receipt.get('public_post','unknown')]+=1
        posts=Counter(p['author'] for p in read(continuity/'diplomacy_posts.json',[]) if not p.get('opening_salutation'))
        return {'game':game,'accepted':len(rows),'tape_sha256':digest,
            'main_decisions_by_seat':dict(seats),'decision_kinds':dict(counts),
            'batch_reviews':dict(approved),'batch_stop_reasons':dict(stops),
            'batch_executed_decisions':execution_total,'batches_fully_executed':completed,
            'extra_decisions_beyond_one_per_batch':execution_total-approved['batches'],
            'step_approval_percent':round(100*approved['approve']/max(1,approved['approve']+approved['reject']),1),
            'scheduler_directives':dict(snoozes),'goal_validity_assessments':dict(validity),
            'strategic_revisions':strategic_revisions,
            'diplomacy_publication_results':dict(talk),'diplomacy_posts_by_seat':dict(posts),
            'diplomacy_refreshes_without_inference':sum(j.get('resolution')=='authorization_refresh_before_inference' for j in workboard.get('jobs',{}).values()),
            'suppression_events':{k:v for k,v in events.items() if 'suppress' in k or k.endswith('_auto')}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--game',type=int,default=1);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();value=report(args.cohort,args.game);write(args.output,value)
    print(json.dumps(value,indent=2))
