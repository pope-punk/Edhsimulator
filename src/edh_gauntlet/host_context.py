"""Seat-private transcript checkpoints at idle host boundaries, without inference."""
import json
from copy import deepcopy
import time
from . import context_packets, pilot_handoff, planner_runtime
from .runtime_store import get, read, write


def chars(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def compact_knowledge(knowledge):
    """Keep rules and deck roles, not a second historical live-zone snapshot."""
    roles=knowledge.get('roles')
    if isinstance(roles,dict) and 'text' in roles:
        # inspection.render's roles text repeats the structured role entries.
        knowledge={**knowledge,'roles':{key:value for key,value in roles.items() if key!='text'}}
    deck=knowledge.get('last_deck_inspection')
    if not isinstance(deck,dict) or 'zones' not in deck:return knowledge
    cards={}
    for zone in deck['zones'].values():
        for row in zone.get('cards',[]):
            key=row['card_id']
            value=cards.setdefault(key,{name:row[name] for name in ('card_id','name','roles') if name in row})
            value['quantity']=value.get('quantity',0)+row.get('quantity',0)
    reference={key:value for key,value in deck.items() if key not in {'zones','text'}}
    reference['known_card_index']=list(cards.values())
    reference['state_policy']='Historical known deck composition and roles only. Current zones, controllers, UIDs and usability come from the next frozen job/decision or a fresh inspection. Unknown-card uncertainty is preserved below.'
    return {**knowledge,'last_deck_inspection':reference}


def continuity_since(directory, plan):
    if not plan:return 0
    if plan.get('publication_stage') in {'standing','long_term'} and not plan.get('short_term_plan'):
        binding=read(directory/'inputs'/(plan['batch_id']+'.json'))
        value=get(directory/'frozen_inputs',binding['input_id'])
        return value.get('rationale_interval',{}).get('after_event_seq',0)
    return plan.get('event_seq',0)


def checkpoint_knowledge(knowledge):
    """Express exact card/face duplicates once within the selected rules cache."""
    records={};changed=False
    for key,record in knowledge.get('catalog_records',{}).items():
        faces=[]
        for face in record.get('faces',[]):
            shared=[name for name,value in face.items() if name in record and record[name]==value]
            compact={name:value for name,value in face.items() if name not in shared}
            compact['inherits_card_fields']=shared
            if shared and 'inherits_card_fields' not in face and chars(compact)<chars(face):
                faces.append(compact);changed=True
            else:faces.append(face)
        records[key]={**record,'faces':faces} if 'faces' in record else record
    if not changed:return knowledge
    return {**knowledge,'catalog_records':records,
        'catalog_encoding':'A face inherits each field named in inherits_card_fields from its containing card record, with exactly the same value. All other face fields are explicit. No rules or abilities are omitted.'}


def bounded_knowledge(knowledge, budget=24000):
    """Bound re-delivered rules cache, preserving strategic memory and evidence.

    Only recently inspected definitions enter the new physical conversation.
    Evicted definitions are explicitly indexed and remain in actor-scoped original
    inspection evidence. They must never qualify as already delivered references.
    """
    result=deepcopy(compact_knowledge(knowledge))
    records=result.get('catalog_records',{})
    if chars(checkpoint_knowledge({'catalog_records':records}))<=budget:return result
    available=dict(result.get('available_card_definitions',{}))
    available.update({key:record.get('name',key) for key,record in records.items()})
    chosen={}
    for key in reversed(records):
        candidate={key:records[key],**chosen}
        if chars(checkpoint_knowledge({'catalog_records':candidate}))<=budget:chosen=candidate
    result['catalog_records']=chosen
    result['available_card_definitions']=available
    result['definition_cache_policy']=(
        'Only catalog_records contains rules retained in this conversation. '
        'available_card_definitions is an index, not remembered rules. Other original '
        'definitions remain in actor-scoped inspection evidence: inspect a card when '
        'its exact rules matter. Do not repeat initialization or re-inspect the entire deck. '
        'Seed, plans, roles and deck index are unaffected.')
    return result


class Contexts:
    def __init__(self, runner, token_limit=64000):
        self.runner = runner
        self.enabled = context_packets.enabled(runner.root, runner.game)
        self.token_limit = token_limit
        self.values = {}
        self.baselines = set()

    def path(self, actor, role):
        return self.runner.directory/'context'/f'{pilot_handoff.seat_slug(actor)}_{role}.json'

    def bind(self, thread, actor, role, *, resume=False):
        value = read(self.path(actor, role), {}) if resume else {}
        if resume and value.get('transport_version')!=2:
            raise RuntimeError('Legacy rollback context requires explicit recovery; do not silently resume it with context replacement.')
        if value and (value.get('thread') != thread or not pilot_handoff.can_resume_session(
                value['seat_session'], self.runner.root, self.runner.game, actor, self.runner.rows())):
            raise RuntimeError('Context checkpoint does not belong to this seat and accepted branch.')
        self.values[thread] = value or {'thread':thread, 'actor':actor, 'role':role,
            'agent':'/app-server/'+thread,'transport_version':2,
            'turns':0, 'delivered_chars':0, 'checkpoints':0, 'knowledge':{}, 'retained':{},'communication_policy':2}
        from .agent_architecture import enabled as split_enabled
        if resume and split_enabled(self.runner.root,self.runner.game) and value.get('communication_policy')!=2:
            self.values[thread]['communication_refresh_required']=True
        self.values[thread]['knowledge']=compact_knowledge(self.values[thread]['knowledge'])
        if value.get('baseline_required'):self.baselines.add(thread)

    def save(self, thread):
        if not self.enabled:return
        value = self.values[thread]
        measured = getattr(self.runner.server, 'usage', {}).get(thread, {}).get('last', {}).get('inputTokens')
        if measured:
            value['last_input_tokens'] = measured
        value['seat_session'] = pilot_handoff.session_descriptor(
            self.runner.root, self.runner.game, value['actor'], self.runner.rows())
        write(self.path(value['actor'],value['role']), value)

    def verify_baseline(self, thread):
        value = self.values.get(thread, {})
        usage = getattr(self.runner.server, 'usage', {}).get(thread, {})
        tokens=usage.get('first',{}).get('inputTokens',0)
        if tokens and value.get('verify_baseline'):
            if tokens>=self.token_limit:
                raise RuntimeError('Fresh checkpoint baseline exceeds context budget; stop instead of repeatedly replacing context.')
            value['verify_baseline']=False;value['baseline_input_tokens']=tokens
            self.save(thread)

    def due(self, thread):
        if self.enabled and self.values.get(thread,{}).get('communication_refresh_required'):return True
        self.verify_baseline(thread)
        value = self.values.get(thread, {})
        usage = getattr(self.runner.server, 'usage', {}).get(thread, {})
        if value.get('verify_baseline') and usage.get('last',{}).get('inputTokens'):
            raise RuntimeError('Fresh checkpoint baseline usage is unavailable; reconcile before replacing context.')
        from .agent_architecture import enabled, is_planner
        # A planner's next real packet can be much larger than a pilot return.
        # Leave room before admission, never split a running staged publication.
        reserve = self.token_limit//5 if (is_planner(value.get('role')) and
            enabled(self.runner.root,self.runner.game)) else 0
        threshold = self.token_limit-reserve
        measured = usage.get('last',{}).get('inputTokens') or value.get('last_input_tokens',0)
        return self.enabled and value.get('turns',0)>0 and (
            measured >= threshold or value.get('delivered_chars',0) >= threshold*3)

    def delivered(self, thread, packet, new_turn):
        if not self.enabled:return
        value = self.values[thread]
        value['delivered_chars'] += chars(packet)
        if new_turn:value['turns'] += 1
        if 'seat_continuity' in packet:value['memory_delivery_pending']=False
        continuity=packet.get('seat_continuity')
        if isinstance(continuity,dict) and 'inspected_knowledge' in continuity:
            value.pop('inspection_delivery_pending',None)
        if packet.get('state')=='decision':
            value['baseline_required']=False
            self.baselines.discard(thread)
        self.save(thread)

    def inspected(self, thread, result, *, delivered=None, count_delivery=True):
        """Retain static definitions once, never carry stale live objects as current."""
        if not self.enabled:return
        value = self.values[thread]
        if count_delivery:value['delivered_chars'] += chars(result if delivered is None else delivered)
        knowledge = value['knowledge']
        rows = result if isinstance(result,list) else result.get('results',[])
        for row in rows:
            payload = row.get('result',{})
            if not isinstance(payload,dict):continue
            for key, record in payload.get('catalog_records',{}).items():
                # Dictionary order tracks most recent successful delivery.
                knowledge.setdefault('catalog_records',{}).pop(key,None)
                knowledge.setdefault('catalog_records',{})[key] = record
            query = ' '.join(row.get('query', '').split()).removesuffix(' detail=full')
            if query == 'roles':
                knowledge['roles'] = {key:item for key,item in payload.items()
                                      if key not in {'catalog_records','zones','state'}}
            if query == 'deck':
                # Names/counts from an old deck inspection are historical, not
                # current-zone authority. The next job/decision supplies state.
                knowledge['last_deck_inspection'] = {key:item for key,item in payload.items()
                                                     if key != 'catalog_records'}
        value['knowledge']=compact_knowledge(knowledge)
        self.save(thread)

    def retained(self, thread, *, recovery=False):
        runner = self.runner
        if thread in runner.active or thread in runner.pending:
            raise RuntimeError('Cannot checkpoint an active turn or unanswered tool call.')
        value = self.values[thread];actor,role=value['actor'],value['role']
        if role=='diplomacy':
            return {'actor':actor,'game':runner.game,'current_state_policy':'The next frozen diplomacy input supplies the authorized brief, public facts, unread relevant messages and current offers. No private gameplay memory is retained by this role.'}
        directory = planner_runtime.directory_for(runner.root,runner.game)
        state = planner_runtime._state(directory)
        plan_id,plan = planner_runtime._latest(directory,runner.root,runner.game,actor)
        head = state.get('event_heads',{}).get(actor)
        all_events = planner_runtime.events_since(directory,head,0)
        since=continuity_since(directory,plan)
        events = [e for e in all_events if e.get('seq',0)>since]
        rows = runner.rows()
        from .planner_wakes import decision_rationales
        from . import decision_context
        known = set(value.get('retained',{}).get('known_card_names',[]))
        if plan:
            source = get(directory/'snapshots',plan['snapshot'])
            known.update(source.get('known_cards',[]))
        known.update(e['card'] for e in events if isinstance(e.get('card'),str))
        observations={}
        for event in all_events:
            if isinstance(event.get('card'),str):
                observations[(event.get('actor'),event['card'])]={key:event.get(key) for key in ('seq','turn','actor','type','card')}
        retained = {'actor':actor,'game':runner.game,'after_decision':len(rows),'plan_id':plan_id,
            'continuity':(plan or {}).get('continuity'), 'known_card_names':sorted(known),
            'last_card_observations':list(observations.values()),
            'knowledge_policy':'Card definitions and historical inspection results are retained knowledge. Never infer current zones from an old deck inspection. Reinspect uncertain current facts.'}
        if role=='decider':
            action=runner.action()
            if not recovery and action.get('actor')!=actor:raise RuntimeError('Pilot checkpoint must precede its own unclaimed decision.')
            route=read(runner.root/f'game_{runner.game:02d}'/'handoffs'/'routes'/
                       (action['dispatch']['route_id']+'.json'),{})
            if route.get('claim_id') and not recovery:raise RuntimeError('Cannot checkpoint an already claimed decision.')
            # Recovery of idle other seats must never read the active seat's
            # private packet. Their next delivery supplies their own baseline.
            request=pilot_handoff.packet_request(read(action['context'])) if action.get('actor')==actor else {}
            retained.update(decision_context_version=1,decision_context_guidance=decision_context.GUIDANCE,
                own_decisions_since_plan=decision_rationales(events,rows,actor),
                latest_decision_context=decision_context.latest_decision(runner.root,runner.game,actor,rows,
                    request.get('public_state',{}) if action.get('actor')==actor else None),
                intervening_context=decision_context.event_summary(events),
                current_state_policy='The next decision supplies the complete current board, stack, scheduler and messageboard. Historical references are not current state.')
            from . import sequence_runtime
            responses=sequence_runtime.planner_report(runner.root,runner.game,actor,rows,
                {item['decision_id'] for item in retained['own_decisions_since_plan']})
            if responses['batches']:retained['plan_responses']=responses
        else:
            # The next frozen planner job already contains all since-plan
            # evidence and the complete prior plan. Do not duplicate that job.
            retained['current_state_policy']='The next frozen planner job supplies the current board, decision contexts, own rationales and intervening observations once.'
        # Never silently truncate strategic memory to satisfy a storage budget.
        if chars(retained)+chars(checkpoint_knowledge(bounded_knowledge(value['knowledge'])))>180000:
            raise RuntimeError('Seat continuity exceeds checkpoint capacity; stop for a bounded-memory review.')
        return retained

    def checkpoint(self, thread, anchor):
        runner=self.runner;value=self.values[thread];role=value['role']
        retained=self.retained(thread)
        before = time.monotonic()
        value['retained'] = retained
        value['knowledge'] = bounded_knowledge(value['knowledge'])
        # Write intent before replacement; interrupted transport changes must
        # be reconciled explicitly, never retried automatically.
        value['checkpoint_pending']=True
        self.save(thread)
        thread=runner.rotate_context(thread)
        value.update(turns=0,delivered_chars=0,checkpoints=value['checkpoints']+1,
                     communication_policy=2,communication_refresh_required=False,
                     checkpoint_pending=False,baseline_required=role=='decider',
                     memory_delivery_pending=True,verify_baseline=True,baseline_input_tokens=None)
        value.pop('last_input_tokens',None)
        if hasattr(runner.server,'usage'):runner.server.usage.pop(thread,None)
        if role=='decider':self.baselines.add(thread)
        self.save(thread)
        metric=runner.metrics.setdefault('context_checkpoints',{'count':0,'seconds':0,'max_seconds':0})
        elapsed=time.monotonic()-before
        metric['count']+=1;metric['seconds']+=elapsed;metric['max_seconds']=max(metric['max_seconds'],elapsed)
