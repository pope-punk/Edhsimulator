"""An event's type view is shared across matching observers and read only if needed."""
import unittest
from unittest.mock import patch
from edh_gauntlet.rules_program import *
from edh_gauntlet.rules_state import RulesState,Zone,ZoneMove
from edh_gauntlet.rules_kernel import RulesKernel


class AnnouncementQueryTests(unittest.TestCase):
    def game(self,types):
        observer=CardProgram('observer','Observer',('Artifact',),abilities=(AbilityProgram('watch',EventPattern('ability_activated',types=types),(GainLife(1),)),))
        self.programs=(observer,CardProgram('body','Body',('Creature',),power=2,toughness=2))
        self.state=RulesState(('A','B'));ref=self.state.add_card('body','body','A',Zone.BATTLEFIELD)
        self.source=self.state.get(ref)
        for i in range(12):self.state.add_card('observer'+str(i),'observer','A',Zone.BATTLEFIELD)
        self.kernel=RulesKernel(self.state,self.programs)

    def test_unfiltered_observers_do_not_query_event_types(self):
        self.game(())
        with patch.object(self.kernel,'effective',wraps=self.kernel.effective) as effective:
            self.kernel._collect_announcement('ability_activated',self.source,'A')
        self.assertEqual(0,effective.call_count);self.assertEqual(12,len(self.kernel.pending_triggers))

    def test_filtered_observers_share_one_view_and_preserve_occurrences(self):
        self.game(('Creature',))
        with patch.object(self.kernel,'effective',wraps=self.kernel.effective) as effective:
            self.kernel._collect_announcement('ability_activated',self.source,'A')
        self.assertEqual(1,effective.call_count);self.assertEqual(12,len(self.kernel.pending_triggers))
        self.assertEqual(12,len({row['source']['ref']['card_id'] for row in self.kernel.pending_triggers}))

    def test_departed_source_fallback_is_computed_once_and_filters_still_apply(self):
        self.game(('Creature',));self.state.move((ZoneMove(self.source.ref,Zone.GRAVEYARD),),'sacrifice')
        with patch.object(self.kernel,'effective',wraps=self.kernel.effective) as effective:
            self.kernel._collect_announcement('ability_activated',self.source,'A',previous_types=('Creature',))
        self.assertEqual(1,effective.call_count);self.assertEqual(12,len(self.kernel.pending_triggers))
        self.kernel.pending_triggers.clear()
        self.kernel._collect_announcement('ability_activated',self.source,'A',previous_types=('Artifact',))
        self.assertEqual([],self.kernel.pending_triggers)
