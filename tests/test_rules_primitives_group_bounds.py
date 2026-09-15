"""Independent group cardinalities for a single batched choice submission."""
from dataclasses import replace
import json,unittest
from edh_gauntlet.rules_choices import ChoiceRequest,Option,choice_capacity
from edh_gauntlet.rules_state import ObjectRef,RulesState,RulesViolation
from edh_gauntlet.rules_kernel import RulesKernel,_NeedsChoice

class GroupBoundsTests(unittest.TestCase):
    def request(self):
        return ChoiceRequest('choice','A','target_groups','Choose targets.',
            (Option('land:one','Land one',ref=ObjectRef('one',1),group='land'),
             Option('land:two','Land two',ref=ObjectRef('two',1),group='land'),
             Option('creature:one','Creature one',ref=ObjectRef('one',1),group='creature'),
             Option('creature:three','Creature three',ref=ObjectRef('three',1),group='creature')),
            0,2,False,False,'0:0',(('land',0,1),('creature',0,1)))

    def test_optional_domains_allow_zero_one_or_one_from_each(self):
        q=self.request()
        for indexes in ([],[0],[2],[0,2],[1,3]):self.assertEqual(tuple(indexes),q.validate('A',indexes))
        for indexes in ([0,1],[2,3],[0,0],[0,2,3],[-1]):
            with self.assertRaises(RulesViolation):q.validate('A',indexes)
        with self.assertRaises(RulesViolation):q.validate('B',[0])

    def test_same_object_can_fill_distinct_clauses_without_duplicate_indexes(self):
        q=self.request();selected=q.validate('A',[0,2]);self.assertEqual(q.options[selected[0]].ref,q.options[selected[1]].ref)
        self.assertNotEqual(q.options[selected[0]].key,q.options[selected[1]].key)

    def test_arbitrary_minimum_maximum_and_overlapping_global_bounds(self):
        q=replace(self.request(),minimum=2,maximum=3,group_bounds=(('land',2,2),('creature',0,1)))
        self.assertEqual((0,1),q.validate('A',[0,1]));self.assertEqual((0,1,2),q.validate('A',[0,1,2]))
        with self.assertRaises(RulesViolation):q.validate('A',[0,2])
        with self.assertRaises(RulesViolation):replace(q,maximum=1)
        with self.assertRaises(RulesViolation):replace(q,group_bounds=(('land',3,3),('creature',0,1)))
        self.assertEqual(3,choice_capacity(iter(q.options),group_bounds=q.group_bounds))

    def test_serialization_and_legacy_choice_behavior(self):
        q=self.request();restored=ChoiceRequest.from_json(json.loads(json.dumps(q.to_json())))
        self.assertEqual(q.to_json(),json.loads(json.dumps(q.to_json())))
        self.assertEqual(q,restored);self.assertEqual((1,3),restored.validate('A',[1,3]))
        old=q.to_json();del old['group_bounds'];old['one_per_group']=True
        legacy=ChoiceRequest.from_json(old);self.assertEqual((),legacy.group_bounds)
        self.assertEqual((0,2),legacy.validate('A',[0,2]))
        with self.assertRaises(RulesViolation):legacy.validate('A',[0,1])

    def test_malformed_and_undeclared_groups_fail_before_presentation(self):
        q=self.request()
        for bounds in ([('land',0,1)],(('land',False,1),),(('land',2,1),),(('land',0,1),('land',0,1)),(('',0,1),),(('unknown',0,1),)):
            with self.assertRaises(RulesViolation):replace(q,group_bounds=bounds)
        with self.assertRaises(RulesViolation):replace(q,one_per_group=True)
        with self.assertRaises(RulesViolation):replace(q,minimum=True)
        with self.assertRaises(RulesViolation):replace(q,options=(replace(q.options[0],group=[]),))

    def test_kernel_binds_group_constraints_and_handles_empty_optional_groups(self):
        k=RulesKernel(RulesState(('A','B')),());k.open_window_for_scenario('A');q=self.request()
        with self.assertRaises(_NeedsChoice):k._choose('group','A','target_groups','Choose.',q.options,0,2,group_bounds=q.group_bounds)
        self.assertEqual(q.group_bounds,k.pending_choice.group_bounds)
        restored=RulesKernel.restore(k.snapshot(),());self.assertEqual(k.snapshot(),restored.snapshot())
        with self.assertRaises(RulesViolation):restored.pending_choice.validate('A',[0,1])
        k=RulesKernel(RulesState(('A','B')),());k.open_window_for_scenario('A')
        self.assertEqual((),k._choose('empty','A','target_groups','Choose.',(),0,2,group_bounds=(('empty',0,1),)))
        with self.assertRaises(RulesViolation):k._choose('required','A','target_groups','Choose.',(),0,2,group_bounds=(('empty',1,1),))

if __name__=='__main__':unittest.main()
