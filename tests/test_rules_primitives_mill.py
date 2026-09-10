"""Milling uses one resumable zone batch, never individual draw actions."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState, Zone, RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel


class MillTests(unittest.TestCase):
    def make(self, replacements=()):
        self.programs=(CardProgram('source','Source',('Enchantment',),replacements=replacements),
                       CardProgram('card','Card',('Land',)))
        self.state=RulesState(('A','B'))
        self.source=self.state.add_card('source','source','A',Zone.BATTLEFIELD)
        for player in ('A','B'):
            for i in range(4):self.state.add_card(player+str(i),'card',player,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_top_cards_move_together_and_no_draw_event(self):
        self.make();self.kernel.execute_for_scenario(self.source,'A',(Mill(2),))
        self.assertEqual(['A0','A1'],[o.ref.card_id for o in self.state.zone('A',Zone.LIBRARY)])
        events=self.state.events
        self.assertEqual({'A2','A3'},{e.before.ref.card_id for e in events})
        self.assertEqual(1,len({e.batch for e in events}))
        self.assertFalse(any(e['kind'] in {'card_drawn','draw_failed'} for e in self.kernel.semantic_events))

    def test_short_and_empty_libraries_never_lose_from_milling(self):
        self.make()
        self.kernel.execute_for_scenario(self.source,'A',(Mill(100),Mill(1)))
        self.assertEqual(4,len(self.state.zone('A',Zone.GRAVEYARD)))
        self.assertEqual(('A','B'),self.state.live_players)

    def test_zero_does_not_select_whole_library(self):
        self.make();self.kernel.execute_for_scenario(self.source,'A',(Mill(0,'all'),))
        self.assertEqual((),self.state.events)

    def test_all_players_share_batch_and_opponents_excludes_controller(self):
        self.make();self.kernel.execute_for_scenario(self.source,'A',(Mill(1,'all'),))
        self.assertEqual({'A3','B3'},{e.before.ref.card_id for e in self.state.events})
        self.assertEqual(1,len({e.batch for e in self.state.events}))
        self.kernel.execute_for_scenario(self.source,'A',(Mill(2,'opponents'),))
        self.assertEqual(3,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual(1,len(self.state.zone('B',Zone.LIBRARY)))

    def test_replacement_batch_waits_and_resumes_from_checkpoint(self):
        self.make((ZoneReplacement('exile',Zone.GRAVEYARD,Zone.EXILE),
                   ZoneReplacement('hand',Zone.GRAVEYARD,Zone.HAND)))
        request=self.kernel.execute_for_scenario(self.source,'A',(Mill(2,'all'),))
        self.assertEqual('replacement_order',request.kind)
        self.assertEqual((),self.state.events)
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        choices=[]
        for kernel in (self.kernel,restored):
            actors=[]
            while kernel.pending_choice:
                request=kernel.pending_choice;actors.append(request.actor)
                self.assertEqual((),kernel.state.events)
                kernel.answer(request.request_id,request.actor,(0,))
            choices.append(actors)
        self.assertEqual(choices[0],choices[1]);self.assertEqual(['A','A','B','B'],choices[0])
        self.assertEqual(self.kernel.snapshot(),restored.snapshot())
        self.assertEqual(4,len(self.state.events));self.assertEqual(1,len({e.batch for e in self.state.events}))
        self.assertEqual(2,len(self.state.zone('A',Zone.LIBRARY)))
        self.assertEqual(2,len(self.state.zone('B',Zone.LIBRARY)))
        self.assertTrue(all(e.after.zone==Zone.EXILE for e in self.state.events))

    def test_shared_quantity_and_program_roundtrip(self):
        self.make();effect=Mill(CountObjects(Selector(Zone.BATTLEFIELD,types=('Enchantment',))))
        self.assertEqual(effect,decode(encode(effect)))
        self.kernel.execute_for_scenario(self.source,'A',(effect,))
        self.assertEqual(1,len(self.state.zone('A',Zone.GRAVEYARD)))

    def test_validation_and_mana_classification_include_fallback_mill(self):
        for effect in (Mill(-1),Mill(True),Mill(1,'invalid'),Mill(1,'target')):
            with self.assertRaises(RulesViolation):validate(CardProgram('bad','Bad',('Sorcery',),spell_effects=(effect,)))
        ability=ActivatedProgram('mana',CostSpec(tap_source=True),
            (AddMana(('C',)),IfCondition(CountCondition(Selector(Zone.BATTLEFIELD),minimum=1),(),(Mill(1),))))
        self.assertFalse(activation_is_mana(ability))

    def test_trenchpost_targets_pays_and_counts_loci_on_resolution(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_casting import Payment
        from edh_gauntlet.rules_state import PlayerRef
        programs=tuple(r['program'] for r in load_reviewed().values())
        state=RulesState(('A','B'));kernel=RulesKernel(state,programs)
        source=state.add_card('post','catalog:trenchpost','A',Zone.BATTLEFIELD)
        for i in range(5):state.add_card('card'+str(i),'catalog:forest','B',Zone.LIBRARY)
        kernel.open_window_for_scenario('A');state.add_mana('A',('C',)*3)
        quote=kernel.quote_activation('mill','A',source,'mill',(PlayerRef('B'),))
        kernel.commit_action(quote,Payment((('C',3),)))
        self.assertTrue(state.get(source).tapped);self.assertEqual((),state.mana_pool('A'))
        self.assertEqual(0,len(state.zone('B',Zone.GRAVEYARD)))
        state.add_card('new-post','catalog:trenchpost','A',Zone.BATTLEFIELD)
        state.add_card('opponent-post','catalog:trenchpost','B',Zone.BATTLEFIELD)
        while kernel.stack:kernel.pass_priority(kernel.priority)
        self.assertEqual(2,len(state.zone('B',Zone.GRAVEYARD)))

    def test_trenchpost_mana_ability_does_not_mill(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_casting import Payment
        state=RulesState(('A','B'));kernel=RulesKernel(state,tuple(r['program'] for r in load_reviewed().values()))
        source=state.add_card('post','catalog:trenchpost','A',Zone.BATTLEFIELD)
        kernel.open_window_for_scenario('A')
        kernel.commit_action(kernel.quote_activation('mana','A',source,'mana'),Payment())
        self.assertEqual((('C',1),),state.mana_pool('A'));self.assertFalse(kernel.stack)
