"""Unambiguous software-host ordinary answers; batch grammar stays separate."""
from .scheduler import WAKE_CONDITIONS
from .table_talk_plan import SCHEMA as TABLE_TALK_SCHEMA
from .decision_roles import COMBO_SCHEMA
from .diplomacy import BRIEF_SCHEMA
from .turn_batches import COVERAGE_SCHEMA

PHASES = ['upkeep','draw','precombat_main','combat','postcombat_main','end_step']
TIME = {'type':'object','properties':{
    'occurrences':{'type':'integer','minimum':1,'maximum':1000000},
    'edge':{'type':'string','enum':['beginning','end']},
    'phase':{'type':'string','enum':PHASES}},
    'required':['occurrences','edge','phase'],'additionalProperties':False}
SNOOZE = {'type':'object','properties':{
    'time':{'anyOf':[TIME,{'type':'string','description':'For example: 1 beginning of upkeep. Prefer the typed time object.'}]},
    'wake_condition':{'type':'string','enum':sorted(WAKE_CONDITIONS)}},
    'required':['time','wake_condition'],'additionalProperties':False}
OBJECT_SNOOZE = {**SNOOZE,'properties':{**SNOOZE['properties'],
    'objects':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':200}},
    'required':[*SNOOZE['required'],'objects']}
STEP_SCHEDULER={'oneOf':[
    {'type':'object','properties':{'mode':{'type':'string','enum':['hold_full_control','resolve_my_sequence']}},
     'required':['mode'],'additionalProperties':False},
    *[{'type':'object','properties':{'mode':{'const':mode},**schema['properties']},
       'required':['mode',*schema['required']],'additionalProperties':False}
      for mode,schema in [('snooze_table',SNOOZE),('snooze_objects',OBJECT_SNOOZE)]] ]}
ACTION_STEP={'type':'object','properties':{
    'id':{'type':'string','minLength':1,'maxLength':48},
    'seat_turn':{'type':'integer','minimum':1,'maximum':1000000},
    'phase':{'type':'string','enum':['precombat_main','combat','postcombat_main']},
    'kind':{'type':'string','minLength':1,'maxLength':80},'choice':{},
    'rationale':{'type':'string','minLength':1,'maxLength':300},'scheduler':STEP_SCHEDULER,
    'requires':{'type':'array','maxItems':8,'items':{'type':'object'}}},
    'required':['id','seat_turn','phase','kind','choice','rationale','scheduler'],'additionalProperties':False}
WATCH_CONDITION={'oneOf':[
    {'type':'object','properties':{'kind':{'const':'card_cast'},'seat':{'type':'string'},'card':{'type':'string'}},'required':['kind','seat','card'],'additionalProperties':False},
    {'type':'object','properties':{'kind':{'const':'object_left'},'uid':{'type':'string'}},'required':['kind','uid'],'additionalProperties':False},
    {'type':'object','properties':{'kind':{'const':'life_at_most'},'seat':{'type':'string'},'value':{'type':'integer','minimum':0,'maximum':1000000}},'required':['kind','seat','value'],'additionalProperties':False}]}
WATCH={'type':'object','properties':{'watch_id':{'type':'string','minLength':1,'maxLength':200},'condition':WATCH_CONDITION},'required':['watch_id','condition'],'additionalProperties':False}
DIPLOMACY_BRIEF_SCHEMA={**BRIEF_SCHEMA,'properties':{**BRIEF_SCHEMA['properties'],
    'invalid_when':{'type':'array','maxItems':8,'items':WATCH_CONDITION}}}
PLANNER_RESPONSE={'type':'object','properties':{
    'standing_plan':{'type':'string','maxLength':3600,'description':'Aim around 2700 characters, with grouped engines, win routes and recovery; maximum 3600 characters, not words.'},
    'diplomacy_brief_action':{'type':'string','enum':['keep','revise'],'description':'KEEP a currently valid brief by reference, or REVISE with diplomacy_brief. Both require a mandatory diplomat message.'},
    'short_term_plan':{'type':'string','maxLength':1200,'description':'Tiered games require at most 600 characters; follow the stage max_chars.'},
    'continuity':{'type':'string','maxLength':1200},
    'long_term_validity':{'type':'string','enum':['valid','invalid']},
    'long_term_invalid_reason':{'type':'string','minLength':1,'maxLength':300},
    'strategic_disposition':{'type':'string','enum':['continue','review_requested','review_pending']},
    'strategic_review':{'type':'object','properties':{
        'question':{'type':'string','minLength':1,'maxLength':600},
        'evidence':{'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','maxLength':200}},
        'interim':{'type':'string','maxLength':600},'useful_by':{'type':'string','minLength':1,'maxLength':160}},
        'required':['question','evidence','interim','useful_by'],'additionalProperties':False},
    'table_talk':TABLE_TALK_SCHEMA,
    'combo_proposal':COMBO_SCHEMA,
    'diplomacy_brief':DIPLOMACY_BRIEF_SCHEMA,
    'dependencies':{'type':'array','maxItems':24,'items':{'type':'string'}},'boundary_notes':{
        'type':'object','additionalProperties':{'type':'string','minLength':1,'maxLength':1200},
        'description':'Map exact reserved boundary keys to factual continuity notes. Required for every boundary when multiple are coalesced; see the current publication stage.'},
    'long_term_action':{'type':'string'},'long_term_rationale':{'type':'string','maxLength':1200},'long_term_plan':{'type':'string','maxLength':1200},
    'phase_coverage':COVERAGE_SCHEMA,
    'action_sequence':{'type':'array','maxItems':16,'items':ACTION_STEP},
    'watches':{'type':'array','maxItems':8,'items':WATCH}},'additionalProperties':False}
