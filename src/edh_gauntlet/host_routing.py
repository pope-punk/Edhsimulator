"""Bounded role routing; capacity cooldowns never make gameplay choices."""
import time

TERRA = 'gpt-5.6-terra'
SOL = 'gpt-5.6-sol'


class Routing:
    def __init__(self, *, model=None, decider=None, planner=None, clock=time.monotonic):
        self.primary = {'decider':decider or model or TERRA, 'planner':planner or model or SOL}
        self.clock = clock
        self.blocked_until = {}

    def candidates(self, role):
        if role in {'short_term_planner','long_term_planner','diplomacy'}:
            return list(dict.fromkeys([self.primary[role],TERRA,SOL]))
        if 'short_term_planner' in self.primary:return [self.primary[role],SOL if self.primary[role]==TERRA else TERRA]
        return list(dict.fromkeys([self.primary[role], *self.primary.values()]))

    def select(self, role):
        now = self.clock()
        candidates = self.candidates(role)
        for model in candidates:
            if self.blocked_until.get(model, 0) <= now:return model
        # Both unavailable: reserve the job, wait locally, then make one probe.
        return min(candidates, key=lambda model:self.blocked_until.get(model, 0))

    def delay(self, model):
        return max(0, self.blocked_until.get(model, 0) - self.clock())

    def overloaded(self, model):
        self.blocked_until[model] = self.clock() + 60

    def policy(self):
        return {'version':1, 'primary':self.primary, 'fallback':'other configured role model',
                'capacity_cooldown_seconds':60, 'max_retries_per_unanswered_turn':2,
                'requires_zero_tool_calls':True}
