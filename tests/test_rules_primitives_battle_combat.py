"""Battle type forbids combat participation, including mid-combat type changes."""
import unittest
from edh_gauntlet.rules_state import RulesState,Zone,RulesViolation
from edh_gauntlet.rules_program import CardProgram,UntilEndOfTurn,ChangeTypes
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.rules_combat import uid


class BattleCombatTests(unittest.TestCase):
    def game(self,battle_owner=None):
        self.state=RulesState(('A','B'))
        self.programs=(CardProgram('body','Body',('Creature',),power=2,toughness=2),CardProgram('land','Land',('Land',)))
        self.attacker=self.state.add_card('a','body','A',Zone.BATTLEFIELD)
        self.blocker=self.state.add_card('b','body','B',Zone.BATTLEFIELD)
        for ref in (self.attacker,self.blocker):self.state.add_counters(ref,'defense',4)
        for p in self.state.players:self.state.add_card('draw'+p,'land',p,Zone.LIBRARY)
        self.kernel=RulesKernel(self.state,self.programs);self.kernel.begin_turn_for_scenario('A')
        if battle_owner:self.battle(self.attacker if battle_owner=='A' else self.blocker)
        for _ in range(4):self.pass_round()

    def pass_round(self):
        for _ in self.state.players:result=self.kernel.pass_priority(self.kernel.priority)
        return result

    def battle(self,ref,add=True):
        self.kernel.execute_for_scenario(ref,self.state.get(ref).controller,(UntilEndOfTurn('source',(ChangeTypes(add=('Battle',)) if add else ChangeTypes(remove=('Battle',)),)),))

    def attack(self):
        self.kernel.declare_attackers('A',{self.attacker:'B'},revision=self.kernel.revision)
        return self.pass_round()

    def test_battle_creature_cannot_be_declared_attacking(self):
        self.game('A');before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.declare_attackers('A',{self.attacker:'B'},revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_battle_creature_is_absent_from_block_choices_and_rejected(self):
        self.game('B');boundary=self.attack()
        self.assertFalse(any(uid(self.blocker) in rows for rows in boundary.specification['eligibility_groups'].values()))
        before=self.kernel.snapshot()
        with self.assertRaises(RulesViolation):self.kernel.declare_blockers('B',{uid(self.attacker):[uid(self.blocker)]},revision=self.kernel.revision)
        self.assertEqual(before,self.kernel.snapshot())

    def test_attacker_becoming_battle_is_removed_and_cannot_rejoin(self):
        self.game();self.attack();self.kernel.declare_blockers('B',{uid(self.attacker):[]},revision=self.kernel.revision)
        self.battle(self.attacker);self.assertEqual([],self.kernel.combat['attackers'])
        self.battle(self.attacker,False);self.assertEqual([],self.kernel.combat['attackers'])
        restored=RulesKernel.restore(self.kernel.snapshot(),self.programs)
        self.pass_round()
        for _ in restored.state.players:restored.pass_priority(restored.priority)
        self.assertEqual(self.kernel.snapshot(),restored.snapshot());self.assertEqual(40,self.state.life('B'))

    def test_blocker_becoming_battle_leaves_attacker_blocked(self):
        self.game();self.attack();self.kernel.declare_blockers('B',{uid(self.attacker):[uid(self.blocker)]},revision=self.kernel.revision)
        self.battle(self.blocker)
        self.assertEqual([],self.kernel.combat['blocks'][uid(self.attacker)])
        self.assertIn(uid(self.attacker),self.kernel.combat['blocked'])
        self.pass_round()
        self.assertEqual(40,self.state.life('B'))
        self.assertEqual(0,self.state.get(self.attacker).damage_marked);self.assertEqual(0,self.state.get(self.blocker).damage_marked)

    def test_transient_type_change_during_one_resolution_permanently_removes_attacker(self):
        for changes in ((ChangeTypes(add=('Battle',)),ChangeTypes(remove=('Battle',))),
                        (ChangeTypes(add=('Artifact',),remove=('Creature',)),ChangeTypes(add=('Creature',),remove=('Artifact',)))):
            with self.subTest(changes=changes):
                self.game();self.attack();self.kernel.declare_blockers('B',{uid(self.attacker):[]},revision=self.kernel.revision)
                self.kernel.execute_for_scenario(self.attacker,'A',tuple(UntilEndOfTurn('source',(change,)) for change in changes))
                self.assertEqual({'Creature'},set(self.kernel.effective(self.attacker).types))
                self.assertEqual([],self.kernel.combat['attackers'])
                self.pass_round();self.assertEqual(40,self.state.life('B'))