PLANNER_GUIDANCE=('Every action_sequence step needs scheduler as an OBJECT with a mode, never a string or boolean flags. '
    'Examples: "scheduler":{"mode":"hold_full_control"}; "scheduler":{"mode":"resolve_my_sequence"}; '
    '"scheduler":{"mode":"snooze_table","time":{"occurrences":1,"edge":"beginning","phase":"upkeep"},"wake_condition":"opponent_action"}. '
    'snooze_objects also requires objects:[exact visible UIDs]. Use only these four modes. '
    'Do not copy ordinary pilot answer flags into a symbolic step. Supply the complete corrected unpublished stage; never repeat an accepted stage.')
PLANNER_GUIDANCE+=(' Complete step fields: id, seat_turn (positive absolute own-turn ordinal), phase, kind, choice, rationale, scheduler; optional requires. '
    'phase MUST be exactly precombat_main, combat, or postcombat_main (underscores); never upkeep, draw, end_step, main_phase, or a prose alias. '
    'kind is the exact engine decision kind; choice uses the frozen symbolic_options, not menu numbers or card names. '
    'Maximum 16 steps, 12000 UTF-8 bytes total, rationale 300 characters. requires is at most 8 objects {path:JSON_POINTER,op:eq|gte|lte|present,value:JSON_VALUE}. '
    'watches MUST be a list of at most 8 objects with exactly watch_id and condition. condition is an OBJECT in exactly one of these forms: '
    '{"kind":"card_cast","seat":"KNOWN_SEAT","card":"EXACT_KNOWN_CARD"}, '
    '{"kind":"object_left","uid":"VISIBLE_UID"}, or {"kind":"life_at_most","seat":"KNOWN_SEAT","value":10}. '
    'Substitute actual frozen known identities; placeholders are illustrative. No other watch kinds, extra fields, prose conditions or boolean expressions. '
    'An explicit empty watches list is valid if you choose no watches. The mandatory own EOT wake already exists.')

def validate_planner_response(response,*,actor=None,board=None,cards=None,uids=None):
    from .scheduler import normalize_directive
    if not isinstance(response,dict):raise ValueError('Planner response must be an object.')
    if board is not None:
        from . import sequence_contract,planning_contract
        errors=[]
        for name,limit,validator in (
            ('action_sequence',16,lambda v:sequence_contract.proposals(v,actor,board,uids)),
            ('watches',8,lambda v:planning_contract.watches(v,board,cards,uids))):
            if name not in response:continue
            values=response[name]
            if not isinstance(values,list) or len(values)>limit:
                errors.append(f'{name}: expected an array of at most {limit} items');continue
            for index,value in enumerate(values):
                try:validator([value])
                except (ValueError,TypeError) as error:errors.append(f'{name}[{index}]: {error}')
            if not errors:
                try:validator(values)
                except (ValueError,TypeError) as error:errors.append(f'{name}: {error}')
        if errors:raise ValueError('Invalid proposal fields: '+'; '.join(errors))
        return
    steps=response.get('action_sequence',[])
    if not isinstance(steps,list):raise ValueError('action_sequence must be an array.')
    for index,step in enumerate(steps):
        if not isinstance(step,dict):raise ValueError(f'action_sequence[{index}] must be an object.')
        try:
            directive=normalize_directive(step.get('scheduler'))
            if directive['mode']=='snooze_stack':raise ValueError('Use resolve_my_sequence.')
        except ValueError as error:
            raise ValueError(f'action_sequence[{index}].scheduler: {error}. '+PLANNER_GUIDANCE) from error

