"""Destruction and mandatory matching sets share the normal resolution pipeline."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_program import CardProgram,Destroy,SelectAll,Selector,Move
from edh_gauntlet.rules_bundle import load_reviewed


class MassEffectTests(unittest.TestCase):
    def setUp(self):
        self.state=RulesState(('A','B'))
        self.programs=[CardProgram('c','Creature',('Creature',),power=2,toughness=2),
            CardProgram('i','Indestructible',('Creature',),power=2,toughness=2,keywords=('indestructible',)),
            CardProgram('l','Land',('Land',)),CardProgram('e','Enchantment',('Enchantment',)),
            CardProgram('a','Artifact',('Artifact',))]
        self.source=self.state.add_card('source','e','A',Zone.BATTLEFIELD)

    def test_destroy_skips_indestructible_and_commits_other_deaths_together(self):
        first=self.state.add_card('first','c','A',Zone.BATTLEFIELD)
        second=self.state.add_card('second','c','B',Zone.BATTLEFIELD)
        immune=self.state.add_card('immune','i','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(self.state,self.programs)
        kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(Destroy('selected'),)),))
        deaths=[e for e in self.state.events if e.cause=='destroy']
        self.assertEqual({first,second},{e.before.ref for e in deaths})
        self.assertEqual(1,len({e.batch for e in deaths}))
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(immune).zone)

    def test_nontargeted_matching_set_ignores_shroud_but_obeys_type_exclusions(self):
        from edh_gauntlet.rules_program import TargetRestriction
        self.programs.extend((CardProgram('s','Shroud',('Creature',),power=2,toughness=2,target_restrictions=(TargetRestriction(),)),
                              CardProgram('lc','Land Creature',('Land','Creature'),power=2,toughness=2)))
        shroud=self.state.add_card('shroud','s','A',Zone.BATTLEFIELD)
        land=self.state.add_card('land-creature','lc','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(self.state,self.programs)
        boundary=kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',),excluded_types=('Land',)),(Move('selected',Zone.HAND,controller='owner'),)),))
        self.assertIsNone(boundary)
        self.assertEqual(Zone.HAND,self.state.get(self.state.current(shroud.card_id)).zone)
        self.assertEqual(Zone.BATTLEFIELD,self.state.get(land).zone)

    def test_bounce_does_not_use_destruction_permissions(self):
        immune=self.state.add_card('immune','i','B',Zone.BATTLEFIELD)
        kernel=RulesKernel(self.state,self.programs)
        kernel.execute_for_scenario(self.source,'A',(SelectAll(Selector(Zone.BATTLEFIELD,types=('Creature',)),(Move('selected',Zone.HAND,controller='owner'),)),))
        self.assertEqual(Zone.HAND,self.state.get(self.state.current(immune.card_id)).zone)

    def test_authored_acidic_slime_targets_any_of_three_types_not_their_intersection(self):
        rows=load_reviewed();self.programs.extend(row['program'] for row in rows.values())
        eligible={self.source}
        for key in ('l','a'):eligible.add(self.state.add_card(key,key,'B',Zone.BATTLEFIELD))
        self.state.add_card('ordinary-creature','c','B',Zone.BATTLEFIELD)
        slime=self.state.add_card('slime',rows['acidic-slime']['program'].definition_id,'A',Zone.HAND)
        kernel=RulesKernel(self.state,self.programs);request=kernel.enter(slime)
        self.assertEqual('trigger_targets',request.kind)
        self.assertEqual(eligible,{o.ref for o in request.options})
        chosen=request.options[0].ref;kernel.answer(request.request_id,'A',[0])
        kernel.pass_priority('A');kernel.pass_priority('B')
        self.assertEqual(Zone.GRAVEYARD,self.state.get(self.state.current(chosen.card_id)).zone)

    def test_authored_whelming_wave_moves_all_nonexempt_creatures_in_one_batch(self):
        rows=load_reviewed();self.programs.extend(row['program'] for row in rows.values())
        excluded=[]
        for subtype in ('Kraken','Leviathan','Octopus','Serpent'):
            self.programs.append(CardProgram(subtype,subtype,('Creature',),subtypes=(subtype,),power=2,toughness=2))
            excluded.append(self.state.add_card(subtype,subtype,'B',Zone.BATTLEFIELD))
        refs=[self.state.add_card('c'+p,'c',p,Zone.BATTLEFIELD) for p in self.state.players]
        spell=self.state.add_card('wave',rows['whelming-wave']['program'].definition_id,'A',Zone.HAND)
        kernel=RulesKernel(self.state,self.programs);kernel.stage_spell_for_scenario(spell,'A')
        kernel.pass_priority('A');kernel.pass_priority('B')
        moves=[e for e in self.state.events if e.before.ref in refs]
        self.assertEqual(2,len(moves));self.assertEqual(1,len({e.batch for e in moves}))
        self.assertTrue(all(e.after.zone==Zone.HAND and e.after.owner==e.before.owner for e in moves))
        self.assertTrue(all(self.state.get(ref).zone==Zone.BATTLEFIELD for ref in excluded))
