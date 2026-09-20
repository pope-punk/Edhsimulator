"""Render a saved actor packet against a verified, in-memory historical engine.

SQLite is opened read-only. This never opens a campaign, dispatches a pilot,
submits to the live host, or changes any saved game state.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from edh_gauntlet.rules_adapter import RulesActorAdapter, digest
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.primitive_inspection import freeze as knowledge
from edh_gauntlet.primitive_action_menu import freeze as menu
from edh_gauntlet.primitive_pilot_document import Document
from edh_gauntlet.primitive_delivery import expand


def refresh(run, preview, prefix, root):
    value=json.loads(preview.read_text())
    config=json.loads((run/'game_01/game_config.json').read_text())
    for name,sha in config['assets'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('Frozen asset mismatch: '+name)
    db=sqlite3.connect((run/'game_01/rules.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        header=json.loads(db.execute('SELECT data FROM header WHERE id=1').fetchone()[0])
        entries=db.execute('SELECT entry,sha FROM commands WHERE seq<=? ORDER BY seq',(prefix,)).fetchall()
    finally:db.close()
    if len(entries)!=prefix:raise ValueError('Historical prefix is absent')
    definitions=tuple(r['program'] for r in load_reviewed(root).values())
    adapter=RulesActorAdapter(RulesKernel.restore(header['initial'],definitions))
    for raw,sha in entries:
        entry=json.loads(raw)
        if digest(entry)!=sha:raise ValueError('Stored record digest mismatch')
        record=entry['record']
        adapter.submit(record['actor'],record['command'])
        if adapter.records[-1]!=record:raise ValueError('Historical reconstruction diverged')
    original=value['original'];actor=original['actor']
    if original['revision']!=adapter.kernel.revision:raise ValueError('Packet/prefix revision mismatch')
    # Expand transport deltas with their checked baselines before rendering a
    # human document. Preserve original JSON separately, byte-for-byte in value.
    packet,_=expand(original)
    campaign=SimpleNamespace(kernel=adapter.kernel,store=adapter,config=config)
    packet['_knowledge']=knowledge(campaign,actor,packet['board'])
    packet['_action_menu']=menu(campaign,actor,packet)
    packet['_accepted_sequence']=prefix
    document=Document(root/'data/catalog/cards.json')
    text=document.render(packet,'decider')
    value['previous_working_text']=value.get('working_text')
    value['working_text']=text
    lands=packet['board']['zones']['battlefield'].get(actor,[])
    value['working_example']=Document(root/'data/catalog/cards.json').objects([o for o in lands if 'Land' in o['types']])
    value['menu_example']=text[text.index('## Actions'):text.index('## plans')]
    value['comparison_version']='pilot_document:1'
    value['render_source']=packet
    value['verification']={'prefix':prefix,'revision':adapter.kernel.revision,
                           'records_checked':len(adapter.records),'live_game_modified':False}
    size=len(text.encode('utf8'));old=value['stats']['original_bytes']
    value['stats'].update(working_text_bytes=size,working_text_saved_percent=round(100*(1-size/old),2))
    temp=preview.with_suffix('.json.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(preview)
    print(json.dumps({'bytes':size,'saved_percent':value['stats']['working_text_saved_percent'],'verified_prefix':prefix}))


def refresh_roles(run,preview,prefix,root):
    """Recover only this seat's historical role inputs; never dispatch work."""
    import zlib
    from edh_gauntlet.primitive_journal import apply
    from edh_gauntlet.primitive_inspection import public_input
    from edh_gauntlet.primitive_planning import stages
    value=json.loads(preview.read_text());actor=value['original']['actor']
    manifest=json.loads((run/'cohort.json').read_text())
    previous=digest(manifest['binding']);state={};inputs={};claimed_at={};original_inputs={}
    db=sqlite3.connect((run/'game_01/rules.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        for sequence,sha,blob in db.execute('SELECT seq,sha256,payload FROM host_journal ORDER BY seq'):
            row=json.loads(zlib.decompress(blob))
            if row['rules_commit']['sequence']>prefix:break
            if row['previous']!=previous or row['sequence']!=sequence or digest(row)!=sha:
                raise ValueError('Historical host journal diverged')
            previous=sha;state=apply(state,row['state'])
            seat=state.get('actors',{}).get(actor,{})
            for role,job in seat.get('jobs',{}).items():
                if not job.get('input'):continue
                packet=deepcopy(job['input']);order=stages(role,job)
                packet['stage']=order[job['stage']]
                original_inputs[role]=deepcopy(packet)
                packet['completed_stages']=list(order[:job['stage']])
                key=(role,job['id'])
                packet['_accepted_sequence']=claimed_at.setdefault(key,row['rules_commit']['sequence'])
                for name,component in seat.get('plans',{}).items():
                    if component.get('job_id')==job['id']:packet['plans'][name]=deepcopy(component)
                inputs[role]=packet
    finally:db.close()
    # The exact saved decider input was independently checked against all 895
    # engine records by refresh(); reuse that actor-scoped source here.
    inputs['decider']=deepcopy(value['render_source'])
    previews={}
    for role,packet in inputs.items():
        packet['_coordination_document']=1
        if role=='short_term_planner':
            from edh_gauntlet.primitive_coordination_document import planning_templates
            packet['_planning_menu']=planning_templates(packet)
        d=Document(root/'data/catalog/cards.json');text=d.render(packet,role)
        original=value['original'] if role=='decider' else public_input(original_inputs[role])
        raw=json.dumps(original,ensure_ascii=False,separators=(',',':'))
        previews[role]={'text':text,'original':original,'original_bytes':len(raw.encode()),
                        'document_bytes':len(text.encode()),'snapshot_decisions':packet.get('_accepted_sequence'),
                        'source_kind':'recorded inference packet' if role=='decider' else 'frozen role input before transport presentation'}
    value['role_previews']=previews
    value['coordination_version']=1
    temp=preview.with_suffix('.json.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(preview)
    print(json.dumps({role:{k:row[k] for k in ('original_bytes','document_bytes','snapshot_decisions')} for role,row in previews.items()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--preview',type=Path,required=True)
    p.add_argument('--prefix',type=int,required=True);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--roles-only',action='store_true')
    a=p.parse_args()
    if not a.roles_only:refresh(a.run,a.preview,a.prefix,a.root)
    refresh_roles(a.run,a.preview,a.prefix,a.root)