def validate_frozen_planner_response(root,game,actor,job,response):
    from . import planner_runtime
    from .runtime_store import read,get
    directory,_,_,snapshot=planner_runtime._batch(root,game,actor,job['batch_id'],job['generation'])
    binding=read(directory/'inputs'/(job['batch_id']+'.json'))
    frozen=get(directory/'frozen_inputs',binding['input_id'])
    if frozen.get('agent_architecture')==1 and frozen.get('role')=='long_term_planner':return
    vocabulary=frozen['symbolic_vocabulary']
    validate_planner_response(response,actor=actor,board=snapshot['board'],
        cards=set(vocabulary['cards']),uids=set(vocabulary['object_uids']))

ANSWER = {'type':'object','properties':{
    'choice':{'anyOf':[{'type':'integer','minimum':0},{'type':'string'},
                      {'type':'object','additionalProperties':{'type':'array','items':{'type':'string'}}},
                      {'type':'object','additionalProperties':{'type':'object','properties':{
                          'blockers':{'type':'object','additionalProperties':{'type':'integer','minimum':0}},
                          'defender':{'type':'integer','minimum':0}},'required':['blockers','defender'],'additionalProperties':False}}],
              'description':'Menu number/text, or requested structured combat response. block_declaration maps attacker UIDs to blocker UID lists; combat_damage maps source UIDs to {blockers:{UID:damage},defender:damage}. Never null.'},
    'rationale':{'type':'string'},
    'hold_full_control':{'type':'boolean'},'resolve_my_sequence':{'type':'boolean'},
    'snooze_table':SNOOZE,'snooze_objects':OBJECT_SNOOZE,
    'message_text':{'type':'string','maxLength':300},
    'message_address':{'type':'string','enum':['generic','all','pilot']},
    'message_recipient':{'type':'string'},
    'planner_alarm':{'type':'object'},
    'pass_on_entries':{'type':'array','items':{'type':'string'}}},
    'required':['choice'],'additionalProperties':False}
RESPONSE = {'oneOf':[
    {'type':'object','properties':{'answer':ANSWER},'required':['answer'],'additionalProperties':False},
    {'type':'object','properties':{'batch':{'type':'object','properties':{
        'approve':{'type':'array','items':{'type':'string'},'maxItems':16},
        'reject':{'type':'array','items':{'type':'string'},'maxItems':16},
        'overrides':{'type':'object'},'add':{'type':'array','items':{'type':'object'},'maxItems':16},
        'pass_priority':{'type':'boolean'},'resume_after_passes':{'type':'boolean'},'rejection_rationale':{'type':'string','minLength':1,'maxLength':300}},
        'required':['approve','reject'],'additionalProperties':False,
        'description':'Pilot-approved symbolic sequence; follow the batch contract.'}},
     'required':['batch'],'additionalProperties':False}]}

GUIDANCE = ('Ordinary edh_act JSON: {"response":{"answer":{"choice":1,"rationale":"Reason",'
            '"hold_full_control":true}}}. Use a current menu number, 0 for PASS/none, or '
            'a comma-separated string for multi-select. At blockers_assignment, select all blockers for the named attacker in this one answer, or 0 for no block; obey min_selected_if_any. Special text decisions follow response_help. '
            'Choose exactly one top-level snooze field: hold_full_control:true, resolve_my_sequence:true, '
            'snooze_table:{time,wake_condition}, or snooze_objects:{objects,time,wake_condition}. '
            'Time object: {occurrences:1,edge:"beginning",phase:"upkeep"}; phases: '
            + ', '.join(PHASES) + '. Ordinary answers NEVER contain scheduler or a null choice. Structured responses: block_declaration maps all attacker UIDs to blocker UID lists (empty if unblocked); combat_damage maps all supplied source UIDs to {blockers:{UID:integer},defender:integer}. Follow the current request schema. Other ordinary choices are menu numbers/text, not symbolic actions. '
            'Nested scheduler objects and symbolic choices (including null PASS) belong ONLY to batch steps.')

