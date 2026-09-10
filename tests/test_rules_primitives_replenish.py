"""Mass enchantment return composes with entry batches and Aura choices."""
import unittest
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_bundle import load_reviewed
from edh_gauntlet.rules_casting import Payment
from edh_gauntlet.rules_adapter import RulesActorAdapter


class ReplenishTests(unittest.TestCase):
    def setUp(self):
        self.programs=tuple(r['program'] for r in load_reviewed().values())+(
            CardProgram('aura','Aura',('Enchantment',),enchant=Selector(Zone.BATTLEFIELD,types=('Creature',))),
            CardProgram('host','Host',('Creature',),power=4,toughness=4,keywords=('hexproof',)),)
        self.state=RulesState(('A','B'));self.kernel=RulesKernel(self.state,self.programs)
        self.spell=self.state.add_card('replenish','catalog:replenish','A',Zone.HAND)
        for i in range(8):self.state.add_card('draw'+str(i),'catalog:forest','A',Zone.LIBRARY)

    def add(self,key,definition,actor='A',zone=Zone.GRAVEYARD):return self.state.add_card(key,definition,actor,zone)

    def cast(self):
        self.kernel.open_window_for_scenario('A');self.state.add_mana('A',('W','C','C','C'))
        self.kernel.commit_action(self.kernel.quote_cast('cast','A',self.spell),Payment((('W',1),('C',3))))
        self.drain()

    def drain(self):
        while self.kernel.stack or self.kernel.pending_choice:
            request=self.kernel.pending_choice
            if request is not None:
                if request.kind!='trigger_order':return
                self.kernel.answer(request.request_id,request.actor,tuple(range(len(request.options))))
            else:self.kernel.pass_priority(self.kernel.priority)

    def test_returns_all_and_only_owned_enchantments_in_one_batch(self):
        first=self.add('first','catalog:hardened-scales');second=self.add('second','catalog:garruk-s-uprising')
        self.add('enemy','catalog:hardened-scales','B');self.add('artifact','catalog:sol-ring')
        self.cast();events=[e for e in self.state.events if e.before.ref in {first,second}]
        self.assertEqual(2,len(events));self.assertEqual(1,len({e.batch for e in events}))
        for key in ('first','second'):self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current(key)).zone)
        for key in ('enemy','artifact'):self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(key)).zone)
        self.assertEqual((),self.state.mana_pool('A'))

    def test_returned_enchantment_creature_fires_its_inherited_entry_trigger(self):
        self.add('dog','catalog:spirited-companion');self.cast()
        self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('dog')).zone)

    def test_aura_cannot_attach_to_creature_entering_in_the_same_batch(self):
        aura=self.add('aura','aura');self.add('dog','catalog:spirited-companion');self.cast()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(aura).zone)
        self.assertIsNone(self.kernel.pending_choice);self.assertEqual(1,len(self.state.zone('A',Zone.HAND)))

    def test_aura_entry_can_enchant_opposing_hexproof_creature_without_targeting(self):
        host=self.add('host','host','B',Zone.BATTLEFIELD);self.add('aura','aura');self.cast()
        request=self.kernel.pending_choice;self.assertEqual('aura_attachment',request.kind)
        self.kernel.answer(request.request_id,'A',(0,));self.drain()
        aura=self.state.get(self.state.current('aura'));self.assertEqual(host,aura.attached_to)
        self.assertEqual('A',aura.controller);self.assertEqual('B',self.state.get(host).controller)

    def test_multiple_aura_choices_wait_for_whole_batch_and_replay(self):
        self.add('host','host',zone=Zone.BATTLEFIELD);self.add('first','aura');self.add('second','aura')
        self.add('ordinary','catalog:hardened-scales');self.cast();request=self.kernel.pending_choice
        self.kernel.answer(request.request_id,'A',(0,))
        self.assertIsNotNone(self.kernel.pending_choice)
        for key in ('first','second','ordinary'):self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(key)).zone)
        adapter=RulesActorAdapter(self.kernel);replay=RulesActorAdapter.replay(adapter.archive(),self.programs)
        request=self.kernel.pending_choice
        command={'kind':'answer','revision':self.kernel.revision,'request_id':request.request_id,'indexes':[0]}
        adapter.submit('A',command);replay.submit('A',command)
        self.assertEqual(adapter.archive(),replay.archive())
        events=[e for e in self.state.events if e.before.ref.card_id in {'first','second','ordinary'}]
        self.assertEqual(3,len(events));self.assertEqual(1,len({e.batch for e in events}))

    def test_simultaneous_return_observer_sees_other_entrants(self):
        self.add('up','catalog:garruk-s-uprising');self.add('giant','catalog:doomwake-giant');self.cast()
        # Uprising sees the 4-power Giant at entry and also passes its own intervening clause.
        self.assertEqual(2,len(self.state.zone('A',Zone.HAND)))

    def test_no_legal_aura_entry_does_not_prevent_other_enchantments_returning(self):
        aura=self.add('aura','aura');self.add('ordinary','catalog:hardened-scales');self.cast()
        self.assertEqual(Zone.GRAVEYARD,self.state.get(aura).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(self.state.current('ordinary')).zone)

    def test_empty_graveyard_resolves_and_pays_normal_cost(self):
        self.cast();self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current('replenish')).zone)
        self.assertEqual((),self.state.mana_pool('A'));self.assertIsNone(self.kernel.pending_choice)
