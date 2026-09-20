"""Actor-scoped working documents and reversible transport labels.

Original inputs and accepted engine commands remain unchanged in evidence.
Labels live in one physical conversation, with action menus bound to one input.
"""
from collections import defaultdict
from copy import deepcopy
import json
import re
from .catalog import load_catalog
from .rules_state import RulesViolation

DEFAULTS = {'commander':False, 'token':False, 'tapped':False, 'phased':False,
            'damage':0, 'counters':{}, 'attached_to':None, 'power':None, 'toughness':None,
            'keywords':[], 'colors':[], 'subtypes':[], 'supertypes':[]}
OMIT = {'claim_id', 'job_id', 'snapshot', 'revision', 'context_handling', 'evidence_through',
        'evidence_after', 'definition_id', 'rules_id', 'board_id', 'base_id', 'brief_id', 'short_term_id'}
LITERALS = {'kind','node','phase','zone','face','timing','name','label','mode','seat',
            'actor','controller','owner','relation','color','symbol','status','encoding','type'}
PROSE = {'rationale','reason','question','intended_action','long_term_plan','short_term_plan',
         'proposal_text','message','text','objective','disclosure_limits','commitment_limits',
         'intent','continuity','long_term_invalid_reason','explanation','recommended_action'}


def compact(value): return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
def ref_key(value): return compact(dict(sorted(value.items())))
def is_ref(value): return isinstance(value,dict) and set(value)=={'card_id','incarnation'}
def is_object(value): return isinstance(value,dict) and is_ref(value.get('ref')) and 'types' in value and 'zone' in value


class Labels:
    def __init__(self):
        self.forward={}; self.reverse={}; self.counters=defaultdict(int); self.actions={}; self.sections={}; self.proposals={}; self.object_names={}; self.coordination=False

    def label(self, value, prefix='R'):
        key=ref_key(value) if is_ref(value) else compact(value)
        if key not in self.forward:
            self.counters[prefix]+=1
            alias=prefix+str(self.counters[prefix])
            self.forward[key]=alias; self.reverse[alias]=deepcopy(value)
        return self.forward[key]

    def encode(self, value, key=""):
        if key in PROSE or key in LITERALS and isinstance(value,str):return deepcopy(value)
        if is_ref(value): return self.label(value, 'C')
        if isinstance(value, list): return [self.encode(v,key) for v in value]
        if isinstance(value, dict):
            result={}
            for k,v in value.items():
                if k in OMIT or k.startswith('_') or self.coordination and k in {'plan_refs','goal_id','assessed_goal','sha256'}: continue
                if (k in ('id','brief_id','proposal_id','request_id','hold_id','step_id','ability_id','mode_id','cost_id','uid','owned_card') or self.coordination and k in ('reply_to','authorization_id','negotiation_id')) and isinstance(v,str):
                    result[k]=self.label(v)
                else: result[self.forward.get(compact(k),k)]=self.encode(v,k)
            return result
        if isinstance(value,str): return self.forward.get(compact(value),value)
        return value

    def decode(self, value, key=''):
        if key in PROSE or key in LITERALS and isinstance(value,str): return deepcopy(value)
        if isinstance(value, list): return [self.decode(v,key) for v in value]
        if isinstance(value, dict):
            if key=='command': return self.command(value)
            result={}
            for k,v in value.items():
                if re.fullmatch(r'P[0-9]+',k) and k not in self.proposals:raise RulesViolation('Unknown or expired proposal label')
                real=self.reverse.get(k,k)
                if isinstance(real,dict):
                    if key!='assignments': raise RulesViolation('Object labels cannot be used as keys here')
                    real=real['card_id']+'@'+str(real['incarnation'])
                if key=='assignments' and isinstance(v,list):
                    decoded=[self.decode(x) for x in v]
                    result[real]=[x['card_id']+'@'+str(x['incarnation']) if is_ref(x) else x for x in decoded]
                else: result[real]=self.decode(v,k)
            return result
        if isinstance(value,str):
            if re.fullmatch(r'P[0-9]+',value) and value not in self.proposals:
                raise RulesViolation('Unknown or expired proposal label; use the current proposal')
            resolved=deepcopy(self.reverse.get(value,value))
            return resolved['card_id'] if key=='owned_card' and is_ref(resolved) else resolved
        return deepcopy(value)

    def command(self, value):
        value=deepcopy(value)
        action=value.pop('action',None)
        if action is not None:
            if action not in self.actions: raise RulesViolation('Unknown or expired action label; use the current action menu')
            base=deepcopy(self.actions[action])
            if set(value)&set(base): raise RulesViolation('Do not override the identity of a menu action; select another action')
            value={**base,**value}
        if 'target' in value:
            if 'targets' in value: raise RulesViolation('Supply target or targets, not both')
            value['targets']=[value.pop('target')]
        result=self.decode(value)
        if result.get('kind') in ('cast','activate'):
            result.setdefault('targets',[]); result.setdefault('x_value',0)
        return result


