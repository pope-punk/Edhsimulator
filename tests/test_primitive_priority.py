from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from edh_gauntlet.rules_program import (CardProgram, CastSpec, CostSpec, ManaCost,
    ActivatedProgram, AddMana, GainLife, AbilityProgram, EventPattern,
    GraveyardAlternativeCost, DoubleFacedProgram)
from edh_gauntlet.rules_state import RulesState, Zone
from edh_gauntlet.rules_kernel import RulesKernel
from edh_gauntlet.primitive_priority import mana_only_window
from edh_gauntlet.primitive_campaign import PrimitiveCampaign
from edh_gauntlet import primitive_actions as actions


class ManaOnlyPriorityTests(TestCase):
    def kernel(self, extra=(), zone=Zone.HAND):
        land = CardProgram('land', 'Forest', ('Land',), subtypes=('Forest',))
        state = RulesState(('A', 'B'))
        state.add_card('land', 'land', 'A', Zone.BATTLEFIELD)
        for program in extra:
            state.add_card(program.definition_id, program.definition_id, 'A', zone)
        kernel = RulesKernel(state, (land, *extra))
        kernel.open_window_for_scenario('B', 'precombat_main', 'A')
        return kernel

    def test_untapped_lands_and_sorceries_skip_without_mutation(self):
        sorcery = CardProgram('spell', 'Sorcery', ('Sorcery',), cast=CastSpec(CostSpec()))
        k = self.kernel((sorcery,))
        before = k.snapshot()
        self.assertTrue(mana_only_window(k, 'A'))
        self.assertEqual(before, k.snapshot())

    def test_affordable_instant_and_flash_keep_control_without_floating_mana(self):
        for timing, keywords in [('instant', ()), ('sorcery', ('flash',))]:
            p = CardProgram('spell', 'Spell', ('Instant',), keywords=keywords,
                            cast=CastSpec(CostSpec(ManaCost(1)), timing))
            self.assertFalse(mana_only_window(self.kernel((p,)), 'A'))

    def test_unaffordable_instant_and_ability_skip(self):
        spell = CardProgram('spell', 'Expensive instant', ('Instant',), cast=CastSpec(CostSpec(ManaCost(2)), 'instant'))
        ability = CardProgram('rock', 'Expensive ability', ('Artifact',), activated=(
            ActivatedProgram('life', CostSpec(ManaCost(2)), (GainLife(1),)),))
        self.assertTrue(mana_only_window(self.kernel((spell,)), 'A'))
        self.assertTrue(mana_only_window(self.kernel((ability,), Zone.BATTLEFIELD), 'A'))

    def test_floating_mana_is_added_to_untapped_sources(self):
        p = CardProgram('spell', 'Instant', ('Instant',), cast=CastSpec(CostSpec(ManaCost(2)), 'instant'))
        k = self.kernel((p,)); k.state.add_mana('A', ('C',))
        self.assertFalse(mana_only_window(k, 'A'))

    def test_wrong_color_is_insufficient_even_with_enough_total(self):
        p = CardProgram('spell', 'Blue instant', ('Instant',), cast=CastSpec(CostSpec(ManaCost(0, ('U',))), 'instant'))
        self.assertTrue(mana_only_window(self.kernel((p,)), 'A'))

    def test_free_alternative_and_discount_keep_control(self):
        from edh_gauntlet.rules_program import AlternativeCost
        for spec in (CastSpec(CostSpec(ManaCost(8)), 'instant', generic_reduction=7),
                     CastSpec(CostSpec(ManaCost(8)), 'instant', alternatives=(AlternativeCost('free', CostSpec()),))):
            p = CardProgram('spell', 'Discounted instant', ('Instant',), cast=spec)
            self.assertFalse(mana_only_window(self.kernel((p,)), 'A'))

    def test_alternative_mana_abilities_do_not_double_count_a_source(self):
        rock = CardProgram('rock', 'Dual rock', ('Artifact',), activated=tuple(
            ActivatedProgram(color, CostSpec(tap_source=True), (AddMana((color,)),), mana_ability=True)
            for color in ('U', 'R')))
        k = self.kernel((rock,), Zone.BATTLEFIELD)
        from edh_gauntlet.primitive_priority import _mana_bound
        total, colors = _mana_bound(k, 'A', list(k.state.objects()))
        self.assertEqual(2, total)  # Forest plus one activation of the dual rock.
        self.assertEqual(1, colors['U']); self.assertEqual(1, colors['R'])

    def test_mana_doubler_and_land_play_keep_control(self):
        from edh_gauntlet.rules_program import TappedManaReplacement
        p = CardProgram('spell', 'Instant', ('Instant',), cast=CastSpec(CostSpec(ManaCost(2)), 'instant'))
        k = self.kernel((p,))
        # Install the doubler in a fresh scenario, not by mutating a live game.
        doubler = CardProgram('double', 'Doubler', ('Enchantment',),
            tapped_mana_replacements=(TappedManaReplacement('double'),))
        state = RulesState(('A', 'B'))
        land = CardProgram('land', 'Forest', ('Land',), subtypes=('Forest',))
        for name, program, zone in [('land', land, Zone.BATTLEFIELD), ('double', doubler, Zone.BATTLEFIELD), ('spell', p, Zone.HAND)]:
            state.add_card(name, program.definition_id, 'A', zone)
        k = RulesKernel(state, (land, doubler, p)); k.open_window_for_scenario('B', 'precombat_main', 'A')
        self.assertFalse(mana_only_window(k, 'A'))
        k = self.kernel(); k.active = 'A'; k.turn_schedule = {'land_plays':0}
        k.state.add_card('hand-land', 'land', 'A', Zone.HAND)
        self.assertFalse(mana_only_window(k, 'A'))

    def test_graveyard_alternative_instant_keeps_control(self):
        p = CardProgram('spell', 'Spell', ('Instant',), cast=CastSpec(CostSpec(), 'instant',
            alternatives=(GraveyardAlternativeCost('flashback', CostSpec()),)))
        self.assertFalse(mana_only_window(self.kernel((p,), Zone.GRAVEYARD), 'A'))

    def test_modal_back_instant_keeps_control(self):
        back = CardProgram('spell:back', 'Back', ('Instant',), cast=CastSpec(CostSpec(), 'instant'))
        p = DoubleFacedProgram('spell', 'Front', ('Sorcery',), cast=CastSpec(CostSpec()), back=back, layout='modal')
        self.assertFalse(mana_only_window(self.kernel((p,)), 'A'))

    def test_non_mana_ability_and_mana_side_effect_keep_control(self):
        for ability in [ActivatedProgram('life', CostSpec(), (GainLife(1),)),
                        ActivatedProgram('mana', CostSpec(), (AddMana(('G',)), GainLife(1)), mana_ability=True),
                        ActivatedProgram('mana', CostSpec(life=1), (AddMana(('G',)),), mana_ability=True)]:
            p = CardProgram('rock', 'Rock', ('Artifact',), activated=(ability,))
            self.assertFalse(mana_only_window(self.kernel((p,), Zone.BATTLEFIELD), 'A'))

    def test_tap_trigger_keeps_control(self):
        p = CardProgram('trigger', 'Trigger', ('Enchantment',), abilities=(
            AbilityProgram('tap', EventPattern('becomes_tapped'), (GainLife(1),)),))
        self.assertFalse(mana_only_window(self.kernel((p,), Zone.BATTLEFIELD), 'A'))

    def test_own_main_and_stack_response_keep_control(self):
        p = CardProgram('spell', 'Free sorcery', ('Sorcery',), cast=CastSpec(CostSpec()))
        k = self.kernel((p,)); k.active = 'A'
        self.assertFalse(mana_only_window(k, 'A'))
        k.active = 'B'; k.stack.append({'id': 'pending-spell'})
        self.assertFalse(mana_only_window(k, 'A'))

    def test_automatic_pass_is_durable_and_old_binding_does_not_skip(self):
        with TemporaryDirectory() as tmp:
            # Initialize an offline durable campaign around the authored scenario.
            seed = PrimitiveCampaign._create(Path(tmp)/'seed', seed=93, starting_player='Omo')
            seed.close()
            # A real four-seat fixture avoids inventing production actor registrations.
            game = PrimitiveCampaign.open(Path(tmp)/'seed')
            try:
                while game.kernel.pending_choice:
                    q = game.kernel.pending_choice
                    game.submit(q.actor, 'setup:'+q.request_id, {'kind':'answer', 'revision':game.kernel.revision,
                        'request_id':q.request_id, 'indexes':[0] if q.kind=='mulligan' else []}, rationale='Fixture')
                from unittest.mock import patch
                before = game.store.committed_head()
                game.config.pop('mana_only_priority')
                with patch('edh_gauntlet.primitive_priority.mana_only_window', return_value=True):
                    self.assertFalse(actions.automatic(game))
                    game.config['mana_only_priority']=1
                    self.assertTrue(actions.automatic(game))
                self.assertEqual(before['sequence']+1, game.store.committed_head()['sequence'])
                self.assertIsNone(game.state()['claim'])
            finally:
                game.close()

    def test_fully_tapped_painlands_and_city_trigger_do_not_hold_priority(self):
        from edh_gauntlet.rules_bundle import load_reviewed
        from edh_gauntlet.rules_state import ResourcePayment
        cards=load_reviewed()
        state=RulesState(('A','B'))
        programs=[cards[key]['program'] for key in ('city-of-brass','caves-of-koilos','adarkar-wastes')]
        refs=[state.add_card(p.definition_id,p.definition_id,'A',Zone.BATTLEFIELD) for p in programs]
        k=RulesKernel(state,programs);k.open_window_for_scenario('B','precombat_main','A')
        self.assertFalse(mana_only_window(k,'A'))  # An available activation has material effects.
        state.move((),'fixture-tap',payment=ResourcePayment('A',taps=tuple(refs)))
        before=k.snapshot()
        self.assertTrue(mana_only_window(k,'A'))
        self.assertEqual(before,k.snapshot())
