import unittest
from edh_gauntlet.diplomacy import duplicate_post

class DuplicateMessageTests(unittest.TestCase):
    def setUp(self):
        self.address={'kind':'generic','pilots':[]}
        self.posts=[{'message_id':'original','author':'A','text':'Hold the line.','address':self.address}]
        self.row={'actor':'A','text':'  HOLD  the\nline. '}
    def test_whitespace_case_and_same_batch_history(self):
        self.assertEqual(duplicate_post(self.posts,self.row,self.address),'original')
        self.assertIsNone(duplicate_post([],self.row,self.address))
    def test_other_speakers_audiences_replies_and_distinct_text_survive(self):
        for changes in ({'actor':'B'},{'text':'Attack now.'},{'reply_to':'another-message'}):
            self.assertIsNone(duplicate_post(self.posts,{**self.row,**changes},self.address))
        self.assertIsNone(duplicate_post(self.posts,self.row,{'kind':'pilot','pilots':['B']}))
    def test_new_typed_commitments_are_never_silently_discarded(self):
        for key in ('offers','accept_offer_ids','withdraw_offer_ids'):
            self.assertIsNone(duplicate_post(self.posts,{**self.row,key:['new']},self.address))

    def test_flush_drains_duplicate_without_replay_wakes_or_retry_debt(self):
        import tempfile
        from pathlib import Path
        from contextlib import ExitStack
        from unittest.mock import patch
        from edh_gauntlet import diplomacy,planner_runtime,pilot_handoff,campaign
        from edh_gauntlet.runtime_store import read,write,identity
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);d=root/'game_01/continuity';current={'content':'authorized'}
            prior={**self.posts[0],'source_session':{'key':'valid'}}
            row={**self.row,'actor':'A','source_session':{'key':'valid'},'brief_id':identity(current),'brief':{},
                 'offers':[],'accept_offer_ids':[],'withdraw_offer_ids':[],'disclosure_ids':['line'],'requires_public_post':True}
            write(d/'diplomacy_posts.json',[prior]);write(d/'diplomacy_outbox.json',{'batch':row})
            write(d/'publications/batch.json',{'state':'published','public_post':'queued'})
            write(root/'NEXT_ACTION.json',{'next_action':{'kind':'dispatch_pilot','game':1,'dispatch':{'route_id':'route'}}})
            stack.enter_context(patch.object(diplomacy,'diplomacy_enabled',return_value=True))
            stack.enter_context(patch.object(diplomacy.components,'directory',return_value=d))
            stack.enter_context(patch.object(diplomacy.components,'recover'))
            stack.enter_context(patch.object(diplomacy.components,'current',return_value={'diplomacy_brief':current}))
            stack.enter_context(patch.object(diplomacy,'get',return_value={'board':{'players':{'A':{},'B':{}}}}))
            stack.enter_context(patch.object(diplomacy,'applicable',return_value=True))
            stack.enter_context(patch.object(planner_runtime,'_state',return_value={'snapshots':{'A':'snapshot'}}))
            stack.enter_context(patch.object(planner_runtime,'_rows',return_value=[]))
            stack.enter_context(patch.object(planner_runtime,'_compatible',return_value=True))
            stack.enter_context(patch.object(pilot_handoff,'session_descriptor',return_value={'key':'valid'}))
            advance=stack.enter_context(patch.object(campaign,'advance'))
            def commit(root,game,actor,op,digest,source,writes,result):
                for path,value in writes:write(path,value)
                self.assertEqual(result['suppressed_duplicates'],{'batch':'original'})
            stack.enter_context(patch.object(diplomacy.components,'commit',side_effect=commit))
            self.assertFalse(diplomacy.flush(root,1));advance.assert_not_called()
            self.assertEqual(read(d/'diplomacy_outbox.json'),{})
            self.assertEqual(read(d/'diplomacy_posts.json'),[prior])
            self.assertEqual(read(d/'publications/batch.json')['public_post'],'duplicate_suppressed')
            self.assertFalse((d/'diplomacy_refresh.json').exists())