def heading(types):
    order={'Kindred':0,'Tribal':0,'Artifact':1,'Enchantment':2,'Planeswalker':3,'Battle':4,'Creature':5,'Land':6}
    names=sorted(types,key=lambda x:(order.get(x,7),x))
    plurals={'Creature':'Creatures','Land':'Lands','Artifact':'Artifacts','Enchantment':'Enchantments',
             'Planeswalker':'Planeswalkers','Instant':'Instants','Sorcery':'Sorceries','Battle':'Battles'}
    return ' '.join(names[:-1]+[plurals.get(names[-1],names[-1])]) if names else 'Other'


class Document:
    def __init__(self, catalog_path, labels=None):
        self.labels=deepcopy(labels) if labels else Labels()
        self.faces={f.name:f for c in load_catalog(catalog_path) for f in c.faces}
        self.printed=set()

    def objects(self, objects):
        groups=defaultdict(list);positions=defaultdict(int)
        for obj in objects:
            location=(obj.get('owner'),obj['zone']);i=positions[location];positions[location]+=1
            groups[(obj.get('controller',obj.get('owner')),obj['zone'],tuple(obj['types']))].append((i,obj))
        lines=[]
        for (seat,zone,types),rows in groups.items():
            lines.append(f'### {seat}’s {zone.replace("_"," ")} — {heading(types)}')
            for i,obj in rows:
                details={}
                for k,v in obj.items():
                    if k in ('ref','name','types','zone','controller','definition_id'): continue
                    if k=='owner' and v==seat or k=='face' and v=='front': continue
                    if k in DEFAULTS and type(v) is type(DEFAULTS[k]) and v==DEFAULTS[k]: continue
                    if k=='copy_cast': continue # printed casting rules below, not a duplicate engine program
                    details[k]=v
                position=f' (position {i+1})' if zone not in ('battlefield','hand') else ''
                lines.append(f"- {self.labels.label(obj['ref'],'C')} — {obj['name']}{position}"+
                             ('; '+compact(self.labels.encode(details)) if details else ''))
        return '\n'.join(lines)

    def oracle_programs(self,value):
        if isinstance(value,list): return [self.oracle_programs(v) for v in value]
        if not isinstance(value,dict): return value
        result={k:self.oracle_programs(v) for k,v in value.items()}
        program=value.get('program')
        if isinstance(program,dict) and program.get('name') in self.faces:
            face=self.faces[program['name']]
            result.pop('program',None)
            result['printed_rules']={'name':face.name,'mana_cost':face.mana_cost,'oracle_text':face.oracle_text}
            # An object inspection retains executable activation descriptors for
            # planner-authored exceptional payments. Default documents do not.
        return result

    def value(self,value):
        value=self.oracle_programs(value)
        if is_object(value):
            self.labels.object_names[self.labels.label(value['ref'],'C')]=value['name']
            return self.objects([value])
        if isinstance(value,list) and value and all(is_object(x) for x in value): return self.objects(value)
        def contains(v):
            return is_object(v) or isinstance(v,dict) and any(contains(x) for x in v.values()) or isinstance(v,list) and any(contains(x) for x in v)
        if contains(value):
            if isinstance(value,dict): return '\n'.join('### '+k.replace('_',' ')+'\n'+self.value(v) for k,v in value.items() if k not in OMIT and not k.startswith('_'))
            return '\n'.join(self.value(v) for v in value)
        return compact(self.labels.encode(value))

    def section(self,key,text,*,repeat=False):
        previous=self.labels.sections.get(key)
        self.labels.sections[key]=text
        if previous==text and not repeat:
            return 'Unchanged since the previous delivered input in this conversation.'
        return text

    def render(self,packet,role):
        self.labels.coordination=packet.get('_coordination_document')==1
        board=packet.get('board',{})
        # Register stack references first. S labels mean exact spell sources,
        # never frame IDs; two spell incarnations never share a label.
        for frame in board.get('stack',[]):
            if frame.get('kind')=='spell' and is_ref(frame.get('source')): self.labels.label(frame['source'],'S')
        def names(node):
            if isinstance(node,dict):
                ref=node.get('ref',node.get('source'))
                if is_ref(ref) and isinstance(node.get('name'),str):
                    label=self.labels.label(ref,'C')
                    self.labels.object_names[label]=node['name']
                for child in node.values():names(child)
            elif isinstance(node,list):
                for child in node:names(child)
        names(board)
        # Register operational identities before rendering references to them.
        self.labels.encode(packet)
        self.labels.actions={}
        lines=['# Pilot working document',
               'Labels refer to this conversation’s exact objects, not names. Use current action labels only. Unchanged sections refer only to the previous delivered input in this same conversation; first inputs are self-contained. '
               'Headings supply controller, zone and all card types. Owner appears only when different. '
               'Omitted object defaults: false flags, zero damage, no counters/attachment, no listed keywords/colors/subtypes/supertypes; front face. '
               'Zero power/toughness, life, costs and choice counts are retained. Oracle text describes printed rules; current modifications and engine validation govern play.',
               '## Current decision\n'+self.value(board.get('decision',{}))]
        if '_accepted_sequence' in packet:lines.insert(1,'Accepted decision count: '+str(packet['_accepted_sequence']))
        handled=set()
        if packet.get('_coordination_document')==1:
            from .primitive_coordination_document import sections
            extra,handled=sections(self,packet,role);lines.extend(extra)
            if role!='decider':
                lines=[line.replace('## Current decision\n','## Observed decision (not a request for you to play)\n',1) for line in lines]
        menu=packet.get('_action_menu',[])
        if role=='decider':
            lines.append('## Actions\nOne entry per spell/ability/face/alternative, not per target combination. '
                         'These are action families, not guaranteed legal combinations. Read availability and current decision; choose parameters yourself. '
                         'Submit command:{action:"A…",target:"S…"} (or targets:[…]); Python binds exact references. '
                         'Omit mana payment for automatic tapping, including supported pure filter-land costs and color choices. Submit the spell or ability itself; do not request planner mana steps for a payment marked checked. If automatic payment cannot fund an action, consequential or unsupported sources may require a planner sequence; labels do not unlock otherwise prohibited mana activations.')
            for row in menu:
                self.labels.counters['A']+=1
                alias='A'+str(self.labels.counters['A']); self.labels.actions[alias]=deepcopy(row['command'])
                lines.append('- '+alias+' — '+row['label']+'\n  '+self.value({k:v for k,v in row.items() if k not in ('label','command')}))
        if role=='short_term_planner' and packet.get('_coordination_document')==1:
            lines.append('## Planning action templates\nThese are frozen planning vocabulary, not legal actions available now. Use command:{action:"T…",targets:[…]} in phase steps; select parameters and reserve mana if needed. Python expands the template before publication. Templates do not execute and are never sent to the decider as another lane’s labels.')
            for row in packet.get('_planning_menu',[]):
                self.labels.counters['T']+=1;alias='T'+str(self.labels.counters['T'])
                self.labels.actions[alias]=deepcopy(row['command'])
                lines.append('- '+alias+' — '+row['label']+'\n  '+self.value({k:v for k,v in row.items() if k not in ('label','command')}))
        # Keep plans verbatim in substance, with reversible IDs and references.
        for key in ('plans','diplomatic_holds','combo_offer','rejection','rejection_context','batch_interruption'):
            if key not in handled and packet.get(key) is not None:
                value=packet[key]
                if key=='plans':value={name:{k:v for k,v in row.items() if k not in ('id','short_term_id')} if isinstance(row,dict) else row for name,row in value.items()}
                lines.append('## '+key.replace('_',' ')+'\n'+self.section(key,self.value(value),repeat=key=='plans'))
        if board:
            lines.append('## Current board')
            for key,value in board.items():
                if key in ('decision','revision','schema','actor'):continue
                if key=='zones':
                    parts=[]
                    for zone,seats in value.items():
                        objects=[obj for rows in seats.values() for obj in rows]
                        if objects:parts.append(self.objects(objects))
                        for seat in seats:
                            if not any(obj.get('controller',obj.get('owner'))==seat for obj in objects):
                                parts.append('### '+seat+'’s '+zone.replace('_',' ')+'\nEmpty.')
                    rendered='\n\n'.join(parts)
                elif key=='stack':rendered=self.value([{k:v for k,v in frame.items() if k!='id'} for frame in value])
                else:rendered=self.value(value)
                lines.append('## '+key.replace('_',' ')+'\n'+self.section('board/'+key,rendered))
        lines.append('## Card rules (once per printed face)')
        # Only cards already visible in this role's packet. Diplomats never gain
        # own hand or private knowledge through the catalog lookup.
        names=[]
        def names_in(v):
            if isinstance(v,dict):
                if isinstance(v.get('name'),str) and (is_object(v) or 'source' in v or 'mana_cost' in v): names.append(v['name'])
                for child in v.values(): names_in(child)
            elif isinstance(v,list):
                for child in v: names_in(child)
        names_in(board)
        for row in packet.get('_knowledge',{}).values():
            program=row.get('program',{})
            if program.get('name'): names.append(program['name'])
        for name in dict.fromkeys(names):
            face=self.faces.get(name)
            if face:
                lines.append('### '+face.name+' '+face.mana_cost+'\n'+self.section('oracle/'+face.name,face.oracle_text))
            else:
                # Custom tokens/fixtures cannot acquire invented Oracle rules.
                rules=[v for v in packet.get('_knowledge',{}).values() if v.get('program',{}).get('name')==name]
                lines.append('### '+name+'\nNo frozen Oracle face available. Explicit implemented rules: '+self.value(rules))
        excluded={'board','current_decision','action_facts','plans','diplomatic_holds','combo_offer','rejection','rejection_context','batch_interruption'}
        for key,value in packet.items():
            if key in excluded or key in handled or key in OMIT or key.startswith('_') or value is None: continue
            lines.append('## '+key.replace('_',' ')+'\n'+self.section(key,self.value(value)))
        return '\n\n'.join(lines)+'\n'
