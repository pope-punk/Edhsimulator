import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from edh_gauntlet import engine,referee,decision_selection

class SelectionBatchTests(unittest.TestCase):
    def game(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(referee.ManualGame,'mulligan'):
            g=referee.ManualGame(1,1,Path(tmp.name),selection_batch_after=0,
                decision_tape=referee.DecisionTape(Path(tmp.name)/'tape.jsonl'),
                decision_surface_revision=6,capture_event_state=False,capture_decision_state=False)
        for p in g.players.values():p.battlefield=[];p.hand=[];p.graveyard=[];p.library=[]
        g.scheduler.before_decision=Mock(return_value=False)
        g.scheduler.accept=Mock()
        return g,g.players['Omo']

    def test_exact_bounds_and_group_limits(self):
        exact={'options':['a','b','c'],'min_selected':2,'max_selected':2}
        for bad in ([],[0],[0,1,2]):
            with self.assertRaises(ValueError):decision_selection.validate_count(exact,bad)
        decision_selection.validate_count(exact,[2,0])
        grouped={'options':['a','b','c'],'selection_groups':['A','A','B'],'max_per_group':1}
        with self.assertRaises(ValueError):decision_selection.validate_count(grouped,[0,1])
        decision_selection.validate_count(grouped,[0,2])

    def test_ordered_answer_survives_tape_replay(self):
        g,p=self.game();g.decision_tape.script={'G01-D0001':{'choice_indexes':[2,0,1]}}
        chosen=g._request_selection('test_order',p,'Order all.', ['a','b','c'],str,minimum=3,maximum=3,ordered=True)
        self.assertEqual(chosen,['c','a','b'])

    def test_malformed_tape_rejected(self):
        for indexes in ([0],[0,1,2],[0,0]):
            g,p=self.game();g.decision_tape.script={'G01-D0001':{'choice_indexes':indexes}}
            with self.assertRaises(ValueError):g._request_selection('test',p,'Choose two.',['a','b','c'],str,minimum=2,maximum=2)

    def test_trigger_batch_preserves_controller_and_resolution_order(self):
        g,p=self.game();other=g.players['Elenda'];resolved=[]
        g._request_selection=Mock(side_effect=lambda kind,actor,prompt,objects,*a,**k:list(reversed(objects)))
        g.react_to_abilities=Mock();g.priority_window=Mock();g.check_sba=Mock();g.check_ream_combo=Mock()
        triggers=[{'controller':owner,'source':label,'label':label,'resolve':lambda label=label:resolved.append(label)}
                  for owner,label in [(p,'A'),(p,'B'),(p,'C'),(other,'D')]]
        g.resolve_simultaneous_triggers('test',triggers,starter=p)
        g._request_selection.assert_called_once()
        self.assertIs(g._request_selection.call_args.args[1],p)
        self.assertEqual(resolved,['D','A','B','C'])
        self.assertTrue(g._request_selection.call_args.kwargs['ordered'])

    def test_grasp_groups_targets_by_opponent(self):
        g,p=self.game();other=g.players['Elenda']
        other.battlefield=[engine.Perm(str(i),'Sol Ring',other.name,other.name) for i in range(2)]
        source=engine.Perm('grasp','Grasp of Fate',p.name,p.name);p.battlefield=[source]
        g._dispatch_etb_triggers=Mock()
        with self.assertRaises(referee.NeedDecision) as caught:g.grasp_of_fate_etb(p,source)
        request=caught.exception.request
        self.assertEqual(request['selection_groups'],[other.name,other.name])
        with self.assertRaises(ValueError):decision_selection.validate_count(request,[0,1])

    def test_brainstorm_putback_order(self):
        g,p=self.game();cards=[engine.CardObj(str(i),engine.CARDDEF['Forest']) for i in range(3)];p.hand=cards[:]
        g.draw=Mock();g._request_selection=Mock(return_value=[cards[2],cards[0]])
        g.resolve_spell(p,engine.CardObj('spell',engine.CARDDEF['Brainstorm']))
        self.assertEqual(p.library,[cards[2],cards[0]]);self.assertEqual(p.hand,[cards[1]])
        self.assertTrue(g._request_selection.call_args.kwargs['ordered'])

    def test_finale_still_exiles_itself_after_batched_untap(self):
        g,p=self.game();spell=engine.CardObj('spell',engine.CARDDEF['Finale of Revelation'])
        land=engine.Perm('land','Forest',p.name,p.name,tapped=True);p.battlefield=[land]
        g.draw=Mock();g._request_selection=Mock(return_value=[land]);g.resolve_spell(p,spell,10)
        self.assertFalse(land.tapped);self.assertIn(spell,p.exile)

    def test_gifts_zero_and_distinct_names(self):
        g,p=self.game();p.library=[engine.CardObj(str(i),engine.CARDDEF['Forest']) for i in range(2)]
        with self.assertRaises(referee.NeedDecision) as caught:g.resolve_gifts(p)
        request=caught.exception.request
        self.assertTrue(request['allow_pass'])
        with self.assertRaises(ValueError):decision_selection.validate_count(request,[0,1])
        g._request_selection=Mock(return_value=[]);g.resolve_gifts(p)
        self.assertEqual(len(p.library),2);self.assertFalse(p.hand);self.assertFalse(p.graveyard)

    def test_cleanup_discards_once_to_exact_hand_size(self):
        g,p=self.game();p.hand=[engine.CardObj(str(i),engine.CARDDEF['Forest']) for i in range(12)]
        chosen=p.hand[:5];g._request_selection=Mock(return_value=chosen)
        g.end_step_triggers=Mock();g.observe_priority_boundary=Mock();g.priority_window=Mock()
        g.cleanup(p)
        g._request_selection.assert_called_once();self.assertEqual(len(p.hand),7);self.assertEqual(p.graveyard,chosen)
        self.assertEqual(g._request_selection.call_args.kwargs['minimum'],5)

    def test_existing_game_does_not_inherit_fresh_manifest_binding(self):
        from edh_gauntlet import campaign
        from edh_gauntlet.runtime_store import write
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        manifest={'target_games':1,'seed_start':1,'max_rounds':10,'decision_surface_revision':6,'selection_batch_after':0}
        write(root/'game_01/game_config.json',{'decision_surface_revision':6})
        self.assertNotIn('selection_batch_after',campaign._game_config_with_bound_surface(root,manifest,1))
        write(root/'game_01/game_config.json',{'decision_surface_revision':6,'selection_batch_after':20})
        self.assertEqual(campaign._game_config_with_bound_surface(root,manifest,1)['selection_batch_after'],20)

    def test_symbolic_selections_validate_resolved_indexes(self):
        from edh_gauntlet.sequence_contract import match
        request={'kind':'test','phase':'main','allow_pass':True,'multi_select':True,
                 'options':['a','b','c'],'symbolic_options':[{'value':{'uid':str(i)}} for i in range(3)],
                 'selection_groups':['A','A','B'],'max_per_group':1,'max_selected':2}
        def step(ids):return {'kind':'test','phase':'main','choice':[{'uid':str(i)} for i in ids]}
        self.assertEqual(match(step([2,0]),request),[2,0])
        with self.assertRaises(ValueError):match(step([0,1]),request)
