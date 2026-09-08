"""Rolling timing metadata; never stores prompts, deltas, choices or reasoning."""
from collections import deque
import json
import hashlib
import threading
import time
from .runtime_store import write


class Timing:
    def __init__(self,path,limit=512):
        self.path=path;self.events=deque(maxlen=limit);self.roles={};self.requests={}
        self.first=set();self.lock=threading.RLock();self.count=0
        self.usage_totals={}

    def bind(self,thread,actor,role):
        with self.lock:
            self.roles.pop(thread,None);self.roles[thread]=(actor,role)
            while len(self.roles)>32:self.roles.pop(next(iter(self.roles)))

    def record(self,event,thread=None,**fields):
        with self.lock:
            self.count+=1
            row={'event':event,'epoch':time.time(),'thread':thread,**fields}
            if thread in self.roles:row.update(zip(('actor','role'),self.roles[thread]))
            self.events.append(row)
            write(self.path,{'version':1,'total_events':self.count,'retained_events':list(self.events)})

    def observe(self,message):
        method=message.get('method','');p=message.get('params',{});thread=p.get('threadId')
        with self.lock:
            if method=='turn/started':
                self.first.discard(thread)
                self.record('turn_started',thread,turn=(p.get('turn') or {}).get('id'))
            elif method=='thread/tokenUsage/updated':
                token_usage=p.get('tokenUsage',{})
                usage=token_usage.get('last',{})
                # Notifications may repeat the previous response's last usage.
                # Keep the cumulative counter to identify these without counting
                # a replay as another cache miss or an additional inference.
                total=token_usage.get('total',{}).get('totalTokens')
                repeated=total is not None and self.usage_totals.get(thread)==total
                if total is not None:
                    self.usage_totals.pop(thread,None);self.usage_totals[thread]=total
                    while len(self.usage_totals)>32:self.usage_totals.pop(next(iter(self.usage_totals)))
                self.record('usage',thread,turn=p.get('turnId'),usage={k:v for k,v in usage.items()
                    if k in {'inputTokens','cachedInputTokens','cacheWriteInputTokens','outputTokens','reasoningOutputTokens','totalTokens'}},
                    cumulative_total_tokens=total,repeated_usage=repeated)
            elif ('delta' in method.lower() and thread and thread not in self.first):
                self.first.add(thread)
                self.record('first_output_event',thread,turn=p.get('turnId'),method=method)
            elif method=='item/tool/call':
                self.requests[message['id']]=(thread,time.time())
                while len(self.requests)>16:self.requests.pop(next(iter(self.requests)))
                args=p.get('arguments',{});queries=args.get('queries') if isinstance(args,dict) else None
                fields={'tool':p.get('tool'),'request':message['id'],'turn':p.get('turnId')}
                if isinstance(queries,list):fields['inspection_categories']=[q if q in {'continuity','sequence','roles','deck','seed','history'} else 'other' for q in queries]
                response=args.get('response',{}) if isinstance(args,dict) else {}
                if isinstance(response,dict):
                    fields['submitted_chars']=len(json.dumps(response,ensure_ascii=False,separators=(',',':')))
                    if p.get('tool')=='edh_publish':
                        fields.update(publication_stage=args.get('stage'),strategic_disposition=response.get('strategic_disposition'),
                            long_term_action=response.get('long_term_action'),proposed_actions=len(response.get('action_sequence',[])))
                        if isinstance(response.get('phase_coverage'),dict):
                            fields['phase_coverage']={phase:row.get('status') for phase,row in response['phase_coverage'].items()
                                if phase in {'precombat_main','combat','postcombat_main'} and isinstance(row,dict)}
                self.record('tool_arrived',thread,**fields)
            elif method=='turn/completed':
                self.first.discard(thread)
                self.record('turn_completed',thread,turn=(p.get('turn') or {}).get('id'),status=(p.get('turn') or {}).get('status'))
            elif method in {'item/started','item/completed'}:
                item=p.get('item',{});kind=item.get('type')
                if kind in {'reasoning','agentMessage','dynamicToolCall','contextCompaction'}:
                    self.record('model_item',thread,turn=p.get('turnId'),item=item.get('id'),kind=kind,
                        edge=method.split('/')[-1],text_chars=len(item.get('text','')) if isinstance(item.get('text'),str) else None)

    def returned(self,key,value,success):
        with self.lock:
            thread,since=self.requests.pop(key,(None,time.time()))
            validation={}
            if success and isinstance(value,dict) and value.get('role'):
                validation={'publication_stage':value.get('stage'),
                    'changed_components':value.get('changed_components',[]),
                    'strategic_review_state':value.get('strategic_review',{}).get('state'),
                    'tactical_rework':bool(value.get('tactical_rework')),
                    'publication_timing':value.get('telemetry',{})}
            if not success and isinstance(value,dict):
                message=str(value.get('error',''))
                validation={'validation_sections':[s for s in ('action_sequence','scheduler','watches','choice') if s in message],
                            'error_sha256':hashlib.sha256(message.encode()).hexdigest()}
                if any(s in message for s in ('Boundary notes','Coalesced maintenance requires','reserved boundary')):
                    validation['validation_sections'].append('boundary_notes')
                if 'A plan delta may not exceed ' in message:
                    validation['validation_sections'].append('prose_length')
                lengths=value.get('length_feedback',[])
                if lengths:
                    if 'prose_length' not in validation['validation_sections']:validation['validation_sections'].append('prose_length')
                    validation['publication_lengths']=[{k:r[k] for k in ('field','received_chars','max_chars','target_chars')}
                        for r in lengths if r.get('field') in {'standing_plan','short_term_plan','continuity','long_term_plan','long_term_rationale'}
                        and all(isinstance(r.get(k),int) for k in ('received_chars','max_chars','target_chars'))]
                stage=(value.get('next') or {}).get('stage')
                if stage in {'standing','long_term','short_term','actions'}:
                    validation['publication_stage']=stage
            self.record('tool_returned',thread,request=key,seconds=time.time()-since,
                state=value.get('state') if isinstance(value,dict) else None,success=success,
                response_chars=len(json.dumps(value,ensure_ascii=False)),**validation)
            self.first.discard(thread)
