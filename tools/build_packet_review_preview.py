"""Read-only, hash-verified role snapshots for the server-side packet comparison."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import zlib
from edh_gauntlet.primitive_journal import apply
from edh_gauntlet.rules_adapter import digest
from edh_gauntlet.primitive_planning import stages
from edh_gauntlet.primitive_inspection import public_input
from edh_gauntlet.primitive_pilot_document import Document


def build(run, output, root, actor, prefix):
    binding=json.loads((run/'cohort.json').read_text())['binding']
    previous=digest(binding);state={};packets={};scanned=0
    connection=sqlite3.connect((run/'game_01/rules.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        for sequence,sha,payload in connection.execute('select seq,sha256,payload from host_journal order by seq'):
            row=json.loads(zlib.decompress(payload))
            if row['rules_commit']['sequence']>prefix:break
            if sequence!=scanned or row['previous']!=previous or digest(row)!=sha:
                raise ValueError('Historical journal chain mismatch')
            previous=sha;scanned+=1;state=apply(state,row['state'])
            claim=state.get('claim')
            if claim and claim.get('actor')==actor:packets['decider']=deepcopy(claim)
            for role,job in state.get('actors',{}).get(actor,{}).get('jobs',{}).items():
                if not job.get('input'):continue
                packet=deepcopy(job['input']);order=stages(role,job)
                packet['stage']=order[job['stage']];packet['completed_stages']=list(order[:job['stage']])
                for name,component in state['actors'][actor]['plans'].items():
                    if component.get('job_id')==job['id']:packet['plans'][name]=deepcopy(component)
                packets[role]=packet
    finally:connection.close()
    previews={}
    for role,packet in packets.items():
        original=public_input(packet);packet['_coordination_document']=1
        if role=='short_term_planner':
            from edh_gauntlet.primitive_coordination_document import planning_templates
            packet['_planning_menu']=planning_templates(packet)
        if role=='decider':
            from edh_gauntlet.primitive_decider_mana import presentation
            packet={**packet,**presentation(public_input(packet))}
        document=Document(root/'data/catalog/cards.json');text=document.render(packet,role)
        # Isolate message-delivery savings from the baseline: a repeated snapshot
        # has no new table messages but retains all current task/plan obligations.
        repeat=Document(root/'data/catalog/cards.json',document.labels).render(packet,role)
        previews[role]={'original':original,'text':text,'original_bytes':len(json.dumps(original,ensure_ascii=False,separators=(',',':')).encode()),
            'document_bytes':len(text.encode()),'repeat_document_bytes':len(repeat.encode()),
            'snapshot_decisions':packet.get('_accepted_sequence'),
            'source_kind':'hash-verified frozen role input before transport presentation; not recorded inference text'}
    result={'role_previews':previews,'review_prefix':prefix,'journal_records_verified':scanned,
            'live_game_modified':False,'examples':[{'before':{'note':'Use each role comparison above.'}}],
            'working_example':'Cards remain grouped by controller, zone and types; owner is shown when different.',
            'menu_example':'Open the decider comparison: its current decision, full response wrapper and action menu precede strategy.'}
    output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');temporary.replace(output)
    print(json.dumps({'verified_journal_records':scanned,'roles':{r:{k:v[k] for k in ('document_bytes','repeat_document_bytes','snapshot_decisions')} for r,v in previews.items()}}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--actor',default='Reaminatour');p.add_argument('--prefix',type=int,required=True)
    a=p.parse_args();build(a.run,a.output,a.root,a.actor,a.prefix)
