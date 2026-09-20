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


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--preview',type=Path,required=True)
    p.add_argument('--prefix',type=int,required=True);p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();refresh(a.run,a.preview,a.prefix,a.root)
