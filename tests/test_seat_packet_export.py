import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib

spec = importlib.util.spec_from_file_location('seat_export', Path(__file__).parents[1] / 'tools/export_seat_packets.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PacketExportTests(unittest.TestCase):
    def test_scoped_lossless_rounds_and_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); run = root/'run'; game = run/'game_01'; game.mkdir(parents=True)
            sessions = root/'sessions'; sessions.mkdir(); out = root/'out'
            (run/'cohort.json').write_text(json.dumps({'active_game':1}))
            db = sqlite3.connect(game/'rules.sqlite')
            db.executescript('CREATE TABLE host_state(value TEXT); CREATE TABLE host_evidence(seq INTEGER,actor TEXT,kind TEXT,rules_seq INTEGER,payload BLOB); CREATE TABLE host_journal(seq INTEGER,payload BLOB);')
            state = {'registrations': {'Reaminatour::decider': {'thread':'seat-thread','role':'decider'}}, 'last_rules_commit': {'sequence':28,'sha256':'sealed'}}
            db.execute('INSERT INTO host_state VALUES (?)', (json.dumps(state),))
            boards = {}
            for turn in (1,4,5,17,20,21,25,28):
                board = {'revision': str(turn), 'turn': {'number':turn,'active':'Omo','phase':'precombat_main'},'stack':[]}
                boards[turn] = board
                db.execute('INSERT INTO host_evidence VALUES (?,?,?,?,?)',(turn,'Reaminatour','observation',turn,zlib.compress(json.dumps(board).encode())))
            db.execute('INSERT INTO host_evidence VALUES (?,?,?,?,?)',(100,'Reaminatour','help_answer',17,zlib.compress(json.dumps({'answer':'schema documentation'}).encode())))
            db.commit(); db.close()
            lines = []
            for turn, board in boards.items():
                lines.append({'timestamp':f'2026-09-20T00:{turn:02}:00Z','type':'turn_context','payload':{'turn_id':str(turn)}})
                p={'type':'message','role':'user','content':[{'text':json.dumps({'board':board})}]}
                lines.append({'timestamp':f'2026-09-20T00:{turn:02}:00Z','type':'response_item','payload':p})
                lines.append({'timestamp':'','type':'event_msg','payload':{'type':'user_message','message':'duplicate'}})
                lines.append({'timestamp':'','type':'response_item','payload':{'type':'reasoning','encrypted_content':'OPAQUE'}})
                lines.append({'timestamp':'','type':'response_item','payload':{'type':'custom_tool_call','name':'exec','input':'text(await tools.edh_act({rationale:"=unsafe", command:{kind:"pass"}}));'}})
            source=sessions/'rollout-seat-thread.jsonl'
            source.write_text(''.join(json.dumps(x)+'\n' for x in lines))
            (sessions/'rollout-other-seat.jsonl').write_text('Not JSON; must never read this unrelated seat')
            first=module.export(run,out,sessions)
            self.assertEqual(first['missing_transcripts'],[])
            self.assertEqual(first['decode_errors'],[])
            self.assertEqual(first['rounds'][1]['rows'],6)
            self.assertEqual(first['rounds'][5]['rows'],7)
            self.assertEqual(first['rounds'][7]['rows'],6)
            rows=list(csv.DictReader((out/'round-1.csv').read_text().splitlines()))
            self.assertEqual({r['turn #'] for r in rows},{'1','4'})
            tool=next(r for r in rows if 'edh_act' in r['type'])
            self.assertEqual(tool['rationale'],"'=unsafe")
            copy=(out/'packets'/f"{tool['record ID']}.html").read_text()
            self.assertIn('tools.edh_act',copy)
            self.assertIn('Previous packet',copy)
            before=(out/'round-1.csv').read_bytes()
            second=module.export(run,out,sessions)
            self.assertEqual(before,(out/'round-1.csv').read_bytes())
            self.assertEqual(first['accepted_prefix'],second['accepted_prefix'])
            self.assertEqual(len(list((out/'packets').glob('*.html'))),25)
            self.assertNotIn('OPAQUE',''.join(p.read_text() for p in (out/'packets').glob('*.html')))

    def test_pilot_document_and_unchanged_sections_keep_audit_context(self):
        text='# Pilot working document\n\nAccepted decision count: 895\n\n## turn\n{"number":20,"active":"Minsc & Boo","phase":"precombat_main"}\n\n## stack\n[{"name":"Ghalta, Primal Hunger","source":"S1"}]\n'
        value=next(module.objects(text))
        context=module.context_packet(value,{}, {}, {})
        self.assertEqual(895,context['sequence']);self.assertEqual(20,context['turn']['number'])
        next_text='# Pilot working document\n\nAccepted decision count: 897\n\n## turn\nUnchanged since the previous delivered input in this conversation.\n\n## stack\n[]\n'
        updated=module.context_packet(next(module.objects(next_text)),context,{}, {})
        self.assertEqual(897,updated['sequence']);self.assertEqual(context['turn'],updated['turn'])
        self.assertEqual([],updated['stack'])

    def test_delta_context_and_unknown_revision(self):
        from edh_gauntlet.rules_adapter import digest
        board={'turn':{'number':17,'phase':'end','active':'Omo'},'revision':'r1','stack':[]}
        boards={digest(board):board}
        new={**board,'revision':'r2','turn':{**board['turn'],'number':18}}
        value={'board':{'encoding':'primitive_board_delta_v1','base_id':digest(board),'board_id':digest(new),'changes':[['set',['revision'],'r2'],['set',['turn','number'],18]]}}
        context=module.context_packet(value,{},boards,{'r2':700})
        self.assertEqual(context['turn']['number'],18)
        self.assertEqual(context['sequence'],700)
        with self.assertRaises(ValueError):module.context_packet(value,{}, {}, {})


if __name__ == '__main__':unittest.main()
