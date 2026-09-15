"""Damage-received triggers observe simultaneous batches before lethal cleanup."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_bundle import load_reviewed


class DamageReceivedTests(unittest.TestCase):
    def game(self,extra=()):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(CardProgram('body','Body',('Creature',),power=2,toughness=2),)+extra
        self.state=RulesState(('A','B'));self.priest=self.state.add_card('priest','catalog:high-priest-of-penance','A',Zone.BATTLEFIELD)
        self.sources=tuple(self.state.add_card('source'+str(i),'body','B',Zone.BATTLEFIELD) for i in range(2))
        self.rock=self.state.add_card('rock','catalog:sol-ring','B',Zone.BATTLEFIELD)
        self.land=self.state.add_card('land','catalog:forest','B',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def hit(self,amounts):
        self.kernel._deal_damage(tuple((self.state.get(self.sources[i%2]),self.priest,n) for i,n in enumerate(amounts)))

    def test_simultaneous_sources_trigger_once_with_total_amount(self):
        self.game();self.hit((2,3))
        self.assertEqual(1,len(self.kernel.pending_triggers));self.assertEqual(5,self.kernel.pending_triggers[0]['values']['event_amount'])
        events=[e for e in self.kernel.semantic_events if e['kind']=='damage_received']
        self.assertEqual(1,len(events));self.assertEqual(5,events[0]['amount'])

    def test_separate_batches_trigger_separately_and_zero_does_not(self):
        self.game();self.hit((0,));self.assertEqual([],self.kernel.pending_triggers)
        self.hit((1,));self.hit((1,));self.assertEqual(2,len(self.kernel.pending_triggers))

    def test_lethal_trigger_survives_death_and_optional_resolution_restores(self):
        for choose,expected in ((0,Zone.GRAVEYARD),(1,Zone.BATTLEFIELD)):
            self.game();self.hit((1,));request=self.kernel.advance()
            self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('priest')).zone)
            self.assertEqual('trigger_targets',request.kind);self.assertNotIn(self.land,[o.ref for o in request.options])
            index=next(i for i,o in enumerate(request.options) if o.ref==self.rock)
            self.kernel.answer(request.request_id,'A',[index])
            self.kernel.pass_priority('A');request=self.kernel.pass_priority('B');self.assertEqual('may',request.kind)
            restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
            for k in (self.kernel,restored):k.answer(request.request_id,'A',[choose])
            self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(expected,self.state.get(self.state.current('rock')).zone)

    def test_generic_event_amount_binding_and_type_filter(self):
        observer=CardProgram('observer','Observer',('Enchantment',),abilities=(AbilityProgram('received',EventPattern('damage_received',types=('Creature',)),(GainLife(EventAmount()),)),))
        self.game((observer,));self.state.add_card('observer','observer','A',Zone.BATTLEFIELD)
        self.kernel._deal_damage(((self.state.get(self.sources[0]),self.sources[1],1),))
        self.assertEqual(1,len(self.kernel.pending_triggers));self.assertEqual('received',self.kernel.pending_triggers[0]['ability']['ability_id'])
        self.kernel.advance()
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual(41,self.state.life('A'))

    def test_copied_definition_inherits_received_damage_trigger(self):
        self.game();copy=self.state.add_card('copy','body','A',Zone.HAND)
        event=self.state.move((ZoneMove(copy,Zone.BATTLEFIELD,copied_definition='catalog:high-priest-of-penance'),),'fixture-copy')[0]
        self.kernel._deal_damage(((self.state.get(self.sources[0]),event.after.ref,1),))
        self.assertEqual(1,len(self.kernel.pending_triggers));self.assertEqual('copy',self.kernel.pending_triggers[0]['source']['ref']['card_id'])

    def test_printed_cost_and_entry_do_not_create_damage_trigger(self):
        self.game();spell=self.state.add_card('cast-priest','catalog:high-priest-of-penance','A',Zone.HAND)
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','B'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',spell),Payment((('W',1),('B',1))))
        while self.kernel.stack:self.kernel.pass_priority(self.kernel.priority)
        self.assertEqual((),self.state.mana_pool('A'));self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('cast-priest')).zone)
        self.assertFalse(self.kernel.pending_triggers)