BATCH_GUIDANCE = '''Optional batch edh_act JSON: {"response":{"batch":{"approve":["step-id"],"reject":[],"resume_after_passes":true}}}.
Approve only during an ordinary own precombat/postcombat land_play or main_action. Name every proposed step exactly once in approve or reject; approve order is execution order. Otherwise make an ordinary answer with the reason for departing from the plan.
Optional overrides maps approved IDs to replacements of choice, rationale, scheduler or requires. Optional add contains complete new steps for currently visible cards; use unique IDs and put them in approve at the intended positions. A complete step has id, seat_turn (absolute own-turn ordinal), phase (precombat_main/combat/postcombat_main), exact decision kind, symbolic choice, rationale (<=300 characters), scheduler, and optional requires. Steps use the frozen symbolic_options exactly: UID objects, seat objects, action/source/args objects, null PASS, or lists for multi-select. These symbolic values are NOT ordinary answer choices.
Every new step needs its own rationale and scheduler {mode:hold_full_control|resolve_my_sequence|snooze_table|snooze_objects,...}. Table snooze is permitted only on the final approved step. Time and wake fields follow the same typed snooze grammar as ordinary answers. Requires uses JSON Pointer paths, eq/gte/lte/present, and values; at most eight predicates per step. Maximum 16 steps and 12,000 UTF-8 bytes total; symbolic choice maximum 1,500 bytes. Never invent unseen cards, future token UIDs, unresolved targets, modes or payments. Required choices must be separate explicitly approved steps.
For partial rejection include one rejection_rationale <=300 characters. Default to resume_after_passes:true when you authorize continuation after opponents only pass. Python never passes for opponents or invents an action; it stops on intervention, new information, failed prerequisites, illegality, new required choices, or exhaustion. The first step must match this decision. Messages, concessions and combo claims use ordinary answers. Inspect sequence for the full frozen proposal. No standalone plan-approval turn, identity fields, shell calls or coordinator routing. On parked/stop, end immediately. Do not replay an accepted batch.'''

def validate_response(response):
    """Enforce transport shape before binding an engine submission. Never infer a choice."""
    if not isinstance(response,dict) or set(response) not in ({'answer'},{'batch'}):
        raise ValueError('Supply answer or batch only.')
    if 'batch' in response:
        if not isinstance(response['batch'],dict):raise ValueError('batch must be an object')
        return
    answer=response['answer']
    if not isinstance(answer,dict):raise ValueError('answer must be an object')
    unknown=set(answer)-set(ANSWER['properties'])
    if unknown:raise ValueError('Invalid answer fields: '+', '.join(sorted(unknown))+'. Snooze fields belong directly in answer.')
    choice=answer.get('choice')
    block_map=isinstance(choice,dict) and all(isinstance(k,str) and isinstance(v,list) and all(isinstance(uid,str) for uid in v) for k,v in choice.items())
    damage_map=isinstance(choice,dict) and all(isinstance(k,str) and isinstance(v,dict) and set(v)=={'blockers','defender'} and
        isinstance(v['blockers'],dict) and type(v['defender']) is int and v['defender']>=0 and
        all(isinstance(uid,str) and type(n) is int and n>=0 for uid,n in v['blockers'].items()) for k,v in choice.items())
    if isinstance(choice,bool) or not (isinstance(choice,(int,str)) or block_map or damage_map) or (isinstance(choice,int) and choice<0):
        raise ValueError('choice must be a menu number/text or the requested structured combat assignment; never null or a symbolic action.')
    for key in ('rationale','message_text','message_address','message_recipient'):
        if key in answer and not isinstance(answer[key],str):raise ValueError(key+' must be a string')
    from .scheduler import normalize_directive
    selected=[]
    for key in ('hold_full_control','resolve_my_sequence'):
        if key in answer and not isinstance(answer[key],bool):raise ValueError(key+' must be a boolean')
        if answer.get(key):selected.append({'mode':key})
    for key in ('snooze_table','snooze_objects'):
        if key in answer:
            if not isinstance(answer[key],dict):raise ValueError(key+' must be an object')
            if 'mode' in answer[key]:raise ValueError('Do not nest a mode inside '+key)
            selected.append({'mode':key,**answer[key]})
    if len(selected)!=1:raise ValueError('Exactly one top-level snooze directive is required.')
    normalize_directive(selected[0])
