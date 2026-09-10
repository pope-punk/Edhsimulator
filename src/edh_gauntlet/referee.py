#!/usr/bin/env python3
"""Manual EDH ledger runner.

The imported Game is the rules/state ledger.  This module deliberately removes the
old score-maximising policy from official play and halts for explicit externally-authored decisions. The code contains no strategic chooser.

Machine responsibilities: shuffle, zones, mana legality/payment, triggers/effects,
combat arithmetic, SBAs, invariants, snapshots.
External pilot responsibilities: mulligans, sequencing, tutors, optional targets/modes,
interaction, attack target/attackers, blocks, and other materially branching choices.
"""
from __future__ import annotations
import json, argparse, hashlib, re, unicodedata
from dataclasses import dataclass
from itertools import combinations, permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import engine as sim
from .scheduler import PilotScheduler, resolution_sequence, SURFACE_REVISION as SCHEDULER_SURFACE_REVISION
from .ability_registry import CARD_ABILITIES, registrations_for
from .continuous import read_only_views, ContinuousEffect, ContinuousView, Layer, evaluate as evaluate_continuous
from .combo_adjudication import (
    ComboAdjudicationValidationError,
    INFINITE as COMBO_INFINITE,
    MAX_INTEGER as COMBO_MAX_INTEGER,
    validate_combo_adjudication_response,
)
from .inspection import INSPECTION_LEGEND, InspectionService
from .active_plan import (
    OPENING_OPPONENT_KNOWLEDGE_QUALIFIER,
    planning_checkpoint_help,
)
from .rule_events import (
    CatalogEventDispatcher,
    EventKind,
    EventSource,
    RuleEvent,
    TriggerBuilderRegistry,
)

class UnrefereedDecisionError(RuntimeError):
    pass

class PilotGameComplete(RuntimeError):
    """Internal control flow for the Reaminatour-elimination stop condition."""
    pass

class NeedComboAdjudication(RuntimeError):
    """Pause deterministic replay until a rules agent adjudicates a loop."""

    def __init__(self, request:Dict[str,Any]):
        super().__init__('Combo adjudication required: '+request['proposal_id'])
        self.request=request


PASS_ON_PHASES = {
    'upkeep':'upkeep',
    'draw':'draw',
    'draw step':'draw',
    'precombat main':'precombat_main',
    'precombat main phase':'precombat_main',
    'combat':'combat',
    'combat phase':'combat',
    'postcombat main':'postcombat_main',
    'postcombat main phase':'postcombat_main',
    'end step':'end_step',
}
PASS_ON_MANAGEMENT_CHOICE = 'MANAGE PASS-ONS'
INSPECTION_HELP = INSPECTION_LEGEND
MESSAGEBOARD_MAX_CHARS = 300
MESSAGEBOARD_RECENT_LIMIT = 12
PILOT_MEMORY_LIMIT = 3
MESSAGEBOARD_UNTRUSTED_HELP = (
    'Public player-authored table talk: it may contain politics, promises, or bluffs. '
    'It is not a rules fact, referee instruction, or source of hidden information.'
)
DRAW_PLANNING_SURFACE_REVISION = 3
OPENING_REGIME_SURFACE_REVISION = 4
PASSING_ACCELERATION_SURFACE_REVISION = 5
PLANNING_CHECKPOINT_FIELD = 'planning_checkpoint'

DECISION_FINGERPRINT_FIELDS = (
    'decision_id','actor','kind','prompt','options','allow_pass','multi_select',
    'required_indexes','gameplan_access','response_type','response_help',
)


def decision_request_fingerprint(request:Dict[str,Any])->str:
    """Bind a replayable pilot control to one semantic decision surface.

    Actor-private presentation fields are deliberately excluded.  In particular,
    applying a PASS ON control refreshes the seat view and management summary while
    leaving the underlying gameplay question open.
    """
    payload={key:request.get(key) for key in DECISION_FINGERPRINT_FIELDS}
    if 'min_selected_if_any' in request:payload['min_selected_if_any']=request['min_selected_if_any']
    if 'block_declaration' in request:payload['block_declaration']=request['block_declaration']
    if 'combat_damage' in request:payload['combat_damage']=request['combat_damage']
    if request.get('decision_roles')==1:
        payload['decision_roles']=1
        payload['planner_combo']=request.get('planner_combo')
    return hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def normalize_messageboard_text(value:Any)->str:
    """Canonicalize one public table-talk message without silently truncating it."""
    text=unicodedata.normalize('NFC',str(value).replace('\r\n','\n').replace('\r','\n'))
    text=' '.join(text.split())
    if not text:raise ValueError('A public message cannot be empty')
    if any(unicodedata.category(character)=='Cc' for character in text):
        raise ValueError('A public message cannot contain control characters')
    if len(text)>MESSAGEBOARD_MAX_CHARS:
        raise ValueError(
            f'A public message may not exceed {MESSAGEBOARD_MAX_CHARS} characters '
            f'(received {len(text)})')
    return text


def parse_pass_on_schedule(value:Any)->Dict[str,Any]:
    """Canonicalize ``N beginning|end of PHASE`` typed decision input."""
    if isinstance(value,dict):
        if set(value)!={'occurrences','edge','phase'}:
            raise ValueError('PASS ON schedule must contain occurrences, edge, and phase only')
        occurrences=value.get('occurrences');edge=str(value.get('edge','')).casefold()
        phase=str(value.get('phase','')).casefold().replace('-','_').replace(' ','_')
        if isinstance(occurrences,bool) or not isinstance(occurrences,int) or occurrences<1:
            raise ValueError('PASS ON occurrences must be a positive integer')
        if occurrences>1000000:raise ValueError('PASS ON occurrences may not exceed 1000000')
        if edge not in {'beginning','end'}:raise ValueError("PASS ON edge must be 'beginning' or 'end'")
        if phase not in set(PASS_ON_PHASES.values()):raise ValueError('Unknown PASS ON phase')
        return {'occurrences':occurrences,'edge':edge,'phase':phase}
    text=' '.join(str(value).strip().casefold().replace('_',' ').split())
    match=re.fullmatch(
        r'(?:snooze\s+)?(?:until\s+)?(?:the\s+)?'
        r'(?P<count>next|\d+)(?:st|nd|rd|th)?\s+'
        r'(?P<edge>beginning|end)\s+(?:of\s+)?(?P<phase>.+?)'
        r'(?:\s+from\s+now)?',text)
    if not match:
        raise ValueError(
            'Enter a PASS ON schedule such as "1 beginning of upkeep" or "3 end of combat"')
    count=1 if match.group('count')=='next' else int(match.group('count'))
    phase=PASS_ON_PHASES.get(match.group('phase'))
    if phase is None:raise ValueError('Unknown PASS ON phase/step')
    return parse_pass_on_schedule({'occurrences':count,'edge':match.group('edge'),'phase':phase})


def parse_pass_on_batch_entry(value:Any)->Dict[str,Any]:
    """Canonicalize one ``OBJECT_UID=N beginning|end of PHASE`` entry."""
    if isinstance(value,dict):
        if set(value)!={'source_uid','schedule'}:
            raise ValueError('A batched PASS ON entry must contain source_uid and schedule only')
        source_uid=str(value.get('source_uid','')).strip()
        schedule=value.get('schedule')
    else:
        text=str(value).strip()
        if '=' not in text:
            raise ValueError(
                'Enter each batched PASS ON as "OBJECT_UID=1 beginning of upkeep"')
        source_uid,schedule=text.split('=',1);source_uid=source_uid.strip()
    if not source_uid:
        raise ValueError('A batched PASS ON entry requires an object UID before =')
    if len(source_uid)>160:
        raise ValueError('A batched PASS ON object UID is too long')
    return {'source_uid':source_uid,'schedule':parse_pass_on_schedule(schedule)}


def validate_pass_on_control(value:Any)->Dict[str,Any]:
    """Validate the narrow pre-decision control format used by PASS ON management."""
    if not isinstance(value,dict):raise ValueError('PASS ON control must be an object')
    action=str(value.get('action',''))
    expected={
        'schema','control_id','actor','decision_id','request_sha256','action','source_uids',
    }
    if action=='reschedule':expected.add('schedule')
    if set(value)!=expected:raise ValueError('PASS ON control contains missing or unknown fields')
    if value.get('schema')!=1:raise ValueError('Unsupported PASS ON control schema')
    control_id=value.get('control_id');actor=value.get('actor');decision_id=value.get('decision_id')
    request_sha256=value.get('request_sha256');source_uids=value.get('source_uids')
    if not isinstance(control_id,str) or not control_id or len(control_id)>160:
        raise ValueError('PASS ON control_id must be a nonempty string')
    if not isinstance(actor,str) or not actor:raise ValueError('PASS ON control actor is required')
    if not isinstance(decision_id,str) or not decision_id:
        raise ValueError('PASS ON control decision_id is required')
    if not isinstance(request_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',request_sha256):
        raise ValueError('PASS ON control request_sha256 is invalid')
    if action not in {'unsnooze','reschedule'}:
        raise ValueError('PASS ON control action must be unsnooze or reschedule')
    if (not isinstance(source_uids,list) or not source_uids or
            any(not isinstance(uid,str) or not uid for uid in source_uids) or
            len(source_uids)!=len(set(source_uids))):
        raise ValueError('PASS ON control source_uids must be distinct nonempty strings')
    result={
        'schema':1,'control_id':control_id,'actor':actor,'decision_id':decision_id,
        'request_sha256':request_sha256,'action':action,'source_uids':list(source_uids),
    }
    if action=='reschedule':
        if len(source_uids)!=1:raise ValueError('A reschedule control requires exactly one source UID')
        result['schedule']=parse_pass_on_schedule(value.get('schedule'))
    return result

@dataclass
class PriorityObjectPass:
    """Pilot-authored debounce for one exact game object.

    ``source`` is intentionally the live Python object, not merely its physical
    card UID.  A card that changes zones becomes a new game object under Magic's
    rules even though this ledger preserves the physical UID across zones.
    """

    source: Any
    source_uid: str
    source_name: str
    source_zone: str
    armed_turn: int
    wake_not_before_turn: int
    wake_player: str
    wake_edge: Optional[str] = None
    wake_phase: Optional[str] = None
    requested_occurrences: int = 0
    wake_ordinal: int = 0


@dataclass
class PrioritySeatSnooze:
    """A pilot-authored pass across optional prompts, bounded by game timing."""

    armed_turn: int
    wake_not_before_turn: int
    wake_player: str
    wake_edge: Optional[str] = None
    wake_phase: Optional[str] = None
    requested_occurrences: int = 0
    wake_ordinal: int = 0

class NeedDecision(RuntimeError):
    def __init__(self, request:Dict[str,Any]):
        super().__init__('Decision required: '+request['decision_id'])
        self.request=request

def semantic_label_key(label:str)->str:
    """Normalize display punctuation for tapes written by older Windows shells."""
    text=str(label)
    for artifact in ('\ufffd','\u00e2\u20ac\u201d','\u00e2\u2020\u2019','\u2014','\u2013','\u2192'):
        text=text.replace(artifact,' ')
    return ' '.join(''.join(character.casefold() if character.isalnum() else ' ' for character in text).split())

class ConsoleDecisionTape:
    def resolve(self, request:Dict[str,Any]):
        print('\n'+'='*100)
        print(f"{request['decision_id']} | R{request['round']} T{request['turn']} {request['phase']} | {request['actor']} | {request['kind']}")
        print(request['prompt'])
        print(request['seat_view'])
        for i,label in enumerate(request['options'],1):print(f'  {i:2d}. {label}')
        if request['allow_pass']:print('   0. PASS / choose none')
        while True:
            if request.get('response_type') in {'block_declaration','combat_damage'}:
                from .structured_choice import validate,presentation
                print(presentation(request))
                raw=input('block declaration JSON [| rationale]: ').strip()
                left,sep,rationale=raw.partition('|')
                try:return validate(request,left),rationale.strip()
                except ValueError as exc:print(str(exc));continue
            if request.get('response_type')=='pass_on_schedule':
                raw=input('schedule [for example: 3 end of combat | rationale]: ').strip()
                if '|' in raw:left,rationale=raw.split('|',1);rationale=rationale.strip()
                else:left,rationale=raw,''
                try:return parse_pass_on_schedule(left),rationale
                except ValueError as exc:print(str(exc));continue
            selector='comma-separated numbers' if request.get('multi_select') else 'number'
            raw=input(f'choice [{selector} | rationale]: ').strip()
            if '|' in raw:left,rationale=raw.split('|',1);rationale=rationale.strip()
            else:left,rationale=raw,''
            if request.get('multi_select'):
                try:indexes=[] if left.strip()=='0' else [int(value.strip())-1 for value in left.split(',')]
                except ValueError:
                    print('Enter comma-separated option numbers, optionally followed by | rationale');continue
                if len(indexes)!=len(set(indexes)) or any(not 0<=index<len(request['options']) for index in indexes):
                    print('Invalid or repeated choice.');continue
                required=set(request.get('required_indexes',[]))
                if not required.issubset(indexes):
                    print('Every REQUIRED attacker must be selected.');continue
                if not indexes and not request['allow_pass']:
                    print('This choice cannot be empty.');continue
                from .decision_selection import validate_count
                try:validate_count(request,indexes)
                except ValueError as exc:print(str(exc));continue
                return indexes,rationale
            try:idx=int(left.strip())
            except ValueError:
                print('Enter an option number, optionally followed by | rationale');continue
            if idx==0 and request['allow_pass']:return None,rationale
            if 1<=idx<=len(request['options']):return idx-1,rationale
            print('Invalid choice.')

class DecisionTape:
    """Replay a JSONL decision script; stop cleanly at the first missing decision.

    This lets ChatGPT make one seat-visible decision at a time without ever opening the
    omniscient ledger. Re-running from the seed plus prior decisions deterministically
    reconstructs the game and reaches the next crux.
    """
    def __init__(self, script_path:Path, request_path:Optional[Path]=None):
        self.script_path=Path(script_path);self.request_path=Path(request_path) if request_path else self.script_path.with_suffix('.request.json')
        self.script={};self.pass_on_control_positions={}
        if self.script_path.exists():
            for line in self.script_path.read_text(encoding='utf8').splitlines():
                if not line.strip():continue
                r=json.loads(line);self.script[r['decision_id']]=r

    def needs_presentation(self,decision_id:str)->bool:
        """Return whether this decision can escape replay and reach a pilot."""
        record=self.script.get(decision_id)
        return record is None or record.get('choice_pending') is True

    def auxiliary_payload(self,decision_id:str)->Dict[str,Any]:
        """Return validated sidecar input attached to one accepted decision.

        Decision resolution deliberately keeps its historical two-value return
        shape.  New batched actions can retrieve structured, replayed input here
        without teaching the rules engine about CLI spelling.
        """
        record=self.script.get(decision_id) or {}
        payload=record.get('auxiliary_payload') or {}
        if not isinstance(payload,dict):
            raise UnrefereedDecisionError(
                f'{decision_id} auxiliary payload must be an object')
        return dict(payload)

    def _record_pass_on_controls(self,rec):
        raw=rec.get('pass_on_controls',[])
        if not isinstance(raw,list):
            raise UnrefereedDecisionError('Decision PASS ON controls must be a list')
        try:controls=[validate_pass_on_control(value) for value in raw]
        except ValueError as exc:
            raise UnrefereedDecisionError(f'Invalid replayed PASS ON control: {exc}') from exc
        identifiers=[control['control_id'] for control in controls]
        if len(identifiers)!=len(set(identifiers)):
            raise UnrefereedDecisionError('Decision contains duplicate PASS ON control IDs')
        return controls

    def next_pass_on_control(self,request:Dict[str,Any]):
        """Yield the next control anchored before this still-open decision."""
        did=request['decision_id'];rec=self.script.get(did)
        if rec is None:return None
        controls=self._record_pass_on_controls(rec)
        position=self.pass_on_control_positions.get(did,0)
        if position>=len(controls):return None
        control=controls[position]
        if control['actor']!=request.get('actor') or control['decision_id']!=did:
            raise UnrefereedDecisionError(
                f'{did} PASS ON control is bound to a different actor or decision')
        if control['request_sha256']!=decision_request_fingerprint(request):
            if rec.get('choice_pending') is True:
                raise UnrefereedDecisionError(
                    f'{did} pending PASS ON control is stale for the current decision surface')
            self.stop_for_inserted_decision(request)
        self.pass_on_control_positions[did]=position+1
        return control

    def stop_for_inserted_decision(self,request):
        request=dict(request);request['rebase_existing_decision']=True
        self.request_path.parent.mkdir(parents=True,exist_ok=True)
        self.request_path.write_text(json.dumps(request,indent=2),encoding='utf8')
        raise NeedDecision(request)

    def resolve(self,request:Dict[str,Any]):
        rec=self.script.get(request['decision_id'])
        if rec is None:
            self.request_path.parent.mkdir(parents=True,exist_ok=True)
            self.request_path.write_text(json.dumps(request,indent=2),encoding='utf8')
            raise NeedDecision(request)
        controls=self._record_pass_on_controls(rec)
        if self.pass_on_control_positions.get(request['decision_id'],0)!=len(controls):
            raise UnrefereedDecisionError(
                f"{request['decision_id']} PASS ON controls were not applied before its answer")
        if rec.get('choice_pending') is True:
            if any(key in rec for key in ('choice_index','choice_indexes','choice_value','chosen')):
                raise UnrefereedDecisionError('A controls-only decision row cannot also contain an answer')
            self.request_path.parent.mkdir(parents=True,exist_ok=True)
            self.request_path.write_text(json.dumps(request,indent=2),encoding='utf8')
            raise NeedDecision(request)
        batch=rec.get('auxiliary_payload',{}).get('batch')
        if batch and 'symbolic_choice' in batch:
            # Contract-4 approvals retain physical identities on every replay,
            # even when two legal objects share a label or their menu order changes.
            from .sequence_contract import match
            if rec.get('actor')!=request.get('actor'):self.stop_for_inserted_decision(request)
            try:choice=match(batch['symbolic_choice'],request)
            except (ValueError,KeyError,TypeError):self.stop_for_inserted_decision(request)
            return choice,rec.get('rationale','')
        if request.get('response_type') in {'block_declaration','combat_damage'}:
            from .structured_choice import validate
            if 'choice_value' not in rec:self.stop_for_inserted_decision(request)
            return validate(request,rec['choice_value']),rec.get('rationale','')
        if request.get('response_type')=='pass_on_schedule':
            if 'choice_value' not in rec:self.stop_for_inserted_decision(request)
            try:value=parse_pass_on_schedule(rec['choice_value'])
            except ValueError as exc:
                raise ValueError(f"{request['decision_id']} has an invalid PASS ON schedule: {exc}") from exc
            return value,rec.get('rationale','')
        if 'choice_index' not in rec and 'choice_indexes' not in rec and 'chosen' in rec:
            rec=dict(rec);chosen=rec.get('chosen')
            if request.get('multi_select'):
                labels=list(chosen or []);indexes=[];available=list(enumerate(request['options']))
                for label in labels:
                    matches=[pair for pair in available if pair[1]==label]
                    if len(matches)!=1:
                        key=semantic_label_key(label);matches=[pair for pair in available if semantic_label_key(pair[1])==key]
                    if len(matches)!=1:self.stop_for_inserted_decision(request)
                    index,_=matches[0];indexes.append(index);available.remove(matches[0])
                rec['choice_indexes']=indexes;rec['chosen_labels']=labels
            elif chosen is None:rec['choice_index']=None
            else:
                matches=[index for index,label in enumerate(request['options']) if label==chosen]
                if len(matches)!=1:
                    key=semantic_label_key(chosen);matches=[index for index,label in enumerate(request['options']) if semantic_label_key(label)==key]
                if len(matches)!=1:self.stop_for_inserted_decision(request)
                rec['choice_index']=matches[0];rec['chosen_label']=chosen
        if request.get('multi_select'):
            indexes=[int(index) for index in rec.get('choice_indexes',[])]
            from .decision_selection import validate_count
            validate_count(request,indexes)
            expected=rec.get('chosen_labels')
            labels_at_recorded_indexes=(
                [request['options'][index] for index in indexes]
                if all(0<=index<len(request['options']) for index in indexes)
                else None
            )
            if expected is not None and labels_at_recorded_indexes!=expected:
                remapped=[];available=list(enumerate(request['options']))
                for label in expected:
                    matches=[(index,value) for index,value in available if value==label]
                    if len(matches)!=1:
                        key=semantic_label_key(label)
                        matches=[(index,value) for index,value in available if semantic_label_key(value)==key]
                    if len(matches)!=1:
                        self.stop_for_inserted_decision(request)
                    index,_=matches[0];remapped.append(index);available.remove(matches[0])
                indexes=remapped
            if len(indexes)!=len(set(indexes)) or any(not 0<=index<len(request['options']) for index in indexes):
                raise ValueError(f"{request['decision_id']} multi-select indexes are invalid")
            if not indexes and not request['allow_pass']:
                raise ValueError(f"{request['decision_id']} script makes an empty mandatory choice")
            required=set(request.get('required_indexes',[]))
            if not required.issubset(indexes):
                raise ValueError(f"{request['decision_id']} omits a required option")
            return indexes,rec.get('rationale','')
        if rec.get('choice_index') is None:
            if not request['allow_pass']:raise ValueError(f"{request['decision_id']} script passes a mandatory choice")
            return None,rec.get('rationale','')
        ix=int(rec['choice_index'])
        expected=rec.get('chosen_label')
        if expected is not None and (not 0<=ix<len(request['options']) or expected!=request['options'][ix]):
            matches=[index for index,label in enumerate(request['options']) if label==expected]
            if len(matches)!=1:
                key=semantic_label_key(expected)
                matches=[index for index,label in enumerate(request['options']) if semantic_label_key(label)==key]
            if len(matches)==1:ix=matches[0]
            else:self.stop_for_inserted_decision(request)
        if not (0<=ix<len(request['options'])):raise ValueError(f"{request['decision_id']} choice_index {ix} out of range")
        return ix,rec.get('rationale','')

class ResumeConsoleDecisionTape(DecisionTape):
    """Replay an accepted prefix, then continue interactively at divergence.

    A rules fix can insert a new decision before the end of an otherwise valid
    live-play tape.  Once replay no longer matches, every later choice must be
    freshly piloted because the old decision ids and future information are no
    longer trustworthy.
    """
    def __init__(self,script_path:Path,request_path:Optional[Path]=None):
        super().__init__(script_path,request_path)
        self.console=ConsoleDecisionTape();self.live=False

    def next_pass_on_control(self,request:Dict[str,Any]):
        if self.live:return None
        try:return super().next_pass_on_control(request)
        except (NeedDecision,UnrefereedDecisionError,ValueError):
            self.live=True
            return None

    def needs_presentation(self,decision_id:str)->bool:
        # A semantic mismatch switches directly to the interactive console from
        # inside ``resolve``; keep complete fields available for that handoff.
        return True

    def resolve(self,request:Dict[str,Any]):
        if self.live:return self.console.resolve(request)
        if request.get('response_type') in {'pass_on_schedule','block_declaration','combat_damage'}:
            try:return super().resolve(request)
            except (NeedDecision,ValueError):
                self.live=True
                return self.console.resolve(request)
        rec=self.script.get(request['decision_id'])
        # Console-written tapes store the selected display label(s), whereas
        # campaign answer tapes store indexes plus labels.  Normalize the live
        # form before using the ordinary deterministic replay validator.
        if rec is not None and 'choice_index' not in rec and 'choice_indexes' not in rec:
            normalized=dict(rec);chosen=rec.get('chosen')
            if request.get('multi_select'):
                labels=list(chosen or []);indexes=[];available=list(enumerate(request['options']))
                for label in labels:
                    matches=[pair for pair in available if pair[1]==label]
                    if len(matches)!=1:
                        key=semantic_label_key(label);matches=[pair for pair in available if semantic_label_key(pair[1])==key]
                    if len(matches)!=1:self.live=True;return self.console.resolve(request)
                    index,_=matches[0];indexes.append(index);available.remove(matches[0])
                normalized['choice_indexes']=indexes;normalized['chosen_labels']=labels
            else:
                if chosen is None:normalized['choice_index']=None
                else:
                    matches=[index for index,label in enumerate(request['options']) if label==chosen]
                    if len(matches)!=1:
                        key=semantic_label_key(chosen);matches=[index for index,label in enumerate(request['options']) if semantic_label_key(label)==key]
                    if len(matches)!=1:self.live=True;return self.console.resolve(request)
                    normalized['choice_index']=matches[0];normalized['chosen_label']=chosen
            self.script[request['decision_id']]=normalized
        try:return super().resolve(request)
        except (NeedDecision,ValueError):
            self.live=True
            return self.console.resolve(request)

class ManualGame(sim.Game):
    """Game with externally supplied material choices.

    This is intentionally conservative: if an unconverted policy hotspot is reached, official mode raises rather than selecting anything itself.
    """
    def __init__(self,*args,decision_tape=None,inspection_service=None,
                 combo_adjudications=None,decision_surface_revision=1,planning_contract=1,
                 capture_event_state=True,capture_decision_state=True,async_diplomacy=False,diplomacy_posts=None,combat_blocker_batch=False,combat_damage_batch=False,proliferate_batch_after=None,selection_batch_after=None,turn_batches=False,decision_roles=False,combo_deliveries=None,**kwargs):
        self.decision_surface_revision=int(decision_surface_revision)
        self.planning_contract=planning_contract
        self.async_diplomacy=async_diplomacy
        self.decision_roles=decision_roles
        self.combo_deliveries=combo_deliveries or [];self.used_combo_proposals=set()
        self.combat_blocker_batch=combat_blocker_batch
        self.selection_batch_after=selection_batch_after
        if selection_batch_after is not None and (type(selection_batch_after) is not int or selection_batch_after<0):
            raise ValueError("selection_batch_after must be a nonnegative accepted decision count")
        self.proliferate_batch_after=proliferate_batch_after
        if proliferate_batch_after is not None and (type(proliferate_batch_after) is not int or proliferate_batch_after<0):
            raise ValueError("proliferate_batch_after must be a nonnegative accepted decision count")
        self.combat_damage_batch=combat_damage_batch
        self.turn_batches=turn_batches
        self.diplomacy_posts=diplomacy_posts or [];self.diplomacy_applied=set()
        self.planning_boundaries=[]
        self.planning_turns={}
        self._planning_life={}
        if self.decision_surface_revision<1:
            raise ValueError('decision_surface_revision must be a positive integer')
        self.capture_event_state=bool(capture_event_state)
        self.capture_decision_state=bool(capture_decision_state)
        self.decision_tape = decision_tape or ConsoleDecisionTape()
        if inspection_service is not None:self.inspection_service=inspection_service
        else:
            try:self.inspection_service=InspectionService()
            except (FileNotFoundError,ValueError):self.inspection_service=None
        self.scheduler=PilotScheduler()
        self.decisions=[];self.decision_counter=0
        self.priority_boundary_counts={}
        self.consumed_pass_on_controls=set()
        self.public_messageboard=[]
        self.closed_messageboard_windows=set()
        self.offered_messageboard_windows=set()
        self.combo_adjudications={}
        self.consumed_combo_adjudications=set()
        for response in combo_adjudications or []:
            proposal_id=str(response.get('proposal_id',''))
            if not proposal_id or proposal_id in self.combo_adjudications:
                raise ValueError('Combo adjudications require unique proposal_id values')
            self.combo_adjudications[proposal_id]=dict(response)
        self.pending_delayed_returns=[]
        self.spell_cast_epoch=0
        self.pilot_terminal=''
        self.catalog_event_dispatcher=CatalogEventDispatcher(sim.CATALOG,TriggerBuilderRegistry())
        self.catalog_trigger_audit=[]
        super().__init__(*args,**kwargs)

    def log(self,etype,actor,card,detail,**extra):
        """Log the event, then invalidate object passes after any zone/control move.

        Card objects are deliberately reused for several nonbattlefield zone
        moves.  Observing the source after every ledger event catches a
        hand-to-graveyard-to-hand round trip even when Python identity and the
        final zone are unchanged by the next priority window.
        """
        if self.planning_contract>=3:
            active=self.turn_order[self.active_idx] if getattr(self,'turn_order',None) else None
            extra.update(active_player=active,seat_turn=self.planning_turns.get(active,0))
        result=super().log(etype,actor,card,detail,**extra)
        if self.planning_contract>=3:
            for name,player in getattr(self,'players',{}).items():
                before=self._planning_life.get(name,player.life)
                self._planning_life[name]=player.life
                if before!=player.life:
                    super().log('planner_life_change',name,None,'Public life total changed',
                                before=before,after=player.life,active_player=active,seat_turn=self.planning_turns.get(active,0))
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            definition=sim.CARDDEF.get(card)
            spell_event=(etype=='cast' or (etype=='counterspell' and definition is not None
                                           and (definition.is_instant or definition.is_sorcery)))
            self.scheduler.observe(self,etype,actor,is_spell=spell_event,targets=extra.get('targets',[]))
        # A whole-stack pass ends on the observed nonempty-to-empty boundary.
        # Clear it here so a trigger that immediately builds a fresh stack
        # cannot inherit the previous stack's suppression.
        if not getattr(self,'stack',[]):
            for player in getattr(self,'players',{}).values():
                player.dungeon.pop('specialized_priority_pass',None)
                if player.dungeon.pop('autopass_stack',None) is not None:
                    super().log('autopass_stack_end',player.name,None,
                                'The current stack became empty; normal priority prompts resume')
        for player in getattr(self,'players',{}).values():
            passes=player.dungeon.get('priority_object_passes',{})
            for uid,entry in list(passes.items()):
                if self.priority_source_zone(player,entry.source)==entry.source_zone:continue
                passes.pop(uid,None)
                self._clear_priority_holds_for_uid(player,uid)
                super().log(
                    'priority_object_pass_end',player.name,entry.source_name,
                    f'{entry.source_name} changed zones or controller; it may open priority prompts again',
                    uid=entry.source_uid,wake_player=entry.wake_player)
            if not passes:player.dungeon.pop('priority_object_passes',None)
        return result

    def eliminate(self,p,reason):
        if p.eliminated:return

        # A player may now leave during an open stack.  Objects that player
        # controls on the stack cease to exist, and permanents they control but
        # do not own return to their owners before the base ownership cleanup.
        # This keeps eliminated-player containers out of later target/combat
        # discovery without pretending that those permanents left the game.
        for permanent in list(p.battlefield):
            if permanent.owner==p.name:continue
            owner=self.players[permanent.owner]
            p.battlefield.remove(permanent)
            permanent.controller=owner.name
            owner.battlefield.append(permanent)
            self.log('control_change',owner.name,permanent.name,
                     f'{permanent.name} returns to {owner.name} as {p.name} leaves the game',
                     uid=permanent.uid,previous_controller=p.name)

        removed_stack=[]
        for item in list(self.stack):
            if not isinstance(item,dict):continue
            controller=item.get('actor') or item.get('controller')
            controller_name=getattr(controller,'name',controller)
            if controller_name==p.name:
                self.stack.remove(item);removed_stack.append(item)
        for item in removed_stack:
            self.log('leaves_game',p.name,item.get('card'),
                     f'{item.get("card") or "A stack object"} leaves the stack with {p.name}',
                     uid=item.get('uid'),zone='stack')

        self.pending_delayed_returns=[
            row for row in self.pending_delayed_returns
            if row.get('controller')!=p.name]
        # Arcane Denial's delayed draw record names both the controller of the
        # countered spell and the Denial controller.  Neither half may survive
        # the departure of either recipient; otherwise a later upkeep would
        # reopen a decision for a player who is no longer in the game.
        self.pending_arcane_denials=[
            row for row in self.pending_arcane_denials
            if p.name not in {row.get('spell_controller'),row.get('denial_controller')}]
        for key in ('announced_spells','resolving_cast_modes','priority_holds',
                    'priority_object_passes','priority_seat_snooze',
                    'specialized_priority_pass','autopass_stack','next_cast_autoresolve'):
            p.dungeon.pop(key,None)

        # Leaving permanents can create triggers controlled by surviving
        # players.  Collect them as one batch, discard triggers controlled by
        # the departed player, then use the normal APNAP resolver.
        departures=[]
        self.__dict__.setdefault('_ltb_trigger_frames',[]).append(departures)
        try:super().eliminate(p,reason)
        finally:self._ltb_trigger_frames.pop()

        if p.name=='Reaminatour' and p.eliminated:
            self.pilot_terminal='reaminatour_eliminated'
            self.win_turn=self.turn_number
            self.win_reason=f'Reaminatour eliminated: {reason}'
            self.log('pilot_game_stop',p.name,None,
                     'Pilot game ends immediately because Reaminatour was eliminated')
        surviving_triggers=[
            trigger for trigger in departures
            if not trigger['controller'].eliminated]
        if surviving_triggers and not self.winner and not self.pilot_terminal:
            active=self.players[self.turn_order[self.active_idx]]
            if active.eliminated:
                active=next(player for player in self.players.values() if not player.eliminated)
            self.resolve_simultaneous_triggers(
                f'{p.name} leaves the game',surviving_triggers,starter=active)

    @staticmethod
    def _battlefield_identity_visible_to(actor,q):
        """Return only whether a battlefield object's identity is pilot-visible.

        Runtime permanents intentionally retain their true name and printed
        characteristics while face down.  Decision context must treat those as
        referee-only fields unless the viewing pilot is entitled to look.
        """
        metadata=getattr(q,'metadata',{}) or {}
        known_to=metadata.get('known_to',getattr(q,'known_to',None))
        visible_to=metadata.get('visible_to',getattr(q,'visible_to',None))
        if known_to is not None:return actor in set(known_to if isinstance(known_to,(list,tuple,set,frozenset)) else [known_to])
        if visible_to is not None:return actor in set(visible_to if isinstance(visible_to,(list,tuple,set,frozenset)) else [visible_to])
        hidden=bool(
            metadata.get('identity_hidden') or metadata.get('hidden_identity') or
            metadata.get('hidden') or getattr(q,'identity_hidden',False) or
            getattr(q,'hidden_identity',False)
        )
        face_down=bool(metadata.get('face_down') or getattr(q,'face_down',False))
        if hidden:return False
        if not face_down:return True
        return actor==q.controller

    def strategic_state_summary(self, actor:str)->str:
        p=self.players.get(actor)
        if not p:return ''
        def life_display(player):
            return 'infinite (adjudicated loop)' if player.dungeon.get('adjudicated_infinite_life') else str(player.life)
        floating=''.join(p.dungeon.get('domri_floating',[])) or 'none'
        # The public player row below is the canonical mana rendering for every
        # seat, including the actor.  Keep the private-hand prelude compact and
        # do not repeat the actor's same mana calculation here.
        lines=[f'{actor}: life {life_display(p)}; hand [{", ".join(c.d.name for c in p.hand)}]; treasures={p.treasures}; floating mana={floating}']
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            lines=[f'{actor}: life {life_display(p)}; treasures={p.treasures}; floating mana={floating}',
                   'Your hand: '+('; '.join(f'{c.d.name} [{c.uid}] {c.d.mana_cost or "no mana cost"} | {c.d.type_line}' for c in p.hand) or 'empty')]
        for name,pp in self.players.items():
            bf=[]
            for q in pp.battlefield:
                identity_visible=self._battlefield_identity_visible_to(actor,q)
                extra=[]
                if q.tapped: extra.append('tapped')
                if q.counters: extra.append(str(q.counters))
                if q.copy_of and identity_visible: extra.append('copy='+q.copy_of)
                display_name=q.name if identity_visible else 'Unknown face-down card'
                bf.append(display_name+(f' ({"; ".join(extra)})' if extra else ''))
            mana=self.mana_availability(pp)
            colors=' '.join(f'{color}={amount}' for color,amount in mana['by_color'].items())
            commander=(pp.commander.d.name+' (command zone)' if pp.commander else 'not in command zone')
            lines.append(f'  {name}: life={life_display(pp)}{" ELIM" if pp.eliminated else ""}; modeled mana available={mana["total"]} total ({colors}); color values are independent maxima; BF=[{", ".join(bf)}]; CMD=[{commander}]; hand={len(pp.hand)}; GY=[{", ".join(c.d.name for c in pp.graveyard)}]; EX=[{", ".join(c.d.name for c in pp.exile)}]')
        linked=[]
        for name,pp in self.players.items():
            if not pp.eliminated and pp.dungeon.get('ecd_tax_effects'):
                amount=2*pp.dungeon['ecd_tax_effects']
                lines.append(f'  Elspeth Conquers Death resolved effect: {name}\'s opponents pay {{{amount}}} more for noncreature spells until {name}\'s next turn begins, even if the Saga leaves.')
        for _,source in self.all_permanents():
            for uid in source.metadata.get('linked_exiled_uids',[]):
                exiled=next((card for owner in self.players.values() for card in owner.exile if card.uid==uid),None)
                commander=next((owner.commander for owner in self.players.values()
                                if owner.commander and owner.commander.uid==uid),None)
                if exiled:linked.append(f'{source.name} links {exiled.d.name} in exile; it returns when {source.name} leaves')
                elif commander:linked.append(f'{commander.d.name} is in the command zone and will not return when {source.name} leaves')
        if linked:lines.append('  Linked-zone status: '+' | '.join(linked))
        pass_rows=self.describe_priority_object_passes(p)
        if pass_rows:
            lines.append('  Passed-on priority objects: '+' | '.join(
                f'{entry["source_name"]} [{entry["source_uid"]}] '
                f'({entry["wake_description"]}; still selectable when another object opens priority)'
                for entry in pass_rows))
        transcript=self.public_messageboard[-MESSAGEBOARD_RECENT_LIMIT:]
        if transcript:
            hidden=len(self.public_messageboard)-len(transcript)
            lines.append(
                f'  Public messageboard ({len(self.public_messageboard)} message(s); '
                f'{hidden} earlier omitted here). {MESSAGEBOARD_UNTRUSTED_HELP}')
            for entry in transcript:
                target=self._messageboard_address_label(entry.get('address',{}))
                reply=f' reply to {entry["reply_to"]}' if entry.get('reply_to') else ''
                lines.append(
                    f'    [{entry["message_id"]}] {entry["author"]} -> {target}{reply}: '
                    +json.dumps(entry['text'],ensure_ascii=False))
        return '\n'.join(lines)

    def note_timing_affordance(self,p,c):
        # Revision 2 replaces this repeated Oracle-text reminder with concrete
        # legal actions plus on-demand inspection.  Retain the legacy store only
        # so an already-started revision-1 game replays byte-for-byte as before.
        if self.decision_surface_revision>=2:return
        note=None;windows=[];rules=' '.join(c.d.text.split())
        if c.d.is_instant:
            windows=['response','phase_end','end_step','upkeep']
            note='Instant-speed spell. '+rules
        elif self.has_flash_timing(c):
            windows=['response','phase_end','end_step','upkeep'];note='Flash spell. '+rules
        elif 'Channel' in c.d.text:
            windows=['response','phase_end','end_step','upkeep'];note='Channel ability. '+rules
        elif self.has_material_priority_ability(c.d):
            windows=['response','phase_end','end_step','upkeep'];note='Activated ability available from the battlefield when costs and targets are legal. '+rules
        if not note:return
        notes=p.dungeon.setdefault('timing_affordances',{})
        if c.uid in notes:return
        notes[c.uid]={'card':c.d.name,'windows':windows,'note':note}
        self.log('timing_affordance',p.name,c.d.name,note,uid=c.uid,windows=windows)

    def redacted_snapshot(self, actor:str)->Dict[str,Any]:
        """Persist exact public state without ordered libraries or opposing hands."""
        state=self.snapshot()
        for name,player in state['players'].items():
            if self.players[name].dungeon.get('adjudicated_infinite_life'):
                player['life_is_infinite']=True
            player['mana_availability']=self.mana_availability(self.players[name])
            player['library_count']=len(player.pop('library'))
            hand=player.pop('hand')
            if name==actor:
                player['hand']=hand
                player['floating_mana']=list(self.players[name].dungeon.get('domri_floating',[]))
            else:
                player['hand_count']=len(hand)
                if self.planning_contract>=2:player.pop('miracle_uid',None)
            live_by_uid={q.uid:q for q in self.players[name].battlefield}
            for permanent in player['battlefield']:
                live=live_by_uid.get(permanent['uid'])
                if live is None or self._battlefield_identity_visible_to(actor,live):continue
                permanent['name']='Unknown face-down card'
                permanent['identity_visible']=False
                for hidden_field in (
                    'copy_of','base_power','base_toughness','power','toughness',
                    'printed_keywords','effective_keywords','effective_types',
                    'effective_subtypes','effective_colors',
                ):
                    permanent.pop(hidden_field,None)
                metadata=getattr(live,'metadata',{}) or {}
                public_metadata={}
                if metadata.get('face_down'):public_metadata['face_down']=True
                if metadata.get('phased_out'):public_metadata['phased_out']=True
                permanent['metadata']=public_metadata
        if self.planning_contract>=3:
            state['planning_clock']={'active_player':self.turn_order[self.active_idx],
                                     'seat_turns':dict(self.planning_turns)}
        recent=[dict(entry) for entry in self.public_messageboard[-MESSAGEBOARD_RECENT_LIMIT:]]
        state['public_messageboard']={
            'schema':1,'visibility':'public','message_count':len(self.public_messageboard),
            'recent_messages':recent,
            'omitted_earlier_count':len(self.public_messageboard)-len(recent),
            'help':MESSAGEBOARD_UNTRUSTED_HELP+' Use `inspect messageboard` for the complete transcript.',
        }
        return state

    def _with_pass_on_management(self,p,request,applied_controls=()):
        """Attach only the active pilot's live prompt-suppression controls."""
        result=dict(request);result.pop('pass_on_management',None)
        if self.planning_contract>=2:result['planning_contract']=self.planning_contract
        if self.turn_batches:result['turn_batches']=1
        living=[name for name in self.turn_order if not self.players[name].eliminated]
        active=self.turn_order[self.active_idx]
        following=[self.turn_order[(self.active_idx+offset)%len(self.turn_order)]
                   for offset in range(1,len(self.turn_order)+1)]
        result['turn_order']={'seating':list(self.turn_order),'living':living,
            'active_player':active,'acting_pilot':p.name,
            'next_player':next((name for name in following if name in living),None),
            'direction':'listed order, then wrap; eliminated players are skipped'}
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            result['scheduler']=self.scheduler.metadata(self,p)
            return result
        entries=self.describe_priority_object_passes(p)
        if entries:
            result['pass_on_management']={
                'private':True,'choice':PASS_ON_MANAGEMENT_CHOICE,
                'consumes_decision':False,'entry_count':len(entries),'entries':entries,
                'help':(
                    'Review, explicitly unsnooze, unsnooze all, or reschedule these objects. '
                    'The pending gameplay decision remains open; this action never creates priority.'
                ),
            }
        if applied_controls:result['pass_on_controls']=[dict(value) for value in applied_controls]
        else:result.pop('pass_on_controls',None)
        return result

    def _apply_replayed_pass_on_controls(self,p,build_request):
        """Apply ordered controls and rebuild the same decision after each one."""
        applied=[]
        provider=getattr(self.decision_tape,'next_pass_on_control',None)
        while True:
            request,payload=build_request(applied)
            if provider is None:return request,payload
            control=provider(request)
            if control is None:return request,payload
            self.apply_priority_object_pass_control(p,control)
            applied.append(control)

    def record_decision(self,did,kind,actor,prompt,options,chosen_idx,rationale,
                        pilot_memory_ids=(),pass_on_controls=(),rationale_policy=None):
        chosen=None if chosen_idx is None else options[chosen_idx]
        rec={
            'decision_id':did,'game':self.game_no,'seed':self.seed,'seq_before':self.seq,
            'round':self.round,'turn':self.turn_number,'phase':self.phase,
            'actor':actor,'kind':kind,'prompt':prompt,
            'options':[o['label'] for o in options],
            'chosen':None if chosen is None else chosen['label'],
            'rationale':rationale,'pilot_memory_ids':list(pilot_memory_ids),
        }
        if self.capture_decision_state:rec['state_before']=self.redacted_snapshot(actor)
        if pass_on_controls:rec['pass_on_controls']=[dict(value) for value in pass_on_controls]
        if rationale_policy:
            rec['rationale_policy']=dict(rationale_policy)
            parent=rationale_policy.get('parent_decision_id')
            if parent:rec['rationale_parent_decision_id']=parent
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            directive=self._decision_auxiliary_payload(did).get('scheduler')
            automatic=self._decision_auxiliary_payload(did).get('batch',{}).get('automatic_priority')
            if self.turn_batches and automatic and kind=='priority_action' and chosen is None:
                # An approved priority pass is not a new snooze instruction:
                # preserve existing object schedules and their exact deadlines.
                rec['scheduler_preserved']=True
            else:self.scheduler.accept(self,self.players[actor],directive,did)
            rec['scheduler']=directive
        self.decisions.append(rec)
        self.log('llm_decision',actor,None,
                 f'{kind}: '+(rec['chosen'] or 'PASS')+(f' | {rationale}' if rationale else ''),
                 decision_id=did,decision_kind=kind,options=rec['options'])

    def record_multi_decision(self,did,kind,actor,prompt,options,chosen_indexes,rationale,
                              pilot_memory_ids=(),pass_on_controls=(),rationale_policy=None):
        chosen=[options[index] for index in chosen_indexes]
        rec={
            'decision_id':did,'game':self.game_no,'seed':self.seed,'seq_before':self.seq,
            'round':self.round,'turn':self.turn_number,'phase':self.phase,
            'actor':actor,'kind':kind,'prompt':prompt,
            'options':[option['label'] for option in options],
            'chosen':[option['label'] for option in chosen],
            'rationale':rationale,'pilot_memory_ids':list(pilot_memory_ids),
        }
        if self.capture_decision_state:rec['state_before']=self.redacted_snapshot(actor)
        if pass_on_controls:rec['pass_on_controls']=[dict(value) for value in pass_on_controls]
        if rationale_policy:rec['rationale_policy']=dict(rationale_policy)
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            directive=self._decision_auxiliary_payload(did).get('scheduler')
            self.scheduler.accept(self,self.players[actor],directive,did)
            rec['scheduler']=directive
        self.decisions.append(rec)
        self.log('llm_decision',actor,None,
                 f'{kind}: '+(', '.join(rec['chosen']) if rec['chosen'] else 'CHOOSE NONE')+(f' | {rationale}' if rationale else ''),
                 decision_id=did,decision_kind=kind,options=rec['options'])

    def record_value_decision(self,did,kind,actor,prompt,value,rationale,
                              pilot_memory_ids=(),pass_on_controls=(),rationale_policy=None):
        rec={
            'decision_id':did,'game':self.game_no,'seed':self.seed,'seq_before':self.seq,
            'round':self.round,'turn':self.turn_number,'phase':self.phase,
            'actor':actor,'kind':kind,'prompt':prompt,'choice_value':dict(value),
            'rationale':rationale,'pilot_memory_ids':list(pilot_memory_ids),
        }
        if self.capture_decision_state:rec['state_before']=self.redacted_snapshot(actor)
        if pass_on_controls:rec['pass_on_controls']=[dict(value) for value in pass_on_controls]
        if rationale_policy:rec['rationale_policy']=dict(rationale_policy)
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            directive=self._decision_auxiliary_payload(did).get('scheduler')
            self.scheduler.accept(self,self.players[actor],directive,did)
            rec['scheduler']=directive
        self.decisions.append(rec)
        rendered=(json.dumps(value,separators=(',',':')) if kind in {'blockers_declaration','combat_damage_batch'} else
                  f"{value['occurrences']} {value['edge']} of {value['phase'].replace('_',' ')}")
        self.log('llm_decision',actor,None,
                 f'{kind}: {rendered}'+(f' | {rationale}' if rationale else ''),
                 decision_id=did,decision_kind=kind,choice_value=dict(value))

    def _decision_card_names(self,objects):
        """Extract catalog identities from option payloads without traversing players."""
        names=[];seen_objects=set()
        def visit(value,depth=0):
            if value is None or depth>4:return
            ident=id(value)
            if ident in seen_objects:return
            seen_objects.add(ident)
            definition=getattr(value,'d',None)
            name=getattr(definition,'name',None) or (getattr(value,'name',None) if hasattr(value,'uid') else None)
            if name and name in sim.CARDDEF:names.append(name)
            if isinstance(value,dict):
                for item in value.values():visit(item,depth+1)
            elif isinstance(value,(tuple,list,set)):
                for item in value:visit(item,depth+1)
        for value in objects:visit(value)
        return list(dict.fromkeys(names))

    @staticmethod
    def _rank_decision_memory(candidates,current_names,hand_names):
        """Deduplicate and rank private strategy notes by decision relevance.

        Candidate enumeration is deliberately not a priority signal: option
        order can change during replay and deck/profile serialization is an
        implementation detail.  Locked/contextual learning wins, then notes for
        cards represented in the current options, then other cards in hand.
        Multi-piece package notes receive a modest synergy bonus and basic-land
        boilerplate loses ties to strategically denser material.
        """
        current={str(name).casefold() for name in current_names}
        hand={str(name).casefold() for name in hand_names}
        unique={}
        for index,note in enumerate(candidates):
            row=dict(note)
            key=(
                str(row.get('memory_kind','card')),
                str(row.get('card_id','')),
                str(row.get('note_id',f'candidate-{index}')),
            )
            unique.setdefault(key,row)

        def score(row):
            related=[str(name) for name in row.get('applicable_card_names',[]) if name]
            if not related and row.get('card_name'):related=[str(row['card_name'])]
            folded={name.casefold() for name in related}
            current_count=len(folded&current)
            hand_count=len(folded&hand)
            package_bonus=(max(0,len(folded&(current|hand))-1)*900
                           if row.get('memory_kind')=='package' else 0)
            card_name=str(row.get('card_name',''))
            definition=sim.CARDDEF.get(card_name)
            basic=bool(definition and definition.type_line.split(' // ')[0].startswith('Basic Land'))
            confidence=row.get('confidence')
            try:confidence_score=int(float(confidence)*100) if confidence is not None else 0
            except (TypeError,ValueError):confidence_score=0
            relevance=(
                (10000 if row.get('locked') else 0)+
                (4000 if row.get('contexts') else 0)+
                (2400 if current_count else 0)+
                (700 if hand_count else 0)+
                package_bonus+
                (0 if basic else 200)+
                confidence_score
            )
            return (
                -relevance,
                0 if row.get('memory_kind','card')=='card' else 1,
                card_name.casefold(),
                str(row.get('note_id','')),
            )
        return sorted(unique.values(),key=score)

    def _pilot_decision_context(self,p,kind,objects,*,presentation=True):
        service=self.inspection_service
        if service is None:return [],'',[],{'candidate_count':0,'delivered_count':0,'omitted_count':0}
        names=self._decision_card_names(objects)
        hand_names=[card.d.name for card in p.hand]
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            hand_names=list(dict.fromkeys(hand_names+[q.name for q in p.battlefield
                if self._battlefield_identity_visible_to(p.name,q)]+[c.d.name for c in p.graveyard]))
        contexts=[kind,self.phase,'priority' if 'priority' in kind else 'decision']
        decision_memory=getattr(service,'decision_memory',None)
        if self.decision_surface_revision>=2 and callable(decision_memory):
            candidates=decision_memory(
                p.name,names,contexts,hand_card_refs=hand_names)
        else:
            # Compatibility for deliberately small inspection fakes and legacy
            # adapters.  Revision-1 games retain their historical ordering.
            candidates=service.pilot_memory(p.name,names,contexts)
        if self.decision_surface_revision>=2:
            candidates=self._rank_decision_memory(candidates,names,hand_names)
        memory=(candidates[:PILOT_MEMORY_LIMIT]
                if self.decision_surface_revision>=2 else candidates)
        delivery={
            'candidate_count':len(candidates),'delivered_count':len(memory),
            'omitted_count':len(candidates)-len(memory),'limit':PILOT_MEMORY_LIMIT,
        }
        if presentation and self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            delivery['full_candidates']=candidates
        if not presentation:return memory,'',[],delivery
        # Revised requests carry one canonical structured copy.  The campaign
        # renderer is responsible for presenting it; seat_view no longer repeats
        # the same private text.
        text=('' if self.decision_surface_revision>=2 else
              service.render_pilot_memory(p.name,names,contexts))
        try:index=service.inspectable_object_index(self,p.name)
        except (KeyError,ValueError,TypeError):index=[]
        return memory,text,index,delivery

    def _decision_needs_presentation(self,did):
        predicate=getattr(self.decision_tape,'needs_presentation',None)
        return True if not callable(predicate) else bool(predicate(did))

    def _hydrate_inserted_request(self,request,builder):
        """Rebuild a rare displaced replay request with its full private view."""
        hydrated=builder(request.get('pass_on_controls',[]),True)
        if isinstance(hydrated,tuple):hydrated=hydrated[0]
        if request.get('rebase_existing_decision'):
            hydrated['rebase_existing_decision']=True
        path=getattr(self.decision_tape,'request_path',None)
        if path is not None:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(hydrated,indent=2),encoding='utf8')
        return NeedDecision(hydrated)

    @staticmethod
    def _private_decision_item(row):
        """Project one complete, bounded decision record back to its own pilot."""
        if row is None:return None
        keys=(
            'decision_id','game','seed','seq_before','round','turn','phase','actor',
            'kind','prompt','options','chosen','choice_value','rationale',
            'rationale_policy','rationale_parent_decision_id',
        )
        return {
            'schema':2,'private':True,'source':'accepted_replay_branch',
            **{key:row.get(key) for key in keys if key in row},
        }

    def _previous_pilot_decision(self,p,*,with_rationale=False):
        """Return a full prior item, optionally requiring a recorded rationale."""
        for row in reversed(self.decisions):
            if row.get('actor')!=p.name:continue
            if with_rationale and not str(row.get('rationale') or '').strip():continue
            return self._private_decision_item(row)
        return None

    def _continuity_context(self,p):
        return {
            'previous_pilot_decision':self._previous_pilot_decision(p),
            'previous_rationalized_decision':self._previous_pilot_decision(
                p,with_rationale=True),
        }

    def planning_boundary(self,p,reason):
        self.log('planner_turn_boundary',p.name,None,reason,reason=reason)
        opening=reason=='opening_hand_settled'
        boundary={'actor':p.name,'required':True,'scope':'both','reason':reason,
                  'cadence_id':f'{p.name}|turn:{self.turn_number}|{reason}',
                  'event_seq':self.seq,'turn':self.turn_number,
                  'seat_turn':self.planning_turns.get(p.name,0),
                  'opening_long_term_plan_required':opening}
        if opening:
            boundary['opening_information_boundary']={'required_clauses':[
                f'{name}: {OPENING_OPPONENT_KNOWLEDGE_QUALIFIER}' for name in self.turn_order if name!=p.name]}
        self.planning_boundaries.append(boundary)

    def _planning_checkpoint(self,p,*,for_planner=False):
        """Return a deterministic first-draw planning obligation, if one is due."""
        if self.planning_contract>=2 and not for_planner:return None
        if self.decision_surface_revision<DRAW_PLANNING_SURFACE_REVISION:return None
        pending=p.dungeon.get(PLANNING_CHECKPOINT_FIELD)
        if not isinstance(pending,dict) or pending.get('turn')!=self.turn_number:return None
        opening_long_term_required=bool(
            self.decision_surface_revision>=OPENING_REGIME_SURFACE_REVISION
            and pending.get('opening_long_term_plan_required')
        )
        checkpoint={
            'schema':1,'private':True,'required':True,
            'cadence':'first_draw_each_turn','cadence_id':pending['cadence_id'],
            'turn':pending['turn'],'draw_event_seq':pending['draw_event_seq'],
            'completion':'batched_short_term_replacement_and_long_term_review',
            'long_term_action_required':(
                'revise' if opening_long_term_required else 'keep_or_revise'
            ),
            'help':planning_checkpoint_help(
                opening_long_term_required=opening_long_term_required),
        }
        if opening_long_term_required:
            required_opponents=[
                name for name in self.turn_order
                if name!=p.name and not self.players[name].eliminated
            ]
            checkpoint.update({
                'schema':2,
                'opening_long_term_plan_required':True,
                'required_opponent_postures':required_opponents,
                'opening_information_boundary':{
                    'schema':1,
                    'required_qualifier':OPENING_OPPONENT_KNOWLEDGE_QUALIFIER,
                    'required_clauses':[
                        f'{name}: {OPENING_OPPONENT_KNOWLEDGE_QUALIFIER}'
                        for name in required_opponents
                    ],
                    'allowed_sources':[
                        'actor_visible_request',
                        'public_game_history',
                        'this_pilots_private_context',
                    ],
                    'forbidden_sources':[
                        'other_pilots_private_seed_plans',
                        'other_pilots_hidden_hands_or_inspections',
                        'other_pilots_private_gameplans',
                        'unrevealed_decklist_or_future_library_information',
                    ],
                },
            })
        return checkpoint

    def _complete_planning_checkpoint(self,p,request):
        checkpoint=request.get(PLANNING_CHECKPOINT_FIELD) or {}
        pending=p.dungeon.get(PLANNING_CHECKPOINT_FIELD) or {}
        if checkpoint.get('cadence_id') and checkpoint.get('cadence_id')==pending.get('cadence_id'):
            p.dungeon.pop(PLANNING_CHECKPOINT_FIELD,None)

    def _rationale_policy(self,p,kind,prompt,objects,options):
        """Describe when an external answer must include gameplay rationale."""
        if kind=='blockers_declaration':
            return {'schema':1,'mode':'required','reason':'combat_blocking',
                'help':'Explain the overall defensive allocation once, including deliberate unblocked attackers.'}
        if kind=='combat_damage_batch':
            return {'schema':1,'mode':'required','reason':'combat_damage',
                'help':'Explain the overall damage distribution once, including trample and deliberate nonlethal allocations.'}
        if kind in {'trigger_order','trigger_order_selection'}:
            return {
                'schema':1,'mode':'required','reason':'trigger_ordering',
                'help':'Explain why this trigger order best serves the current line.',
            }
        activated_context=self.__dict__.get('_activated_ability_decision_root') or {}
        activated_root=(
            activated_context.get('decision_id')
            if isinstance(activated_context,dict) else activated_context
        )
        targeting=('target' in kind.casefold() or re.search(r'\btargets?\b',prompt,re.I))
        activated_actor=(
            activated_context.get('actor')
            if isinstance(activated_context,dict) else p.name
        )
        if activated_root and activated_actor==p.name and targeting:
            return {
                'schema':1,'mode':'required','reason':'activated_ability_targeting',
                'parent_decision_id':activated_root,
                'help':'Explain the target choice for this activated ability.',
            }
        required_indexes=[]
        for index,obj in enumerate(objects):
            action=obj
            if (
                isinstance(action,tuple) and action
                and action[0]=='priority_action' and len(action)>1
            ):
                action=action[1]
            action_kind=(action[0] if isinstance(action,tuple) and action else None)
            if isinstance(action_kind,str) and action_kind in {
                'cast','commander','escape_uro'
            }:
                required_indexes.append(index)
            elif index<len(options) and str(options[index].get('label','')).upper().startswith('CAST '):
                required_indexes.append(index)
        if kind=='miracle_cast':
            required_indexes.extend(
                index for index,obj in enumerate(objects) if obj is True)
        elif kind=='rishkars_expertise_cast':
            required_indexes.extend(range(len(objects)))
        required_indexes=sorted(set(required_indexes))
        if required_indexes:
            return {
                'schema':1,'mode':'required_for_choices',
                'reason':'spellcasting','choice_indexes':required_indexes,
                'help':'A spellcasting choice requires a strategic rationale.',
            }
        return {
            'schema':1,'mode':'optional','reason':'ordinary_decision',
            'help':'A concise rationale is optional for this decision.',
        }

    def _decision_auxiliary_payload(self,did):
        provider=getattr(self.decision_tape,'auxiliary_payload',None)
        return provider(did) if callable(provider) else {}

    @staticmethod
    def _spellcasting_choice_indexes(rationale_policy):
        if not isinstance(rationale_policy,dict):return []
        if rationale_policy.get('reason')!='spellcasting':return []
        return list(rationale_policy.get('choice_indexes') or [])

    def _request_decision(self,kind,p,prompt,objects,label_fn,allow_pass=False,
                          gameplan_access=False,opening_gameplan_context=None,
                          request_metadata=None):
        if self.pilot_terminal:raise PilotGameComplete(self.win_reason)
        objects=list(objects);opts=[{'label':label_fn(x),'obj':x} for x in objects]
        if not opts:return None
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            if self.scheduler.before_decision(self,p,passable=allow_pass):
                self.log('scheduler_suppressed',p.name,None,kind,
                         legal_options=[option['label'] for option in opts])
                return None
        elif self.decision_surface_revision>=PASSING_ACCELERATION_SURFACE_REVISION:
            snooze=self.active_priority_seat_snooze(p,kind)
            if snooze and allow_pass:
                self.log('priority_seat_snooze_auto',p.name,None,
                         f'{kind}: optional decision automatically passed while SNOOZE ALL is active')
                return None
            if snooze:
                self.clear_priority_seat_snooze(
                    p,f'{kind} requires a choice the referee cannot legally infer')
        if len(opts)==1 and not allow_pass:
            self.log('forced_choice',p.name,None,f'{kind}: {opts[0]["label"]}')
            return opts[0]['obj']
        if self.async_diplomacy:
            from .diplomacy import replay
            replay(self)
        self.decision_counter+=1
        did=f'G{self.game_no:02d}-D{self.decision_counter:04d}'
        presentation=self._decision_needs_presentation(did)
        def build_request(applied,full=presentation):
            memory,memory_text,inspectable,memory_delivery=self._pilot_decision_context(
                p,kind,objects,presentation=full)
            current_opts=[{'label':label_fn(x),'obj':x} for x in objects]
            request={
                'decision_id':did,'game':self.game_no,'seed':self.seed,'round':self.round,'turn':self.turn_number,
                'phase':self.phase,'actor':p.name,'kind':kind,'prompt':prompt,
                'options':[o['label'] for o in current_opts],'allow_pass':allow_pass,
                'gameplan_access':bool(gameplan_access),'pilot_memory':memory,
                'pilot_memory_delivery':memory_delivery,
            }
            request['rationale_policy']=self._rationale_policy(
                p,kind,prompt,objects,current_opts)
            if self.planning_contract>=4:
                from .sequence_contract import options
                request['symbolic_options']=options(objects)
            spell_indexes=self._spellcasting_choice_indexes(request['rationale_policy'])
            if (
                PASSING_ACCELERATION_SURFACE_REVISION<=self.decision_surface_revision<SCHEDULER_SURFACE_REVISION
                and spell_indexes
            ):
                request['autoresolve']={
                    'schema':1,'eligible_choice_indexes':spell_indexes,
                    'help':(
                        'Optional: attach --autoresolve to a spellcasting choice. If the '
                        'spell was cast onto an empty stack, your priority is automatically '
                        'passed on that stack; any new spell immediately wakes you.'
                    ),
                }
            planning=self._planning_checkpoint(p)
            if planning:request[PLANNING_CHECKPOINT_FIELD]=planning
            if full:
                seat_view=self.strategic_state_summary(p.name)
                request.update({
                    'seat_view':seat_view,'pilot_memory':memory,
                    **self._continuity_context(p),
                    'public_state':self.redacted_snapshot(p.name),
                    'inspectable_objects':inspectable,'inspection_help':INSPECTION_HELP,
                })
            if opening_gameplan_context is not None:
                request['opening_gameplan_context']=bool(opening_gameplan_context)
            if request_metadata:
                overlap=set(request)&set(request_metadata)
                if overlap:
                    raise ValueError('request_metadata cannot replace core fields: '+', '.join(sorted(overlap)))
                request.update(request_metadata)
            if self.decision_roles:
                request['decision_roles']=1
                from .decision_roles import proposal_by_id
                for index,obj in enumerate(objects):
                    if isinstance(obj,tuple) and len(obj)==3 and obj[0]=='propose_combo_loop':
                        key=obj[2]['planner_proposal_id']
                        request['planner_combo']={'option_index':index,'proposal_id':key,**proposal_by_id(self,key)}
            return self._with_pass_on_management(p,request,applied),current_opts
        try:
            request,opts=self._apply_replayed_pass_on_controls(p,build_request)
            ix,rationale=self.decision_tape.resolve(request)
        except NeedDecision as exc:
            if presentation:raise
            raise self._hydrate_inserted_request(exc.request,build_request)
        self._complete_planning_checkpoint(p,request)
        self._last_decision_id=did;self._last_decision_rationale=rationale
        auxiliary=self._decision_auxiliary_payload(did)
        if kind=='messageboard_response':
            self._last_messageboard_text=(
                auxiliary.get('messageboard') or {}
            ).get('text','')
        memory=list(request.get('pilot_memory') or [])
        if not memory:
            memory=self._pilot_decision_context(
                p,kind,objects,presentation=False)[0]
        self.record_decision(
            did,kind,p.name,prompt,opts,ix,rationale,[row['note_id'] for row in memory],
            request.get('pass_on_controls',[]),request.get('rationale_policy'))
        pass_on_payload=auxiliary.get('pass_on_batch')
        if pass_on_payload is not None:
            meta=request.get('pass_on_batch') or {}
            if meta.get('schema')!=1 or ix!=meta.get('option_index'):
                raise UnrefereedDecisionError(
                    'Batched PASS ON payload was attached to the wrong decision choice')
            if not isinstance(pass_on_payload,dict):
                raise UnrefereedDecisionError('Batched PASS ON payload must be an object')
        seat_snooze=auxiliary.get('seat_snooze')
        if seat_snooze is not None:
            if (
                not isinstance(seat_snooze,dict)
                or set(seat_snooze)!={'schema','schedule'}
                or seat_snooze.get('schema')!=1
                or ix is not None
                or not (request.get('seat_snooze') or {}).get('available')
            ):
                raise UnrefereedDecisionError(
                    'SNOOZE ALL payload is invalid for this decision choice')
            if seat_snooze.get('schedule') is not None:
                try:parse_pass_on_schedule(seat_snooze['schedule'])
                except ValueError as exc:
                    raise UnrefereedDecisionError(f'Invalid SNOOZE ALL schedule: {exc}') from exc
        cast_control=auxiliary.get('cast_control')
        if cast_control is not None:
            if (
                not isinstance(cast_control,dict)
                or set(cast_control)!={'schema','autoresolve'}
                or cast_control.get('schema')!=1
                or cast_control.get('autoresolve') is not True
            ):
                raise UnrefereedDecisionError('Invalid spell autoresolve payload')
            eligible=set((request.get('autoresolve') or {}).get('eligible_choice_indexes') or [])
            if ix not in eligible:
                raise UnrefereedDecisionError('Autoresolve was attached to a non-spell choice')
        if ix is None:
            if seat_snooze:
                return ('snooze_all_priority',None,dict(seat_snooze))
            return None
        if cast_control is not None:
            p.dungeon['next_cast_autoresolve']={
                'decision_id':did,'choice_index':ix,
            }
        chosen=opts[ix]['obj']
        if isinstance(chosen,tuple) and len(chosen)==3 and chosen[0]=='propose_combo_loop':
            if chosen[2].get('planner_proposal_id'):
                from .decision_roles import proposal_by_id
                chosen=(chosen[0],chosen[1],{**chosen[2],'proposal_text':proposal_by_id(self,chosen[2]['planner_proposal_id'])['proposal_text']})
            chosen=(chosen[0],chosen[1],{
                **chosen[2],'proposal_text':chosen[2].get('proposal_text',str(rationale).strip()),'proposal_decision_id':did,
            })
        if isinstance(chosen,tuple) and len(chosen)==3 and chosen[0]=='messageboard_open':
            payload=auxiliary.get('messageboard') or {}
            chosen=(chosen[0],chosen[1],{
                **chosen[2],**payload,'message_decision_id':did,
            })
        if isinstance(chosen,tuple) and len(chosen)==3 and chosen[0]=='messageboard_address':
            chosen=(chosen[0],chosen[1],{
                **chosen[2],'message_text':str(rationale),
                'message_decision_id':did,
            })
        return chosen

    def _request_pass_on_schedule(self,p,source):
        """Request an arbitrary positive occurrence without an option explosion."""
        if self.pilot_terminal:raise PilotGameComplete(self.win_reason)
        if self.async_diplomacy:
            from .diplomacy import replay
            replay(self)
        self.decision_counter+=1;did=f'G{self.game_no:02d}-D{self.decision_counter:04d}'
        prompt=(
            f'PASS ON {self.priority_source_name(source)} [{source.uid}]: choose when it should '
            'begin opening prompts again. Enter N beginning|end of PHASE; 1 means the next '
            'matching boundary.'
        )
        presentation=self._decision_needs_presentation(did)
        def build_request(applied,full=presentation):
            memory,memory_text,inspectable,memory_delivery=self._pilot_decision_context(
                p,'pass_on_schedule',[source],presentation=full)
            request={
                'decision_id':did,'game':self.game_no,'seed':self.seed,'round':self.round,
                'turn':self.turn_number,'phase':self.phase,'actor':p.name,'kind':'pass_on_schedule',
                'prompt':prompt,'options':[],'allow_pass':False,'response_type':'pass_on_schedule',
                'response_help':(
                    'Examples: "1 beginning of upkeep", "3 end of combat", '
                    '"next beginning of end step". Phases/steps: upkeep, draw, precombat main, '
                    'combat, postcombat main, end step.'
                ),
                'gameplan_access':True,'pilot_memory':memory,
                'pilot_memory_delivery':memory_delivery,
            }
            request['rationale_policy']=self._rationale_policy(
                p,'pass_on_schedule',prompt,[source],[])
            planning=self._planning_checkpoint(p)
            if planning:request[PLANNING_CHECKPOINT_FIELD]=planning
            if full:
                seat_view=self.strategic_state_summary(p.name)
                request.update({
                    'seat_view':seat_view,
                    **self._continuity_context(p),
                    'public_state':self.redacted_snapshot(p.name),
                    'inspectable_objects':inspectable,'inspection_help':INSPECTION_HELP,
                })
            return self._with_pass_on_management(p,request,applied),None
        try:
            request,_=self._apply_replayed_pass_on_controls(p,build_request)
            value,rationale=self.decision_tape.resolve(request)
        except NeedDecision as exc:
            if presentation:raise
            raise self._hydrate_inserted_request(exc.request,build_request)
        self._complete_planning_checkpoint(p,request)
        value=parse_pass_on_schedule(value)
        memory=list(request.get('pilot_memory') or [])
        self._last_decision_id=did;self._last_decision_rationale=rationale
        self.record_value_decision(
            did,'pass_on_schedule',p.name,prompt,value,rationale,
            [row['note_id'] for row in memory],request.get('pass_on_controls',[]),
            request.get('rationale_policy'))
        return value

    def selection_batch_enabled(self):
        return self.selection_batch_after is not None and self.decision_counter>=self.selection_batch_after

    def _request_selection(self,kind,p,prompt,objects,label_fn,*,minimum=0,maximum=None,
                           ordered=False,groups=None):
        """One pilot-authored set or ordering, validated at every submission path.

        Callers must collect all choices before applying effects. No priority,
        revelation, actor handoff, or dependent choice may be crossed here.
        """
        objects=list(objects)
        maximum=len(objects) if maximum is None else min(maximum,len(objects))
        if minimum<0 or maximum<minimum:raise ValueError('Impossible selection bounds')
        metadata={'min_selected':minimum,'max_selected':maximum,'ordered_selection':ordered}
        if groups is not None:
            if len(groups)!=len(objects):raise ValueError('Each selection option needs a group')
            metadata['selection_groups']=groups
            metadata['max_per_group']=1
        return self._request_multi_decision(kind,p,prompt,objects,label_fn,
            allow_pass=minimum==0,request_metadata=metadata,scheduler_passable=False)

    def _request_multi_decision(self,kind,p,prompt,objects,label_fn,allow_pass=False,required=None,
                                request_metadata=None,scheduler_passable=None):
        if self.pilot_terminal:raise PilotGameComplete(self.win_reason)
        objects=list(objects);opts=[{'label':label_fn(value),'obj':value} for value in objects]
        if not opts:return []
        required_objects=list(required or [])
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            passable=allow_pass and not required_objects if scheduler_passable is None else scheduler_passable
            if self.scheduler.before_decision(self,p,passable=passable):
                self.log('scheduler_suppressed',p.name,None,kind,
                         legal_options=[option['label'] for option in opts])
                return []
        if self.async_diplomacy:
            from .diplomacy import replay
            replay(self)
        self.decision_counter+=1
        did=f'G{self.game_no:02d}-D{self.decision_counter:04d}'
        presentation=self._decision_needs_presentation(did)
        def build_request(applied,full=presentation):
            memory,memory_text,inspectable,memory_delivery=self._pilot_decision_context(
                p,kind,objects,presentation=full)
            current_opts=[{'label':label_fn(value),'obj':value} for value in objects]
            required_indexes=[index for index,option in enumerate(current_opts)
                              if option['obj'] in required_objects]
            request={
                'decision_id':did,'game':self.game_no,'seed':self.seed,'round':self.round,'turn':self.turn_number,
                'phase':self.phase,'actor':p.name,'kind':kind,'prompt':prompt,
                'options':[option['label'] for option in current_opts],'allow_pass':allow_pass,
                'multi_select':True,'required_indexes':required_indexes,
                'pilot_memory':memory,'pilot_memory_delivery':memory_delivery,
            }
            if request_metadata:
                overlap=set(request)&set(request_metadata)
                if overlap:raise ValueError('request_metadata cannot replace core fields: '+', '.join(sorted(overlap)))
                request.update(request_metadata)
            if request.get('response_type') in {'block_declaration','combat_damage'}:request['multi_select']=False
            request['rationale_policy']=self._rationale_policy(
                p,kind,prompt,objects,current_opts)
            if self.planning_contract>=4:
                from .sequence_contract import options
                request['symbolic_options']=options(objects)
            planning=self._planning_checkpoint(p)
            if planning:request[PLANNING_CHECKPOINT_FIELD]=planning
            if full:
                seat_view=self.strategic_state_summary(p.name)
                request.update({
                    'seat_view':seat_view,
                    **self._continuity_context(p),
                    'public_state':self.redacted_snapshot(p.name),
                    'inspectable_objects':inspectable,'inspection_help':INSPECTION_HELP,
                })
            return self._with_pass_on_management(p,request,applied),(current_opts,required_indexes)
        try:
            request,(opts,required_indexes)=self._apply_replayed_pass_on_controls(p,build_request)
            indexes,rationale=self.decision_tape.resolve(request)
        except NeedDecision as exc:
            if presentation:raise
            raise self._hydrate_inserted_request(exc.request,build_request)
        if request.get('response_type') in {'block_declaration','combat_damage'}:
            from .structured_choice import validate
            assignment=validate(request,indexes)
            self._complete_planning_checkpoint(p,request)
            self.record_value_decision(did,kind,p.name,prompt,assignment,rationale,
                [row['note_id'] for row in request.get('pilot_memory',[])],request.get('pass_on_controls',[]),request.get('rationale_policy'))
            if request['response_type']=='combat_damage':return assignment
            by_uid={obj.uid:obj for obj in objects}
            return {uid:[by_uid[blocker] for blocker in values] for uid,values in assignment.items()}
        self._complete_planning_checkpoint(p,request)
        # Small custom test tapes written for single-choice requests may return an
        # integer.  Normalize it without weakening validation for real tapes.
        if indexes is None:indexes=[]
        elif isinstance(indexes,int):indexes=[indexes]
        indexes=list(indexes)
        if len(indexes)!=len(set(indexes)) or any(not 0<=index<len(opts) for index in indexes):
            raise ValueError(f'{did} returned invalid multi-select indexes')
        if not set(required_indexes).issubset(indexes):
            raise ValueError(f'{did} omitted a required option')
        if not indexes and not allow_pass:raise ValueError(f'{did} cannot be empty')
        from .decision_selection import validate_count
        validate_count(request,indexes)
        memory=list(request.get('pilot_memory') or [])
        self.record_multi_decision(
            did,kind,p.name,prompt,opts,indexes,rationale,[row['note_id'] for row in memory],
            request.get('pass_on_controls',[]),request.get('rationale_policy'))
        return [opts[index]['obj'] for index in indexes]

    # ---------- opening / resource sequencing ----------
    def mulligan(self,p):
        mull=0
        while mull<4:
            hand=[p.library.pop() for _ in range(7)]
            if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:p.hand=hand
            choice=self._request_decision('mulligan',p,
                f'Opening hand (mulligans taken={mull}): '+', '.join(c.d.name for c in hand)+'. Keep or mulligan?',
                [('keep',hand),('mulligan',hand)],lambda x:x[0],
                opening_gameplan_context=(mull==0))
            if choice[0]=='keep' or mull==3:
                paid=max(0,mull-1)
                if paid:
                    # London bottom itself is a strategic choice.
                    for _ in range(paid):
                        c=self._request_decision('london_bottom',p,'Choose a card to put on bottom.',hand,lambda c:f'{c.d.name} [{c.d.mana_cost}]')
                        hand.remove(c);p.library.insert(0,c)
                p.hand=hand
                for c in p.hand:
                    if p.name=='Reaminatour':self.mark_appearance(c.d.name,drawn=True)
                    self.note_timing_affordance(p,c)
                if self.planning_contract>=3:self.planning_boundary(p,'opening_hand_settled')
                self.log('mulligan_keep',p.name,None,f'Kept {len(p.hand)} after {mull} mulligan(s): '+', '.join(c.d.name for c in p.hand),mulligans=mull,hand_size=len(p.hand))
                return
            p.library.extend(hand);self.rng.shuffle(p.library);mull+=1
            if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:p.hand=[]

    def request_land_play(self,p,allow_pass=False):
        lands=[c for c in p.hand if c.d.is_land or '// Land' in c.d.type_line]
        if not lands:return None
        # Usually playing a land is automatic, but which land is often strategic.
        prompt='Choose the land to play this land drop.' if not allow_pass else 'Choose a land to play now, or hold the available land play and continue sequencing spells.'
        return self._request_decision('land_play',p,prompt,lands,
                         lambda c:(f'{c.d.name} | play the land face' if '// Land' in c.d.type_line and not c.d.is_land else f'{c.d.name} | {c.d.type_line}'),allow_pass=allow_pass)

    def extra_land_from_hand(self,p,reason):
        lands=[c for c in p.hand if c.d.is_land]
        if not lands:return
        choice=self._request_decision('effect_land',p,f'{reason}: put a land card from hand onto the battlefield, or decline.',lands,
                         lambda c:f'{c.d.name} | {c.d.type_line}',allow_pass=True)
        if not choice:return
        old=p.land_plays_used;p.land_plays_used=max(0,p.land_plays_used-1)
        self.play_land(p,choice);p.land_plays_used=old
        self.log('extra_land',p.name,choice.d.name,reason)

    def vesuva_copy_choice(self,p,c):
        lands=[(owner,q) for owner in self.players.values() for q in owner.battlefield if sim.is_land_permanent(q)]
        if not lands:return None
        chosen=self._request_decision('vesuva_copy',p,'Vesuva: choose a land on the battlefield to copy, or have Vesuva enter without copying.',lands,
            lambda row:f'{row[0].name}: {row[1].name}'+(f' (copying {row[1].copy_of})' if row[1].copy_of else ''),allow_pass=True)
        if not chosen:return None
        _,target=chosen
        return target.copy_of or target.name

    def ghostly_dancers_etb(self,p,q):
        options=[]
        room=self.perm(p,'Funeral Room // Awakening Hall')
        if room and not room.metadata.get('awakening_unlocked'):
            options.append(('unlock',room))
        options.extend(('return',card) for card in p.graveyard if card.d.is_enchantment)
        if not options:return
        chosen=self._request_decision('ghostly_dancers_etb',p,'Ghostly Dancers entered: choose an enchantment card to return or a locked Room door to unlock.',options,
            lambda row:('unlock Awakening Hall' if row[0]=='unlock' else f'return {row[1].d.name} to hand'))
        kind,target=chosen
        def resolve_dancers():
            if kind=='unlock':
                if target in p.battlefield:self.unlock_awakening_hall(p,target,'Ghostly Dancers')
            elif target in p.graveyard:
                p.graveyard.remove(target);p.hand.append(target);self.log('return_to_hand',p.name,target.d.name,'Ghostly Dancers ETB')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,
            'label':('unlock Awakening Hall' if kind=='unlock' else f'return target {target.d.name}'),
            'resolve':resolve_dancers}])

    def fallen_ideal_etb(self,p,q):
        choices=[(owner,target) for owner in self.players.values() for target in owner.battlefield if self.is_creature_perm(target)]
        chosen=self._request_decision('fallen_ideal_target',p,'Fallen Ideal: choose target creature to enchant.',choices,
            lambda row:f'{row[0].name}: {row[1].name} {self.effective_power(row[1])}/{self.effective_toughness(row[1])}')
        owner,target=chosen;q.attached_to=target.uid
        if 'flying' not in target.keywords:target.metadata['fallen_granted_flying']=True;target.keywords.add('flying')
        self.log('attach',p.name,q.name,f'Fallen Ideal enchants {target.name}',target_uid=target.uid,target_controller=owner.name)

    def bounce_land_return(self,p,bounce_land):
        lands=[q for q in p.battlefield if sim.is_land_permanent(q)]
        return self._request_decision('bounce_land_return',p,f'{bounce_land.name}: return a land you control to its owner’s hand.',lands,lambda q:q.name)

    def fetch_land_choice(self,p,q,candidates):
        return self._request_decision('fetch_land',p,f'{q.name}: choose a legally fetchable land.',candidates,lambda c:f'{c.d.name} | {c.d.type_line}')

    def shock_untapped_choice(self,p,c):
        return self._request_decision('shock_land',p,f'Pay 2 life for {c.d.name} to enter untapped?',[True,False],lambda value:'pay 2 life; untapped' if value else 'enter tapped')

    def normal_shock_untapped_choice(self,p,c):
        return self._request_decision('shock_land',p,f'As {c.d.name} enters, pay 2 life for it to enter untapped?',[True,False],lambda value:'pay 2 life; untapped' if value else 'enter tapped')

    def crack_fetch(self,p,q):
        """Fetchlands pay their tap/life/sacrifice costs, then use the stack."""
        if q not in p.battlefield or q.name not in sim.FETCHES or q.tapped or p.life<=1:return False
        def pay_cost():
            q.tapped=True;self.lose_life(p,1,'fetch land activation cost')
            self.leave_battlefield(p,q,'graveyard','fetch land activation sacrifice cost');return True
        paid,cost_triggers=self.pay_legacy_activation_cost(pay_cost)
        if not paid:return False
        def resolve_fetch():
            candidates=self.legal_fetch_cards(p,q.name)
            if candidates:
                card=self.fetch_land_choice(p,q,candidates);p.library.remove(card)
                tapped=self.land_enters_tapped_for_fetch(p,card)
                if card.d.name in sim.SHOCK_LANDS and self.shock_untapped_choice(p,card):
                    if p.life>2:self.lose_life(p,2,'shock land untapped replacement');tapped=False
                land=self._put_card_bf(p,card,'fetch land');land.tapped=tapped;land.summoning_sick=False
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffled after fetchland ability')
        return self.put_registered_stack_item(p,q,'search for a land with a legal basic land type',resolve_fetch,cost_triggers=cost_triggers)

    def reveal_land_choice(self,p,land,candidates):
        return self._request_decision('reveal_land',p,f'{land.d.name}: reveal a qualifying land from hand so it enters untapped, or decline.',candidates,lambda card:f'reveal {card.d.name}',allow_pass=True)

    # ---------- tutors / copy / recursion ----------
    def request_ream_grave_target(self,p):
        cards=list(p.library)
        c=self._request_decision('graveyard_tutor',p,'Choose the card to tutor from library to graveyard.',cards,
                    lambda c:f'{c.d.name} [{c.d.mana_cost}] | {c.d.type_line}')
        return c.d.name if c else None

    def request_ream_tutor(self,p,filter_kind=None,mv=None):
        cards=[c for c in p.library if mv is None or c.d.mv==mv]
        if filter_kind=='aura':cards=[c for c in cards if 'Aura' in c.d.type_line or c.d.name in {'Animate Dead','Dance of the Dead','Necromancy','Fallen Ideal','Changing Loyalty'}]
        if filter_kind=='enchant_art':cards=[c for c in cards if c.d.is_enchantment or c.d.is_artifact]
        c=self._request_decision('tutor',p,f'Choose tutor target (filter={filter_kind}, mv={mv}).',cards,
                    lambda c:f'{c.d.name} [{c.d.mana_cost}] | {c.d.type_line}')
        return c.d.name if c else None

    def request_library_card(self,p):
        c=self._request_decision('tutor',p,'Choose a card from the library.',list(p.library),
                    lambda c:f'{c.d.name} [{c.d.mana_cost}] | {c.d.type_line}')
        return c.d.name if c else None

    def cruelty_read_ahead_choice(self,p,q):
        return self._request_decision(
            'cruelty_read_ahead',p,
            'The Cruelty of Gix — Read ahead: choose its starting chapter.',
            [1,2,3],lambda chapter:f'chapter {chapter}')

    def cruelty_discard_choice(self,p):
        opponent=self._request_decision(
            'cruelty_opponent',p,
            'The Cruelty of Gix I: choose target opponent to reveal their hand.',
            self.opponents(p),lambda player:player.name)
        eligible=[card for card in opponent.hand if card.d.is_creature or card.d.is_planeswalker]
        if not eligible:return opponent,None
        card=self._request_decision(
            'cruelty_discard',p,
            f'{opponent.name} revealed their hand. Choose a creature or planeswalker card for them to discard, or decline.',
            eligible,lambda card:f'{card.d.name} [{card.d.mana_cost}]',allow_pass=True)
        return opponent,card

    def cruelty_reanimation_target(self,p):
        candidates=[]
        for owner in self.players.values():
            candidates.extend((owner,card) for card in owner.graveyard if card.d.is_creature)
        return self._request_decision(
            'cruelty_reanimate',p,
            'The Cruelty of Gix III: choose target creature card in a graveyard.',
            candidates,lambda row:f'{row[0].name}: {row[1].d.name} [{row[1].d.mana_cost}]')

    def request_body_double_copy(self,p):
        targets=[]
        for pp in self.players.values():
            for c in pp.graveyard:
                if c.d.is_creature and c.d.name!='Body Double':targets.append((pp,c))
        z=self._request_decision('body_double_copy',p,'Body Double: choose a creature card in a graveyard to copy, or decline.',targets,
                    lambda z:f'{z[1].d.name} in {z[0].name} graveyard',allow_pass=True)
        return z[1].d.name if z else None

    def _put_card_bf(self,p,c,reason,copy_of=None,x_value=0):
        if c.d.name=='Body Double' and copy_of is None:
            copy_of=self.request_body_double_copy(p)
        if c.d.name=='Vesuva' and copy_of is None:
            copy_of=self.vesuva_copy_choice(p,c)
        copy_land=False
        if c.d.name=='Copy Land' and copy_of is None:
            lands=[(owner,q) for owner,q in self.all_permanents() if sim.is_land_permanent(q)]
            choice=self._request_decision('copy_land_choice',p,'Copy Land: choose a land on the battlefield to copy, or enter without copying.',lands,
                lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if lands else None
            if choice:copy_of=choice[1].copy_of or choice[1].name;copy_land=True
        permanent=super()._put_card_bf(p,c,reason,copy_of=copy_of,x_value=x_value)
        # Echo belongs to the battlefield object, not the physical card.  A
        # blink/reanimation creates a fresh object and therefore starts a new
        # echo obligation; an old trigger must not affect that new object.
        if (permanent.copy_of or permanent.name)=='Karmic Guide':
            permanent.metadata['echo_pending']=True
        if c.d.name=='Copy Land' and copy_of:
            permanent.metadata['additional_enchantment']=True
        if c.d.is_land or (copy_of and sim.CARDDEF.get(copy_of) and sim.CARDDEF[copy_of].is_land):
            permanent.summoning_sick=False
            self.on_landfall(p,permanent);self.on_land_etb(p,permanent)
        return permanent

    def after_permanent_entry_adjustments(self,p,q):
        """Apply entry replacements that need a pilot choice in official play."""
        definition=sim.CARDDEF.get(q.name)
        if p.name!='Minsc & Boo' or not self.is_creature_perm(q):return
        rhythm=self.perm(p,'Rhythm of the Wild')
        if rhythm and q.name!='Rhythm of the Wild' and not q.token:
            choice=self._request_decision(
                'riot_choice',p,
                f'Rhythm of the Wild gives {q.name} riot. Choose how it enters.',
                ['counter','haste'],lambda value:'+1/+1 counter' if value=='counter' else 'haste')
            if choice=='counter':self.add_counters(p,q,'+1/+1',1,'Rhythm of the Wild riot')
            else:q.keywords.add('haste');self.log('riot',p.name,q.name,'Rhythm of the Wild chooses haste')
        if self.perm(p,'Grumgully, the Generous') and q.name!='Grumgully, the Generous' and not (definition and 'Human' in definition.type_line):
            self.add_counters(p,q,'+1/+1',1,'Grumgully')

    def put_cards_bf_simultaneously(self,p,cards,reason):
        """Move a known group to the battlefield, then observe one ETB event.

        All objects exist before any listener is evaluated.  Their resulting
        triggers are collected into a single APNAP/orderable stack batch.
        """
        pending=[];self.__dict__.setdefault('_deferred_etb_observation',[]).append(pending)
        permanents=[]
        try:
            for card in cards:
                permanents.append(self._put_card_bf(p,card,reason))
        finally:self._deferred_etb_observation.pop()
        batch={'event':f'{len(permanents)} permanents enter simultaneously ({reason})','triggers':[],'finalizers':[]}
        self.__dict__.setdefault('_simultaneous_etb_frames',[]).append(batch)
        try:
            for controller,permanent,x_value in pending:self.on_etb(controller,permanent,x_value=x_value)
        finally:self._simultaneous_etb_frames.pop()
        self.resolve_simultaneous_triggers(batch['event'],batch['triggers'],starter=self.players[self.turn_order[self.active_idx]])
        for finalizer in batch['finalizers']:finalizer()
        return permanents

    def play_land(self,p,c):
        faces={"Kazuul's Fury // Kazuul's Cliffs":("Kazuul's Cliffs",True),
               'Glasswing Grace // Age-Graced Chapel':('Age-Graced Chapel',True)}
        if c.d.name not in faces:
            result=super().play_land(p,c)
            if result:
                permanent=self.find_card_obj_on_bf(p,c.uid)
                if permanent:self.on_land_etb(p,permanent)
            return result
        if p.land_plays_used>=p.land_play_limit or c not in p.hand:return False
        face,tapped=faces[c.d.name];p.hand.remove(c)
        permanent=sim.Perm(c.uid,c.d.name,p.name,p.name,tapped=tapped,summoning_sick=False,copy_of=face,entered_turn=self.turn_number)
        permanent.metadata.update({'is_land':True,'land_face':face})
        if self.perm(p,'Spelunking'):permanent.tapped=False
        p.battlefield.append(permanent);p.land_plays_used+=1
        self.mark_appearance(c.d.name,cast=True,realized=True)
        self.log('land_play',p.name,c.d.name,f'Played {face}'+(' tapped' if permanent.tapped else ''),uid=c.uid,face=face)
        self.on_landfall(p,permanent);self.on_land_etb(p,permanent)
        return True

    def on_land_etb(self,p,land):
        name=land.copy_of or land.name
        if name=='Blast Zone' and not land.counters.get('charge'):
            self.add_counters(p,land,'charge',1,'Blast Zone enters')
        triggers=p.dungeon.setdefault('pending_landfall_triggers',{}).pop(land.uid,[])
        def add(controller,source,label,resolver):triggers.append({'controller':controller,'source':source,'label':label,'resolve':resolver})
        if name=='Lush Oasis':
            opponent=self._request_decision('lush_oasis_target',p,'Lush Oasis: choose target opponent.',self.opponents(p),lambda op:f'{op.name} life={op.life}')
            add(p,'Lush Oasis',f'deal 1 damage to {opponent.name}',lambda:self.lose_life(opponent,1,'Lush Oasis'))
        elif name=='Scoured Barrens':
            add(p,'Scoured Barrens','gain 1 life',lambda:self.gain_life(p,1,'Scoured Barrens'))
        elif name=='Glimmerpost':
            add(p,'Glimmerpost','gain 1 life for each Locus on the battlefield',lambda:self.gain_life(p,sum(1 for _,q in self.all_permanents() if sim.land_has_type(q,'Locus',self.players[q.controller])),'Glimmerpost'))
        elif name=='Talon Gates of Madara':
            choices=[(owner,q) for owner,q in self.all_creatures() if owner is p or not self.has_hexproof(q)]
            chosen=self._request_decision('talon_phase_target',p,'Talon Gates: choose up to one target creature to phase out.',choices,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if choices else None
            if chosen:
                owner,target=chosen
                def phase(owner=owner,target=target):
                    if self.target_still_legal(p,owner,target,True):
                        target.metadata['phased_out']=True
                        target.metadata['removed_from_combat_turn']=self.turn_number
                        self.log('phase_out',p.name,'Talon Gates of Madara',f'{target.name} phases out',target_uid=target.uid)
                add(p,'Talon Gates of Madara',f'{target.name} phases out',phase)
        elif name=="Urza's Saga":
            land.counters['lore']=1;land.metadata['saga_chapter']=1
            triggers.extend(self.enchantment_event_triggers(p))
            add(p,"Urza's Saga",'chapter I: gain the colorless mana ability',lambda:setattr(land,'metadata',{**land.metadata,'urza_mana':True}))
        self.resolve_simultaneous_triggers(f'{name} enters the battlefield',triggers,
                                           starter=self.players[self.turn_order[self.active_idx]])

    def on_landfall(self,p,land):
        """Collect every trigger caused by one land entry for one APNAP batch."""
        triggers=[]
        def add(controller,source,label,resolver,targets=None):
            triggers.append({'controller':controller,'source':source,'label':label,'targets':targets or [],'resolve':resolver})
        baloths=self.perm(p,'Rampaging Baloths')
        if baloths:add(p,baloths.name,'create a 4/4 Beast token',lambda:self.token(p,'Beast',4,4,{'trample'}))
        scute=self.perm(p,'Scute Swarm')
        if scute:
            def resolve_scute():
                lands=sum(1 for permanent in p.battlefield if sim.is_land_permanent(permanent))
                if lands>=6:
                    for swarm in [permanent for permanent in list(p.battlefield) if permanent.name=='Scute Swarm']:
                        self.create_copiable_token(p,swarm)
                else:self.token(p,'Insect',1,1)
            add(p,scute.name,'create an Insect or copy each Scute Swarm',resolve_scute)
        avenger=self.perm(p,'Avenger of Zendikar')
        if avenger:
            def resolve_avenger():
                for plant in [permanent for permanent in p.battlefield if permanent.name=='Plant']:
                    self.add_counters(p,plant,'+1/+1',1,avenger.name)
            add(p,avenger.name,'put a +1/+1 counter on each Plant',resolve_avenger)
        tatyova=self.perm(p,'Tatyova, Benthic Druid')
        if tatyova:add(p,tatyova.name,'gain 1 life and draw a card',lambda:(self.gain_life(p,1,tatyova.name),self.draw(p,1,tatyova.name)))
        bill=self.perm(p,'Bristly Bill, Spine Sower')
        if bill:
            choices=[permanent for permanent in p.battlefield if self.is_creature_perm(permanent)]
            target=self._request_decision('bristly_bill_target',p,'Bristly Bill landfall: choose target creature.',choices,lambda permanent:permanent.name) if choices else None
            if target:add(p,bill.name,f'put a +1/+1 counter on {target.name}',lambda target=target:self.add_counters(p,target,'+1/+1',1,bill.name) if target in p.battlefield else None,[target])
        sage=self.perm(p,'Evolution Sage')
        if sage:
            def resolve_proliferate():
                eligible=[(owner,permanent) for owner,permanent in self.all_permanents() if any(count>0 for count in permanent.counters.values())]
                # The cutoff is bound explicitly to the game. Finish any old
                # resolution in its original shape, even across the cutoff.
                batched=(self.proliferate_batch_after is not None and
                         self.decision_counter>=self.proliferate_batch_after)
                if batched:
                    eligible=[(owner,permanent) for owner,permanent in eligible
                              if not owner.eliminated and not permanent.metadata.get("phased_out")]
                    eligible.extend((owner,None) for owner in self.players.values()
                                    if not owner.eliminated and owner.energy>0)
                    def label(row):
                        owner,permanent=row
                        if permanent is None:return f'{owner.name} — player (energy: {owner.energy})'
                        counters=', '.join(f'{kind}: {count}' for kind,count in permanent.counters.items() if count>0)
                        return f'{owner.name} — {permanent.name} [{permanent.uid}] ({counters})'
                    chosen=self._request_multi_decision(
                        'proliferate_selection',p,
                        'Evolution Sage: choose any number of permanents and/or players to proliferate. '
                        'Each chosen recipient gets one more of every counter kind it already has; an empty selection is legal.',
                        eligible,label,allow_pass=True,scheduler_passable=False)
                else:
                    chosen=[]
                    for owner,permanent in eligible:
                        include=self._request_decision('proliferate_choice',p,f'Evolution Sage: proliferate {owner.name} — {permanent.name}?',[True,False],lambda value:'proliferate' if value else 'do not proliferate')
                        if include:chosen.append((owner,permanent))
                for owner,permanent in chosen:
                    if permanent is None:
                        owner.energy+=1
                        self.log("energy",owner.name,"Evolution Sage","Proliferated energy",energy=owner.energy)
                        continue
                    for kind,count in list(permanent.counters.items()):
                        if count>0:self.add_counters(p,permanent,kind,1,'Evolution Sage proliferate')
            add(p,sage.name,'proliferate',resolve_proliferate)
        elenda=self.players.get('Elenda')
        bonds=self.perm(elenda,'Polluted Bonds') if elenda and not elenda.eliminated and p is not elenda else None
        if bonds:add(elenda,bonds.name,f'{p.name} loses 2 life and Elenda gains 2 life',lambda:(self.lose_life(p,2,bonds.name),self.gain_life(elenda,2,bonds.name)))
        p.dungeon.setdefault('pending_landfall_triggers',{})[land.uid]=triggers

    def on_etb(self,p,q,x_value=0):
        effective_name=q.copy_of or q.name
        deferred=self.__dict__.get('_deferred_etb_observation',[])
        if deferred:
            deferred[-1].append((p,q,x_value));return
        actual=next((permanent for permanent in p.battlefield if permanent.uid==q.uid),q)
        if actual is not q and actual.name=='Copy Land':return
        frame={'uid':q.uid,'triggers':[]}
        self.__dict__.setdefault('_etb_trigger_frames',[]).append(frame)
        # "Enters with" counters are replacement effects and must exist before
        # the base ETB routine performs its first state-based-action check.
        if effective_name=='Nissa, Steward of Elements':q.counters['loyalty']=x_value
        elif effective_name=='Mikaeus, the Lunarch':self.add_counters(p,q,'+1/+1',x_value,'Mikaeus enters')
        elif effective_name=='Invasion of Theros' and not q.metadata.get('transformed_invasion'):
            q.counters['defense']=4
            protector=self._request_decision(
                'battle_protector',p,
                'Invasion of Theros enters: choose an opponent to protect this Siege.',
                self.opponents(p),lambda opponent:f'{opponent.name} protects Invasion of Theros')
            q.metadata['battle_protector']=protector.name
            self.log('battle_protector',p.name,effective_name,
                     f'{protector.name} protects Invasion of Theros',target=protector.name,uid=q.uid)
        super().on_etb(p,q,x_value=x_value)
        modes=p.dungeon.get('resolving_cast_modes',{}).get(q.uid,{})
        if effective_name=="Innkeeper's Talent":q.metadata.setdefault('level',1)
        elif effective_name=='Lotus Blossom':q.counters.setdefault('petal',0)
        elif effective_name=='Sorin of House Markov':q.metadata.setdefault('transformed_sorin',False)
        elif effective_name in {'Glasswing Grace // Age-Graced Chapel','Parasitic Impetus'}:
            chosen=self._announced_aura_target(p,q)
            if chosen:
                owner,target=chosen
                if self._aura_target_legal(p,q,owner,target):
                    q.attached_to=target.uid
                    if effective_name=='Parasitic Impetus':target.metadata['goaded_by']=p.name
                    self.log('attach',p.name,effective_name,f'{effective_name} enchants {target.name}',target_uid=target.uid)
        if effective_name=='Nullpriest of Oblivion' and modes.get('kicked'):
            choices=[card for card in p.graveyard if card.d.is_creature]
            if choices:
                target=self._request_decision('nullpriest_target',p,'Nullpriest kicked ETB: choose target creature card in your graveyard.',choices,lambda card:f'{card.d.name} {card.d.mana_cost}')
                def resolve_nullpriest():
                    if target in p.graveyard:p.graveyard.remove(target);self._put_card_bf(p,target,'Nullpriest kicked ETB')
                self._dispatch_etb_triggers(p,q,[{'controller':p,'source':effective_name,'label':f'return target {target.d.name}','resolve':resolve_nullpriest}])
        if modes.get('evoke') and effective_name in {'Reveillark','Vesperlark'}:
            self._dispatch_etb_triggers(p,q,[{'controller':p,'source':effective_name,'label':'sacrifice it for evoke','resolve':lambda:self.leave_battlefield(p,q,'graveyard','evoke sacrifice') if q in p.battlefield else None}])
        self._etb_trigger_frames.pop()
        def final_check():
            if q.metadata.pop('saga_enter_final_check',False) and q in p.battlefield and q.counters.get('lore',0)>=3:
                if effective_name in {'The Cruelty of Gix','Elspeth Conquers Death',"Urza's Saga"}:
                    self.leave_battlefield(p,q,'graveyard','Saga final chapter left the stack')
                elif effective_name=='The Restoration of Eiganjo' and not q.metadata.get('transformed_restoration'):
                    self.leave_battlefield(p,q,'graveyard','Restoration final chapter left the stack without transforming')
        batches=self.__dict__.get('_simultaneous_etb_frames',[])
        if batches:
            batches[-1]['triggers'].extend(frame['triggers']);batches[-1]['finalizers'].append(final_check)
        else:
            self.resolve_simultaneous_triggers(f'{effective_name} enters the battlefield',frame['triggers'],starter=self.players[self.turn_order[self.active_idx]])
            final_check()

    def _dispatch_etb_triggers(self,p,q,triggers):
        frames=self.__dict__.get('_etb_trigger_frames',[])
        if frames and frames[-1]['uid']==q.uid:
            frames[-1]['triggers'].extend(triggers);return
        self.resolve_simultaneous_triggers(f'{q.name} enters the battlefield',triggers,starter=self.players[self.turn_order[self.active_idx]])

    def trigger_planeswalker_etb(self,p,q):
        liliana=self.perm(p,'Liliana the Faultless')
        if liliana and q.name!='Liliana the Faultless':
            self._dispatch_etb_triggers(p,q,[{'controller':p,'source':liliana.name,
                'label':'gain 1 life','resolve':lambda:self.gain_life(p,1,'Liliana planeswalker ETB trigger')}])

    def trigger_creature_etb(self,p,q):
        triggers=[]
        def add(source,label,resolver):triggers.append({'controller':p,'source':source,'label':label,'resolve':resolver})
        liliana=self.perm(p,'Liliana the Faultless')
        if liliana and (q.copy_of or q.name)!='Liliana the Faultless':add(liliana.name,'gain 1 life',lambda:self.gain_life(p,1,'Liliana creature ETB'))
        if (q.copy_of or q.name)=='Inspiring Overseer':add(q.name,'gain 1 life and draw a card',lambda:(self.gain_life(p,1,q.name),self.draw(p,1,q.name)))
        if (q.copy_of or q.name)=='Oasis Gardener':add(q.name,'gain 2 life',lambda:self.gain_life(p,2,q.name))
        champion=self.perm(p,'Champion of Lambholt')
        if champion and q.uid!=champion.uid:add(champion.name,'put a +1/+1 counter on it',lambda:self.add_counters(p,champion,'+1/+1',1,champion.name))
        uprising=self.perm(p,"Garruk's Uprising")
        if uprising and self.power(q)>=4:add(uprising.name,'draw a card',lambda:self.draw(p,1,"Garruk's Uprising creature ETB"))
        self._dispatch_etb_triggers(p,q,triggers)

    def mulldrifter_etb(self,p,q):
        modes=p.dungeon.get('resolving_cast_modes',{}).get(q.uid,{})
        triggers=[{'controller':p,'source':'Mulldrifter','label':'draw two cards','resolve':lambda:self.draw(p,2,'Mulldrifter ETB')}]
        if modes.get('evoke'):
            triggers.append({'controller':p,'source':'Mulldrifter','label':'sacrifice it for evoke','resolve':lambda:self.leave_battlefield(p,q,'graveyard','evoke sacrifice') if q in p.battlefield else None})
        self._dispatch_etb_triggers(p,q,triggers)

    def eternal_witness_etb(self,p,q):
        choices=[card for card in p.graveyard if card.uid!=q.uid]
        if not choices:return
        target=self._request_decision('eternal_witness_target',p,'Eternal Witness ETB: choose target card in your graveyard.',choices,lambda card:f'{card.d.name} {card.d.mana_cost}')
        def resolve_witness():
            if target in p.graveyard:p.graveyard.remove(target);p.hand.append(target);self.log('return_to_hand',p.name,target.d.name,'Eternal Witness ETB')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'return {target.d.name}','resolve':resolve_witness}])

    def hydroid_krasis_etb(self,p,q,x_value):
        # Entering with counters is a replacement effect, not an ETB trigger.
        self.add_counters(p,q,'+1/+1',x_value,'Hydroid Krasis enters')

    def solemn_simulacrum_etb(self,p,q):
        def resolve_solemn():
            basics=[card for card in p.library if card.d.type_line.startswith('Basic Land')]
            card=self._request_decision('solemn_basic',p,'Solemn Simulacrum: search for a basic land card.',basics,lambda card:card.d.name,allow_pass=True) if basics else None
            if card:
                p.library.remove(card);land=self._put_card_bf(p,card,'Solemn Simulacrum ETB');land.tapped=True;land.summoning_sick=False
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Solemn Simulacrum')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'search for a basic land tapped','resolve':resolve_solemn}])

    def baleful_strix_etb(self,p,q):
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'draw a card','resolve':lambda:self.draw(p,1,q.name)}])

    def spirited_companion_etb(self,p,q):
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'draw a card','resolve':lambda:self.draw(p,1,q.name)}])

    def omen_of_the_sea_etb(self,p,q):
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'scry 2, then draw a card','resolve':lambda:(self.scry(p,2,q.name),self.draw(p,1,q.name))}])

    def chthonian_nightmare_etb(self,p,q):
        def resolve_energy():p.__setattr__('energy',p.energy+3);self.log('energy',p.name,q.name,'Got 3 energy',energy=p.energy)
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'get three energy','resolve':resolve_energy}])

    def gravebreaker_lamia_etb(self,p,q):
        def resolve_lamia():
            card=self._request_decision('graveyard_tutor',p,'Gravebreaker Lamia: choose a card for your graveyard.',list(p.library),lambda card:f'{card.d.name} {card.d.mana_cost}') if p.library else None
            if card:p.library.remove(card);p.graveyard.append(card);self.rng.shuffle(p.library);self.log('tutor',p.name,card.d.name,'Gravebreaker Lamia to graveyard',destination='graveyard',visibility='public')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'search for a card and put it into your graveyard','resolve':resolve_lamia}])

    def invasion_of_theros_etb(self,p,q):
        def resolve_invasion():
            auras=[card for card in p.library if 'Aura' in card.d.type_line or card.d.name in {'Animate Dead','Dance of the Dead','Necromancy'}]
            card=self._request_decision('tutor',p,'Invasion of Theros: choose an Aura card.',auras,lambda card:f'{card.d.name} {card.d.mana_cost}',allow_pass=True) if auras else None
            if card:p.library.remove(card);p.hand.append(card);self.log('tutor',p.name,card.d.name,'Invasion of Theros to hand',destination='hand',visibility='public')
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Invasion of Theros')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'search for an Aura card','resolve':resolve_invasion}])

    def _targeted_destroy_etb(self,p,q,allow_land=False):
        legal=[]
        for owner,target in self.all_permanents():
            if target.uid==q.uid:continue
            definition=sim.CARDDEF.get(target.copy_of or target.name)
            if not definition:continue
            if not (definition.is_artifact or definition.is_enchantment or (allow_land and sim.is_land_permanent(target))):continue
            if owner is not p and self.has_hexproof(target):continue
            legal.append((owner,target))
        chosen=self._request_decision('removal_target',p,f'{q.name}: choose up to one target.',legal,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if legal else None
        if not chosen:return
        owner,target=chosen
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'destroy target {target.name}','targets':[target],
            'resolve':lambda:self.destroy(owner,target,q.name+' ETB') if self.target_still_legal(p,owner,target) else None}])

    def loran_etb(self,p,q):self._targeted_destroy_etb(p,q,False)
    def acidic_slime_etb(self,p,q):self._targeted_destroy_etb(p,q,True)

    def spelunking_etb(self,p,q):
        def resolve_spelunking():
            self.draw(p,1,'Spelunking ETB')
            lands=[card for card in p.hand if card.d.is_land]
            card=self._request_decision('effect_land',p,'Spelunking: put a land card from your hand onto the battlefield?',lands,lambda card:f'{card.d.name} | {card.d.type_line}',allow_pass=True) if lands else None
            if card:
                p.hand.remove(card);land=self._put_card_bf(p,card,'Spelunking ETB');land.summoning_sick=False
                if 'Cave' in card.d.type_line:self.gain_life(p,4,'Spelunking Cave')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'draw, then you may put a land from hand onto the battlefield','resolve':resolve_spelunking}])

    def ulvenwald_hydra_etb(self,p,q):
        def resolve_hydra():
            lands=[card for card in p.library if card.d.is_land]
            card=self._request_decision('ulvenwald_land',p,'Ulvenwald Hydra: choose a land card.',lands,lambda card:f'{card.d.name} | {card.d.type_line}',allow_pass=True) if lands else None
            if card:p.library.remove(card);land=self._put_card_bf(p,card,'Ulvenwald Hydra ETB');land.tapped=True;land.summoning_sick=False
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Ulvenwald Hydra')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'search for a land card tapped','resolve':resolve_hydra}])

    def terastodon_etb(self,p,q):
        remaining=[(owner,target) for owner,target in self.all_permanents() if target.uid!=q.uid and
                   not self.is_creature_perm(target) and (owner is p or not self.has_hexproof(target))]
        if self.selection_batch_enabled():
            announced=self._request_selection('terastodon_targets',p,'Terastodon: choose up to three target noncreature permanents.',remaining,
                lambda row:f'{row[0].name}: {row[1].name} [{row[1].uid}]',maximum=3)
        else:
            announced=[]
            for slot in range(3):
                if not remaining:break
                chosen=self._request_decision('terastodon_target',p,f'Terastodon: choose target noncreature permanent {slot+1}, or stop.',remaining,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True)
                if not chosen:break
                announced.append(chosen);remaining.remove(chosen)
        def resolve_terastodon():
            for owner,target in announced:
                if self.target_still_legal(p,owner,target) and self.destroy(owner,target,'Terastodon ETB'):self.token(owner,'Elephant',3,3)
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'destroy '+(', '.join(target.name for _,target in announced) if announced else 'no targets'),
            'targets':[target for _,target in announced],'resolve':resolve_terastodon}])

    def avenger_of_zendikar_etb(self,p,q):
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'create a Plant for each land you control',
            'resolve':lambda:[self.token(p,'Plant',0,1) for _ in range(sum(1 for land in p.battlefield if sim.is_land_permanent(land)))]}])

    def elvish_rejuvenator_etb(self,p,q):
        def resolve_rejuvenator():
            seen=list(p.library[-min(5,len(p.library)):]);lands=[card for card in seen if card.d.is_land]
            card=self._request_decision('rejuvenator_land',p,'Elvish Rejuvenator reveals '+(', '.join(card.d.name for card in reversed(seen)) or 'no cards')+'. Choose a land.',lands,lambda card:card.d.name,allow_pass=True) if lands else None
            for revealed in seen:p.library.remove(revealed)
            rest=[revealed for revealed in seen if revealed is not card];self.rng.shuffle(rest);p.library=rest+p.library
            if card:land=self._put_card_bf(p,card,'Elvish Rejuvenator');land.tapped=True;land.summoning_sick=False
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'look at five cards and put a land onto the battlefield tapped','resolve':resolve_rejuvenator}])

    def satyr_wayfinder_etb(self,p,q):
        def resolve_wayfinder():
            seen=[p.library.pop() for _ in range(min(4,len(p.library)))];lands=[card for card in seen if card.d.is_land]
            card=self._request_decision('wayfinder_land',p,'Satyr Wayfinder reveals '+(', '.join(card.d.name for card in seen) or 'no cards')+'. Choose a land for your hand.',lands,lambda card:card.d.name,allow_pass=True) if lands else None
            if card:seen.remove(card);p.hand.append(card);self.log('reveal_to_hand',p.name,card.d.name,'Satyr Wayfinder')
            for other in seen:p.graveyard.append(other);self.log('mill',p.name,other.d.name,'Satyr Wayfinder')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'reveal four, take a land, mill the rest','resolve':resolve_wayfinder}])

    def uro_etb(self,p,q):
        escaped=(p.dungeon.pop('escaping_uro_uid',None)==q.uid) or q.metadata.get('escaped')
        if escaped:q.metadata['escaped']=True
        triggers=[]
        triggers.append({'controller':p,'source':q.copy_of or q.name,'label':'sacrifice Uro unless it escaped',
                         'resolve':lambda:self.leave_battlefield(p,q,'graveyard','Uro sacrifice trigger') if not escaped and q in p.battlefield else None})
        def resolve_uro_value():self.gain_life(p,3,'Uro');self.draw(p,1,'Uro');self.extra_land_from_hand(p,'Uro')
        triggers.append({'controller':p,'source':q.name,'label':'gain 3 life, draw, then you may put a land from hand onto the battlefield','resolve':resolve_uro_value})
        self._dispatch_etb_triggers(p,q,triggers)

    def jyoti_etb(self,p,q):
        count=p.dungeon.get('commander_casts',0)
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'create {count} Forest Dryad land creature token(s)',
            'resolve':lambda:[self.token(p,'Forest Dryad',1,1) for _ in range(count)]}])

    def rune_scarred_demon_etb(self,p,q):
        def resolve_demon():
            card=self._request_decision('tutor',p,'Rune-Scarred Demon: choose a card.',list(p.library),lambda card:f'{card.d.name} {card.d.mana_cost}') if p.library else None
            if card:p.library.remove(card);p.hand.append(card);self.rng.shuffle(p.library);self.log('tutor',p.name,card.d.name,'Rune-Scarred Demon to hand')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'search for a card','resolve':resolve_demon}])

    def noxious_gearhulk_etb(self,p,q):
        legal=[(owner,target) for owner,target in self.all_creatures() if target.uid!=q.uid and (owner is p or not self.has_hexproof(target))]
        chosen=self._request_decision('noxious_target',p,'Noxious Gearhulk: choose another target creature.',legal,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if legal else None
        if not chosen:return
        owner,target=chosen
        def resolve_gearhulk():
            if not self.target_still_legal(p,owner,target,True):return
            amount=self.toughness(target)
            if self.destroy(owner,target,'Noxious Gearhulk'):self.gain_life(p,amount,'Noxious Gearhulk')
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'destroy target {target.name}; gain life equal to its toughness','targets':[target],'resolve':resolve_gearhulk}])

    def karmic_guide_etb(self,p,q):
        legal=[card for card in p.graveyard if card.d.is_creature and card.uid!=q.uid]
        target=self._request_decision('karmic_guide_target',p,'Karmic Guide: choose target creature card in your graveyard.',legal,lambda card:f'{card.d.name} {card.d.mana_cost}',allow_pass=True) if legal else None
        if target:self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'return target {target.d.name}','resolve':lambda:self.put_grave_creature_bf(p,target,'Karmic Guide') if target in p.graveyard else None}])

    def sun_titan_etb(self,p,q):
        legal=[card for card in p.graveyard if card.d.is_permanent and card.d.mv<=3]
        target=self._request_decision('sun_titan_target',p,'Sun Titan ETB: choose target permanent card with mana value 3 or less.',legal,lambda card:card.d.name,allow_pass=True) if legal else None
        if target:self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'return target {target.d.name}','resolve':lambda:self._put_card_bf(p,p.graveyard.pop(p.graveyard.index(target)),'Sun Titan ETB') if target in p.graveyard else None}])

    def garruks_uprising_etb(self,p,q):
        if any(self.is_creature_perm(creature) and self.power(creature)>=4 for creature in p.battlefield):
            self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'draw a card','resolve':lambda:self.draw(p,1,q.name)}])

    def generic_draw_etb(self,p,q):
        # All actual ETB-draw cards in this pod have an exact named handler.
        # The former substring fallback incorrectly drew for Sigarda's Splendor.
        return

    def minsc_enters(self,p,q):
        loyalty=sim.catalog_starting_loyalty(q.name)
        if loyalty is not None:q.counters.setdefault('loyalty',loyalty)
        self._dispatch_etb_triggers(p,q,[{
            'controller':p,'source':q.name,'label':'you may create Boo',
            'resolve':lambda:self.offer_create_boo(p),
        }])

    def commander_grave_exile_choice(self,owner,q,dst,reason):
        """Give the commander's owner the post-move state-based-action choice."""
        deferred=self.__dict__.get('_deferred_commander_sba_choices')
        if deferred is not None:
            deferred.append((owner,q,dst,reason))
            return False
        return self._request_decision(
            'commander_grave_exile_zone',owner,
            f'{q.name} was put into {dst}. Put it in the command zone as a state-based action?',
            [False,True],
            lambda value:(f'leave {q.name} in {dst}' if not value else f'put {q.name} in command zone'))

    def linked_exile_etb(self,p,q):
        """Announce linked-exile ETB targets before the trigger priority round."""
        choices=[]
        for owner,target in self.all_permanents():
            if target.uid==q.uid:continue
            # Tokens and copy-derived permanents need not have a CardDef entry.
            # Target legality follows their current characteristics instead.
            view=self.continuous_view(target)
            if 'Land' in view.types:continue
            if q.name=='Prayer of Binding' and owner is p:continue
            if q.name=='Touch the Spirit Realm' and not ({'Artifact','Creature'} & view.types):continue
            if owner is not p and self.has_hexproof(target):continue
            choices.append((owner,target))
        chosen=self._request_decision('linked_exile_target',p,f'{q.name}: choose up to one target for its enters-the-battlefield ability.',choices,
            lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if choices else None
        targets=[chosen[1]] if chosen else []
        def resolve_linked():
            if q not in p.battlefield:return
            if chosen:
                owner,target=chosen
                if not self.target_still_legal(p,owner,target):return
                uid=target.uid;self.leave_battlefield(owner,target,'exile',q.name+' linked exile')
                q.metadata.setdefault('linked_exiled_uids',[]).append(uid)
            if q.name=='Prayer of Binding':self.gain_life(p,2,'Prayer of Binding')
        self._dispatch_etb_triggers(p,q,[{
            'controller':p,'source':q.name,
            'label':('exile '+chosen[1].name if chosen else 'exile no target')+(' and gain 2 life' if q.name=='Prayer of Binding' else ''),
            'targets':targets,'resolve':resolve_linked,
        }])

    def grasp_of_fate_etb(self,p,q):
        if self.selection_batch_enabled():
            legal=[(opponent,target) for opponent in self.opponents(p) for target in opponent.battlefield
                   if not sim.is_land_permanent(target) and not self.has_hexproof(target)]
            announced=self._request_selection('grasp_of_fate_targets',p,'Grasp of Fate: choose up to one target nonland permanent per opponent.',legal,
                lambda row:f'{row[0].name}: {row[1].name} [{row[1].uid}]',groups=[owner.name for owner,_ in legal])
        else:
            announced=[]
            for opponent in self.opponents(p):
                legal=[target for target in opponent.battlefield if not sim.is_land_permanent(target) and not self.has_hexproof(target)]
                chosen=self._request_decision('grasp_of_fate_target',p,
                    f'Grasp of Fate: choose up to one target nonland permanent controlled by {opponent.name}.',legal,
                    lambda target:target.name,allow_pass=True) if legal else None
                if chosen:announced.append((opponent,chosen))
        def resolve_grasp():
            if q not in p.battlefield:return
            for owner,target in announced:
                if self.target_still_legal(p,owner,target):
                    uid=target.uid;self.leave_battlefield(owner,target,'exile','Grasp of Fate linked exile')
                    q.metadata.setdefault('linked_exiled_uids',[]).append(uid)
        self._dispatch_etb_triggers(p,q,[{
            'controller':p,'source':q.name,
            'label':'exile '+(', '.join(target.name for _,target in announced) if announced else 'no targets'),
            'targets':[target for _,target in announced],'resolve':resolve_grasp,
        }])

    def request_reanimation_target(self,p,aura):
        cards=[c for c in p.graveyard if c.d.is_creature]
        return self._request_decision('reanimation_target',p,f'{aura.name}: choose creature card to return.',cards,
                         lambda c:f'{c.d.name} [{c.d.mana_cost}]')

    def blink_own_permanent(self,p,target,reason):
        if target.name not in {'Animate Dead','Dance of the Dead'}:
            return super().blink_own_permanent(p,target,reason)
        if target not in p.battlefield:return None
        self.leave_battlefield(p,target,'exile',reason+' exile')
        if target.token:return None
        owner=self.players[target.owner]
        card=next((c for c in owner.exile if c.uid==target.uid),None)
        if card is None:return None
        # CR 303.4f-g: these Auras must enchant a creature card as they
        # return. Their old creature's sacrifice trigger cannot resolve in
        # the middle of Felidar's blink to supply a graveyard card in time.
        if not any(c.d.is_creature for player in self.players.values() for c in player.graveyard):
            self.log('aura_return_failed',owner.name,card.d.name,
                     'Remains in exile: no creature card in a graveyard to enchant',uid=card.uid)
            return None
        owner.exile.remove(card)
        return self._put_card_bf(owner,card,reason+' return')

    def reanimate_aura_etb(self,p,aura):
        state=p.dungeon.get('announced_spells',{}).get(aura.uid,{})
        announced=state.get('grave_target')
        if announced:
            owner,card=announced
        else:
            choices=[(grave_owner,card) for grave_owner in self.players.values() for card in grave_owner.graveyard if card.d.is_creature]
            chosen=self._request_decision('necromancy_target' if aura.name=='Necromancy' else 'reanimation_target',p,
                f'{aura.name} ETB: choose target creature card in a graveyard.',choices,lambda row:f'{row[1].d.name} ({row[0].name} graveyard)') if choices else None
            if not chosen:return
            owner,card=chosen
        aura.metadata['enchants_grave_uid']=card.uid
        def resolve_reanimation():self.resolve_reanimation_aura_trigger(p,aura,owner,card)
        self._dispatch_etb_triggers(p,aura,[{
            'controller':p,'source':aura.name,'label':f'return {card.d.name} and attach {aura.name}',
            'resolve':resolve_reanimation,
        }])

    def resolve_reanimation_aura_trigger(self,p,aura,owner,card):
        if aura not in p.battlefield:return
        if not card or card not in owner.graveyard:return
        owner.graveyard.remove(card)
        copy=self.request_body_double_copy(p) if card.d.name=='Body Double' else None
        aura.attached_to=card.uid
        permanent=self._put_card_bf(p,card,f'{aura.name} reanimation',copy_of=copy)
        if aura.name=='Dance of the Dead':permanent.tapped=True
        if permanent.name=='Karmic Guide' and aura.name in {'Animate Dead','Dance of the Dead','Necromancy'}:
            self.log('aura_illegal_attach',p.name,aura.name,f'{permanent.name} has protection from black; {aura.name} cannot remain attached and goes to graveyard')
            aura.attached_to=None
            if aura in p.battlefield:self.leave_battlefield(p,aura,'graveyard','state-based Aura attachment illegal')
            return
        if aura not in p.battlefield or permanent not in p.battlefield:return
        aura.metadata.pop('enchants_grave_uid',None);aura.attached_to=permanent.uid;permanent.metadata['reanimated_by']=aura.uid
        self.log('attach',p.name,aura.name,f'{aura.name} attached to {permanent.name}',target_uid=permanent.uid)

    def celestial_armor_etb(self,p,q):
        targets=[creature for creature in p.battlefield if self.is_creature_perm(creature)]
        if not targets:return
        target=self._request_decision('celestial_armor_target',p,'Celestial Armor ETB: choose target creature you control.',targets,lambda creature:creature.name)
        def resolve_armor():
            if target not in p.battlefield:return
            if q in p.battlefield:self.attach_equipment(p,q,target)
            target.metadata['celestial_hexproof_turn']=self.turn_number;target.metadata['celestial_indestructible_turn']=self.turn_number
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'attach to {target.name}; it gains hexproof and indestructible','targets':[target],'resolve':resolve_armor}])

    def _announced_aura_target(self,p,q):
        state=p.dungeon.get('announced_spells',{}).get(q.uid,{})
        return state.get('target')

    def _aura_target_legal(self,p,aura,owner,target):
        state=p.dungeon.get('announced_spells',{}).get(aura.uid,{})
        if not state.get('entered_without_cast'):
            return self.target_still_legal(p,owner,target,True,aura.name)
        return (target in owner.battlefield and self.is_creature_perm(target) and
                not (self.source_colors(aura) & self.continuous_view(target).rules.get('protection_colors',set())))

    def angelic_destiny_etb(self,p,q):
        chosen=self._announced_aura_target(p,q)
        if chosen:
            owner,target=chosen
            if self._aura_target_legal(p,q,owner,target):q.attached_to=target.uid;target.metadata['angelic_destiny_uid']=q.uid;self.log('attach',p.name,q.name,f'Angelic Destiny enchants {target.name}',target_uid=target.uid)

    def fallen_ideal_etb(self,p,q):
        chosen=self._announced_aura_target(p,q)
        if not chosen:
            targets=[target for target in p.battlefield if self.is_creature_perm(target)]
            if not targets:return
            target=self._request_decision('fallen_ideal_target',p,'Fallen Ideal: choose a creature to enchant.',targets,lambda target:target.name)
            chosen=(p,target)
        owner,target=chosen
        if not self._aura_target_legal(p,q,owner,target):return
        q.attached_to=target.uid
        if 'flying' not in target.keywords:target.metadata['fallen_granted_flying']=True;target.keywords.add('flying')
        self.log('attach',p.name,q.name,f'Fallen Ideal enchants {target.name}',target_uid=target.uid)

    def darksteel_mutation_etb(self,p,q):
        chosen=self._announced_aura_target(p,q)
        if not chosen:return
        owner,target=chosen
        if not self._aura_target_legal(p,q,owner,target):return
        target.metadata['darksteel_original']={'base_power':target.base_power,'base_toughness':target.base_toughness,'keywords':sorted(target.keywords)}
        target.base_power=0;target.base_toughness=1;target.keywords={'indestructible'};target.metadata['mutated']=True;q.attached_to=target.uid
        self.log('aura_disable',p.name,q.name,f'Darksteel Mutation disables {target.name}',target=target.name)

    def changing_loyalty_etb(self,p,q):
        chosen=self._announced_aura_target(p,q)
        if not chosen:
            choices=[(owner,target) for owner,target in self.all_creatures()]
            if not choices:return
            chosen=self._request_decision('changing_loyalty_target',p,'Changing Loyalty: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
        if not chosen:return
        owner,target=chosen
        if self._aura_target_legal(p,q,owner,target):q.attached_to=target.uid;self.log('attach',p.name,q.name,f'Changing Loyalty enchants {target.name}',target_uid=target.uid,target_controller=owner.name)

    def angel_fabricate(self,p,q):
        def resolve_fabricate():
            mode=self._request_decision('fabricate',p,'Angel of Invention — Fabricate 2: choose two +1/+1 counters or two Servo tokens.',
                        ['counters','servos'],lambda value:'put two +1/+1 counters on Angel of Invention' if value=='counters' else 'create two 1/1 Servo tokens')
            if mode=='counters':self.add_counters(p,q,'+1/+1',2,'Angel of Invention fabricate')
            else:self.token(p,'Servo',1,1);self.token(p,'Servo',1,1)
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':'fabricate 2','resolve':resolve_fabricate}])

    # ---------- central target helpers ----------
    def changing_loyalty_target(self,p,choices):
        return self._request_decision(
            'changing_loyalty_target',p,'Changing Loyalty: choose target creature.',choices,
            lambda row:f'{row[0].name}: {row[1].name} {self.effective_power(row[1])}/{self.effective_toughness(row[1])}')

    def strongest_creature(self,p):
        cs=[q for q in p.battlefield if self.is_creature_perm(q)]
        return self._request_decision('own_creature_target',p,'Choose your creature for this effect.',cs,
                         lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')

    def best_enemy_creature(self,p):
        cs=[(op,q) for op in self.opponents(p) for q in op.battlefield if self.is_creature_perm(q) and not self.has_hexproof(q)]
        return self._request_decision('enemy_creature_target',p,'Choose an opposing creature target.',cs,
                         lambda z:f'{z[0].name}: {z[1].name} {self.effective_power(z[1])}/{self.effective_toughness(z[1])}')

    def essence_channeler_death_target(self,p,channeler,targets):
        counters=', '.join(f'{count} {kind}' for kind,count in channeler.counters.items())
        return self._request_decision(
            'essence_channeler_death_target',p,
            f'Essence Channeler died: choose a creature you control to receive its counters ({counters}).',
            targets,lambda creature:f'{creature.name} {self.effective_power(creature)}/{self.effective_toughness(creature)}')

    def best_enemy_permanent_for_removal(self,p,n):
        choices=[]
        for op in self.opponents(p):
            for q in op.battlefield:
                d=sim.CARDDEF.get(q.name)
                legal=True
                if n=='Utter End':legal=not sim.is_land_permanent(q)
                if n in {'Pongify','Murder'}:legal=self.is_creature_perm(q)
                if n=='Breathe Your Last':legal=self.is_creature_perm(q) or self.is_planeswalker_perm(q)
                if n=="Hero's Downfall":legal=self.is_creature_perm(q) or self.is_planeswalker_perm(q)
                if n=='Valorous Stance':legal=self.is_creature_perm(q) and self.toughness(q)>=4
                if q.name=='Elenda, Saint of Dusk' and sim.CARDDEF.get(n) and sim.CARDDEF[n].is_instant:legal=False
                if q.metadata.get('heroic_protected_turn')==self.turn_number or self.has_hexproof(q):legal=False
                if legal:choices.append((op,q))
        return self._request_decision('removal_target',p,f'{n}: choose target.',choices,
                         lambda z:f'{z[0].name}: {z[1].name} ({z[1].counters or "no counters"})',allow_pass=True)

    def use_heroic_intervention(self,p,removal_name,target):
        choices=[True,False]
        if self.decision_surface_revision>=2:choices.append('concede')
        choice=self._request_decision(
            'heroic_intervention',p,
            f'{removal_name} targets {target.name}. Cast Heroic Intervention in response?',
            choices,lambda value:(
                'CONCEDE — leave this game immediately' if value=='concede' else
                ('cast Heroic Intervention' if value else 'do not cast')),
            gameplan_access=True)
        if choice=='concede':
            self.concede_from_priority(p,'targeted-removal response');return False
        return choice

    def destroy_best_noncreature(self,p,reason,allow_land=False):
        choices=[]
        for op in self.opponents(p):
            for q in op.battlefield:
                d=sim.CARDDEF.get(q.name)
                if not d:continue
                if d.is_artifact or d.is_enchantment or (allow_land and d.is_land):choices.append((op,q))
        z=self._request_decision('removal_target',p,f'{reason}: choose noncreature permanent.',choices,
                    lambda z:f'{z[0].name}: {z[1].name}',allow_pass=True)
        if z:self.destroy(z[0],z[1],reason)

    # ---------- counter replacement and counter-event triggers ----------
    def active_ability_perm(self,p,name):
        return next((q for q in p.battlefield if (q.copy_of or q.name)==name
                     and not sim.permanent_mana_inactive(q) and not q.metadata.get('mutated')),None)

    def counter_replacements(self,placing_player,target,kind):
        """Return every replacement effect applicable to one counter-placement event."""
        effects=[]
        controlled=target.controller==placing_player.name
        creature=self.is_creature_perm(target)
        definition=sim.CARDDEF.get(target.copy_of or target.name)
        artifact=bool(definition and definition.is_artifact) or target.metadata.get('artifact')
        if kind=='+1/+1' and controlled and creature:
            if self.perm(placing_player,'Hardened Scales'):effects.append(('Hardened Scales',lambda amount:amount+1))
            if self.perm(placing_player,'The Earth Crystal'):effects.append(('The Earth Crystal',lambda amount:amount*2))
            if self.perm(placing_player,'Branching Evolution'):effects.append(('Branching Evolution',lambda amount:amount*2))
        if kind=='+1/+1' and controlled and (creature or artifact) and self.perm(placing_player,'Ozolith, the Shattered Spire'):
            effects.append(('Ozolith, the Shattered Spire',lambda amount:amount+1))
        if kind=='+1/+1' and controlled and self.perm(placing_player,'Kami of Whispered Hopes'):
            effects.append(('Kami of Whispered Hopes',lambda amount:amount+1))
        if self.active_ability_perm(placing_player,'Vorinclex, Monstrous Raider'):
            effects.append(('your Vorinclex, Monstrous Raider',lambda amount:amount*2))
        talent=self.perm(placing_player,"Innkeeper's Talent")
        if controlled and talent and talent.metadata.get('level',1)>=3:
            effects.append(("Innkeeper's Talent level 3",lambda amount:amount*2))
        for opponent in self.opponents(placing_player):
            if self.active_ability_perm(opponent,'Vorinclex, Monstrous Raider'):
                effects.append((f"{opponent.name}'s Vorinclex, Monstrous Raider",lambda amount:amount//2))
        return effects

    def add_counters(self,p,q,kind,n,reason='',defer_triggers=None):
        if n<=0:return 0
        requested=n;remaining=self.counter_replacements(p,q,kind)
        chooser=self.players.get(q.controller,p)
        applied=[]
        while remaining:
            if len(remaining)==1:effect=remaining[0]
            else:
                effect=self._request_decision(
                    'replacement_order',chooser,
                    f'{requested} {kind} counter(s) would be put on {q.name}. Choose the next replacement effect to apply.',
                    remaining,lambda row:row[0])
            before=n;n=effect[1](n);applied.append(effect[0]);remaining.remove(effect)
            self.log('replacement_effect',chooser.name,effect[0],f'{effect[0]} changes {before} counter(s) to {n}',target_uid=q.uid)
        if n<=0:
            self.log('counters_replaced',p.name,q.name,f'No {kind} counters are put on {q.name}',requested=requested,replacements=applied)
            return 0
        q.counters[kind]=q.counters.get(kind,0)+n;p.counters_placed_this_turn+=n
        self.log('counters',p.name,q.name,f'Put {n} {kind} counter(s) on {q.name} (base request {requested}; {reason})',amount=n,requested=requested,replacements=applied)

        triggers=[]
        all_one=self.perm(p,'All Will Be One')
        if all_one:
            targets=[('player',op,op) for op in self.opponents(p)]
            for opponent in self.opponents(p):
                for permanent in opponent.battlefield:
                    definition=sim.CARDDEF.get(permanent.name)
                    if not self.target_still_legal(p,opponent,permanent,source_name='All Will Be One'):continue
                    if self.is_creature_perm(permanent):targets.append(('creature',opponent,permanent))
                    elif self.is_planeswalker_perm(permanent):targets.append(('planeswalker',opponent,permanent))
            if targets:
                target=self._request_decision('all_will_be_one_target',p,
                    f'All Will Be One: choose a target for {n} damage.',targets,
                    lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player'
                                else f'{row[0].upper()} {row[1].name}: {row[2].name}'))
                triggers.append({'controller':p,'source':'All Will Be One','label':f'deal {n} damage to {target[2].name}',
                                 'targets':([] if target[0]=='player' else [target[2]]),
                                 'resolve':lambda target=target,amount=n:self.resolve_all_will_be_one(p,target,amount)})
        terrasymbiosis=self.perm(p,'Terrasymbiosis')
        if kind=='+1/+1' and q.controller==p.name and self.is_creature_perm(q) and terrasymbiosis and p.dungeon.get('terrasymbiosis_turn')!=self.turn_number:
            def resolve_terrasymbiosis(amount=n):
                draw=self._request_decision('terrasymbiosis_draw',p,f'Terrasymbiosis: draw {amount} card(s)?',[True,False],lambda value:f'draw {amount}' if value else 'decline')
                if draw:
                    p.dungeon['terrasymbiosis_turn']=self.turn_number;self.draw(p,min(amount,40),'Terrasymbiosis')
            triggers.append({'controller':p,'source':'Terrasymbiosis','label':f'you may draw {n} cards','resolve':resolve_terrasymbiosis})
        if q.name=='Exemplar of Light' and kind=='+1/+1' and q.metadata.get('exemplar_draw_turn')!=self.turn_number:
            def resolve_exemplar():
                q.metadata['exemplar_draw_turn']=self.turn_number;self.draw(p,1,'Exemplar of Light counter trigger')
            triggers.append({'controller':self.players[q.controller],'source':'Exemplar of Light','label':'draw a card','resolve':resolve_exemplar})
        if defer_triggers is not None:defer_triggers.extend(triggers)
        else:self.resolve_simultaneous_triggers('counter-placement triggers',triggers,
                                                starter=self.players[self.turn_order[self.active_idx]])
        return n

    def resolve_all_will_be_one(self,p,target,amount):
        self.resolve_any_target_damage(p,target,amount,'All Will Be One')

    # ---------- draws / miracle / scry / surveil ----------
    def gain_life(self,p,n,reason=''):
        if n<=0:return
        if self.perm(p,'Angel of Vitality'):n+=1
        if self.perm(p,'Leyline of Hope'):n+=1
        p.life+=n;p.life_gained_this_turn+=n
        self.log('life_gain',p.name,None,f'{p.name} gains {n} life ({reason})',amount=n)
        if p.name!='Elenda':return
        triggers=[]
        def add(source,label,resolver):triggers.append({'controller':p,'source':source,'label':label,'resolve':resolver})
        pr=self.perm(p,"Ajani's Pridemate")
        if pr:add(pr.name,'put a +1/+1 counter on it',lambda:self.add_counters(p,pr,'+1/+1',1,"Ajani's Pridemate"))
        channeler=self.perm(p,'Essence Channeler')
        if channeler:add(channeler.name,'put a +1/+1 counter on it',lambda:self.add_counters(p,channeler,'+1/+1',1,'Essence Channeler lifegain trigger'))
        priest=self.perm(p,'Marauding Blight-Priest')
        if priest:add(priest.name,'each opponent loses 1 life',lambda:[self.lose_life(op,1,priest.name) for op in self.opponents(p)])
        bloodlord=self.perm(p,'Defiant Bloodlord')
        if bloodlord:
            def resolve_bloodlord():
                op=self._request_decision('defiant_bloodlord_target',p,f'Defiant Bloodlord: choose opponent to lose {n} life.',self.opponents(p),lambda op:f'{op.name} life={op.life}')
                self.lose_life(op,n,bloodlord.name)
            add(bloodlord.name,f'target opponent loses {n} life',resolve_bloodlord)
        dawn=self.perm(p,'Dawn of Hope')
        if dawn:
            def resolve_dawn():
                cost=sim.CardDef('Dawn of Hope trigger','{2}','Ability','',1,p.name,2)
                if self.can_pay(p,cost) is None:return
                pay=self._request_decision('dawn_of_hope_draw',p,'Dawn of Hope: pay {2} to draw a card?',[True,False],lambda value:'pay {2} and draw' if value else 'decline')
                if pay:self.pay(p,cost);self.draw(p,1,'Dawn of Hope lifegain trigger')
            add(dawn.name,'you may pay {2} to draw a card',resolve_dawn)
        for nm in ["Elenda's Hierophant",'Exemplar of Light','Fiendish Panda','Twinblade Paladin']:
            cr=self.perm(p,nm)
            if not cr:continue
            def resolve_counter(cr=cr,nm=nm):
                self.add_counters(p,cr,'+1/+1',1,f'{nm} lifegain trigger')
                if nm=='Exemplar of Light' and cr.metadata.get('exemplar_draw_turn')!=self.turn_number:
                    cr.metadata['exemplar_draw_turn']=self.turn_number;self.draw(p,1,'Exemplar of Light counter trigger')
            add(nm,'put a +1/+1 counter on it',resolve_counter)
        self.resolve_simultaneous_triggers('life gain event',triggers,
                                           starter=self.players[self.turn_order[self.active_idx]])

    def lose_life(self,p,n,reason=''):
        if n<=0:return
        if p.dungeon.get('adjudicated_infinite_life'):
            self.log('life_loss',p.name,None,
                     f'{p.name} loses {n} life ({reason}); adjudicated infinite life remains infinite',
                     amount=n,life_is_infinite=True)
            return
        return super().lose_life(p,n,reason)

    def draw(self,p,n=1,reason='draw'):
        for _ in range(n):
            if not p.library:
                self.log('deck_loss',p.name,None,'Tried to draw from empty library');self.eliminate(p,'drawing from an empty library');return
            c=p.library.pop();p.hand.append(c);p.cards_drawn_this_turn+=1
            if p.name=='Reaminatour':self.mark_appearance(c.d.name,drawn=True)
            self.log('draw',p.name,c.d.name,f'Drew {c.d.name}: {reason}',uid=c.uid,draw_number=p.cards_drawn_this_turn)
            if (
                self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION
                and p.cards_drawn_this_turn==1
                and self.planning_contract<3
            ):
                p.dungeon[PLANNING_CHECKPOINT_FIELD]={
                    'cadence_id':f'{p.name}|turn:{self.turn_number}|first-draw',
                    'turn':self.turn_number,'draw_event_seq':self.seq,
                }
                if (
                    self.decision_surface_revision>=OPENING_REGIME_SURFACE_REVISION
                    and self.round==1
                    and self.turn_order[self.active_idx]==p.name
                ):
                    p.dungeon[PLANNING_CHECKPOINT_FIELD][
                        'opening_long_term_plan_required'
                    ]=True
                if self.planning_contract==2:
                    self.planning_boundaries.append({
                        'actor':p.name,**self._planning_checkpoint(p,for_planner=True)})
            self.note_timing_affordance(p,c)
            triggers=[]
            if p.name=='Reaminatour' and self.perm(p,'Aminatou, Veil Piercer') and p.cards_drawn_this_turn==1 and c.d.is_enchantment:
                reveal=self._request_decision(
                    'miracle_reveal',p,
                    f'{c.d.name} is the first card you drew this turn. Reveal it for miracle?',
                    [True,False],lambda value:'reveal and trigger miracle' if value else 'do not reveal')
                if reveal:
                    p.miracle_card_uid=c.uid
                    self.log('miracle_reveal',p.name,c.d.name,f'Revealed {c.d.name} as it was drawn; miracle triggers',uid=c.uid)
                    triggers.append({
                        'controller':p,'source':'Aminatou, Veil Piercer',
                        'label':f'cast revealed {c.d.name} for its miracle cost',
                        'resolve':lambda p=p,c=c:self.resolve_miracle_trigger(p,c),
                    })
            for owner in self.players.values():
                if owner.name==p.name or owner.eliminated or not self.perm(owner,'Smothering Tithe'):continue
                def resolve_tithe(owner=owner,drawer=p):
                    tax=sim.CardDef('Smothering Tithe tax','{2}','Ability','',1,drawer.name,2)
                    can=self.can_pay(drawer,tax) is not None
                    pay=self._request_decision('smothering_tithe',drawer,f'{owner.name} controls Smothering Tithe. Pay {{2}} for this draw?',[True,False],lambda value:'pay {2}' if value else 'do not pay') if can else False
                    if pay:self.pay(drawer,tax)
                    else:
                        owner.treasures+=1;self.log('treasure',owner.name,'Smothering Tithe',f'{drawer.name} did not pay; create Treasure',treasures=owner.treasures)
                triggers.append({'controller':owner,'source':'Smothering Tithe','label':f'{p.name} may pay {{2}}; otherwise create a Treasure','resolve':resolve_tithe})
            if p.cards_drawn_this_turn==2:
                for owner in self.players.values():
                    if owner.name!=p.name and not owner.eliminated and self.perm(owner,'Gleaming Splendor'):
                        def resolve_splendor(owner=owner,drawer=p):
                            owner.treasures+=1;self.log('treasure',owner.name,'Gleaming Splendor',f'{drawer.name} drew a second card this turn; create Treasure',treasures=owner.treasures)
                        triggers.append({'controller':owner,'source':'Gleaming Splendor','label':'create a Treasure','resolve':resolve_splendor})
            self.resolve_simultaneous_triggers('card-draw triggers',triggers,
                                               starter=self.players[self.turn_order[self.active_idx]])

    def resolve_miracle_trigger(self,p,card):
        """Resolve the revealed-card miracle trigger after normal stack priority."""
        if p.miracle_card_uid!=card.uid or card not in p.hand:
            self.log('miracle_expired',p.name,card.d.name,'The revealed card is no longer in hand')
            p.miracle_card_uid=None;return False
        max_x=self.max_x_payable(p,card.d,True) if '{X}' in card.d.mana_cost else 0
        if self.can_pay(p,card.d,miracle=True,x_value=max_x) is None:
            self.log('miracle_expired',p.name,card.d.name,'Miracle trigger resolves without a legal payment')
            p.miracle_card_uid=None;return False
        cast_it=self._request_decision('miracle_cast',p,f'Cast revealed {card.d.name} for its miracle cost now?',[True,False],lambda value:'cast for miracle cost' if value else 'decline')
        if not cast_it:
            p.miracle_card_uid=None;return False
        x=0
        if '{X}' in card.d.mana_cost:
            legal=[value for value in range(self.max_x_payable(p,card.d,True)+1)
                   if self.can_pay(p,card.d,miracle=True,x_value=value) is not None]
            x=self._request_decision('x_value',p,f'Choose X for miracle {card.d.name}.',legal,lambda value:str(value))
        return self.cast(p,card,miracle=True,x_value=x)

    def scry(self,p,n,reason):
        seen=p.library[-n:]
        if not seen:return
        for c in seen:
            if p.name=='Reaminatour':self.mark_appearance(c.d.name)
        # Enumerate every legal top/bottom split and order.  Library lists are
        # stored bottom-to-top, so both groups use that same internal order.
        options=[]
        for ordering in permutations(seen):
            for bottom_count in range(len(seen)+1):
                bottom=list(ordering[:bottom_count]);top=list(ordering[bottom_count:])
                label=('top draw order: '+(', '.join(card.d.name for card in reversed(top)) if top else 'none')+
                       ' | bottom order: '+(', '.join(card.d.name for card in bottom) if bottom else 'none'))
                options.append((label,top,bottom))
        # Different permutations can describe the same state when one group is
        # empty; retain one option per exact ordered result.
        unique=[];seen_states=set()
        for option in options:
            state=(tuple(card.uid for card in option[1]),tuple(card.uid for card in option[2]))
            if state in seen_states:continue
            seen_states.add(state);unique.append(option)
        _,top,bottom=self._request_decision('scry',p,f'{reason}: choose the exact top/bottom disposition.',unique,lambda row:row[0])
        for c in seen:p.library.remove(c)
        p.library[0:0]=bottom;p.library.extend(top)
        self.log('scry',p.name,top[-1].d.name if top else None,
                 f'{reason}: top draw order={", ".join(c.d.name for c in reversed(top)) or "none"}; bottom={", ".join(c.d.name for c in bottom) or "none"}')

    def aminatou_surveil(self,p):
        seen=p.library[-min(2,len(p.library)):]
        if not seen:return
        for c in seen:self.mark_appearance(c.d.name)
        # Enumerate all legal keep/bin/order results for up to two known cards.
        options=[]
        if len(seen)==1:
            a=seen[0];options=[('keep',[a],[]),('bin',[],[a])]
        else:
            a,b=seen[-1],seen[-2]  # a current top, b second
            options=[
                (f'keep top {a.d.name}, then {b.d.name}',[b,a],[]),
                (f'keep top {b.d.name}, then {a.d.name}',[a,b],[]),
                (f'bin {a.d.name}; keep {b.d.name}',[b],[a]),
                (f'bin {b.d.name}; keep {a.d.name}',[a],[b]),
                (f'bin both {a.d.name}, {b.d.name}',[],[a,b]),
            ]
        z=self._request_decision('aminatou_surveil',p,'Aminatou upkeep surveil 2: choose exact disposition.',options,lambda z:z[0])
        _,keep_order,bins=z
        for c in seen:p.library.remove(c)
        for c in bins:p.graveyard.append(c);self.log('surveil_bin',p.name,c.d.name,'Aminatou surveil → graveyard',uid=c.uid)
        for c in keep_order:p.library.append(c)
        if keep_order:self.log('surveil_keep',p.name,keep_order[-1].d.name,'Aminatou surveil exact keep/order',uid=keep_order[-1].uid)

    def surveil(self,p,n,reason):
        """Externalize every legal keep/bin choice and the exact retained order."""
        seen=list(p.library[-min(n,len(p.library)):])
        if not seen:return
        for c in seen:
            if p.name=='Reaminatour':self.mark_appearance(c.d.name)
        options=[];seen_states=set()
        for ordering in permutations(seen):
            for bin_count in range(len(seen)+1):
                bins=list(ordering[:bin_count]);kept=list(ordering[bin_count:])
                state=(tuple(card.uid for card in kept),tuple(card.uid for card in bins))
                if state in seen_states:continue
                seen_states.add(state)
                label=('top draw order: '+(', '.join(card.d.name for card in reversed(kept)) if kept else 'none')+
                       ' | graveyard: '+(', '.join(card.d.name for card in bins) if bins else 'none'))
                options.append((label,kept,bins))
        _,kept,bins=self._request_decision('surveil',p,f'{reason}: choose the exact library/graveyard disposition.',options,lambda row:row[0])
        for c in seen:p.library.remove(c)
        p.library.extend(kept)
        for c in bins:
            p.graveyard.append(c);self.log('surveil_bin',p.name,c.d.name,f'{reason} → graveyard',uid=c.uid)
        self.log('surveil',p.name,kept[-1].d.name if kept else None,
                 f'{reason}: top draw order={", ".join(c.d.name for c in reversed(kept)) or "none"}; graveyard={", ".join(c.d.name for c in bins) or "none"}')

    def victor_eerie_trigger(self,p,victor):
        if victor not in p.battlefield:return
        if victor.metadata.get('eerie_count_turn_number')!=self.turn_number:
            victor.metadata['eerie_count_turn_number']=self.turn_number
            victor.metadata['eerie_count_turn']=0
        count=victor.metadata.get('eerie_count_turn',0)+1
        victor.metadata['eerie_count_turn']=count
        if count==1:
            self.surveil(p,2,'Victor first eerie')
        elif count==2:
            for opponent in self.opponents(p):
                if not opponent.hand:continue
                card=self._request_decision('victor_discard',opponent,
                    'Victor second eerie: choose a card to discard.',list(opponent.hand),
                    lambda card:f'{card.d.name} {card.d.mana_cost}')
                opponent.hand.remove(card);opponent.graveyard.append(card)
                self.log('discard',opponent.name,card.d.name,'Victor second eerie')
        elif count==3:
            choices=[(owner,card) for owner in self.players.values() for card in owner.graveyard if card.d.is_creature]
            if choices:
                owner,card=self._request_decision('victor_reanimate',p,
                    'Victor third eerie: choose a creature card from a graveyard.',choices,
                    lambda row:f'{row[0].name}: {row[1].d.name} {row[1].d.mana_cost}')
                owner.graveyard.remove(card);self._put_card_bf(p,card,'Victor third eerie')

    def _discover_catalog_trigger_event(self,event,sources):
        """Record card-owned subscriptions without changing rules state or event sequence."""
        matches=self.catalog_event_dispatcher.discover(event,sources,executable_only=False)
        self.catalog_trigger_audit.append({
            'event':event.kind.value,
            'active_player':event.active_player,
            'affected_player':event.affected_player,
            'payload':dict(event.payload),
            'subscriptions':[
                {
                    'controller':match.source.controller,
                    'source':match.source.card_name,
                    'source_uid':match.source.uid,
                    'ability_id':match.spec.ability_id,
                    'support_status':match.spec.support_status,
                }
                for match in matches
            ],
            'materialized_ability_ids':[],
        })
        return matches

    def enchantment_event_triggers(self,p,fully_unlocked=False):
        """Collect every constellation/eerie listener before any of them resolves.

        Catalog subscriptions now gate discovery.  Existing exact resolver closures
        remain in place, so this migration cannot change choices, labels, priority,
        APNAP placement, or deterministic decision tapes.
        """
        active=self.turn_order[self.active_idx]
        event=RuleEvent(
            EventKind.ENCHANTMENT_EVENT,
            active,
            affected_player=p.name,
            payload={'fully_unlocked':bool(fully_unlocked)},
        )
        sources=[EventSource(q.controller,q.name,q.uid) for q in p.battlefield]
        matches=self._discover_catalog_trigger_event(event,sources)
        matches_by_uid={}
        for match in matches:matches_by_uid.setdefault(match.source.uid,[]).append(match)

        def listener(name):
            permanent=self.perm(p,name)
            return permanent if permanent and matches_by_uid.get(permanent.uid) else None

        triggers=[]
        def add(source,label,resolver):
            match=matches_by_uid[source.uid][0]
            triggers.append({
                'controller':p,'source':source.name,'label':label,'resolve':resolver,
                'ability_id':match.spec.ability_id,
            })
            self.catalog_trigger_audit[-1]['materialized_ability_ids'].append(match.spec.ability_id)
        if not fully_unlocked:
            grim=listener('Grim Guardian')
            if grim:add(grim,'each opponent loses 1 life',lambda:[self.lose_life(op,1,grim.name) for op in self.opponents(p)])
            coins=listener('Underworld Coinsmith')
            if coins:add(coins,'gain 1 life',lambda:self.gain_life(p,1,coins.name))
            doom=listener('Doomwake Giant')
            if doom:add(doom,'creatures your opponents control get -1/-1 until end of turn',lambda:self.doomwake(p))
        tracker=listener('Entity Tracker')
        if tracker:add(tracker,'draw a card',lambda:self.draw(p,1,'Entity Tracker eerie'))
        dancers=listener('Ghostly Dancers')
        if dancers:add(dancers,'create a 3/1 flying Spirit token',lambda:self.token(p,'Spirit',3,1,{'flying'}))
        victor=listener("Victor, Valgavoth's Seneschal")
        if victor:add(victor,'resolve the next eerie count for this turn',lambda:self.victor_eerie_trigger(p,victor))
        return triggers

    def on_enchantment_etb(self,p,q):
        triggers=self.enchantment_event_triggers(p)
        for ephara in [permanent for permanent in p.battlefield
                       if permanent.metadata.get('transformed_invasion') and permanent.uid!=q.uid]:
            triggers.append({
                'controller':p,'source':'Ephara, Ever-Sheltering',
                'label':'draw a card for another enchantment entering',
                'resolve':lambda p=p:self.draw(p,1,'Ephara, Ever-Sheltering'),
            })
        self._dispatch_etb_triggers(p,q,triggers)

    def saga_enters(self,p,q):
        chapter=self.cruelty_read_ahead_choice(p,q) if q.name=='The Cruelty of Gix' else 1
        q.counters['lore']=chapter
        q.metadata['saga_chapter']=chapter
        trigger=self.build_saga_chapter_trigger(p,q,chapter)
        if trigger:self._dispatch_etb_triggers(p,q,[trigger])
        if chapter>=3:q.metadata['saga_enter_final_check']=True

    def saga_step(self,p):
        """Add lore as a precombat-main turn action, then stack every crossed chapter."""
        for saga in list(p.battlefield):
            if saga.name not in {'The Cruelty of Gix','Elspeth Conquers Death','The Restoration of Eiganjo',"Urza's Saga"}:continue
            if saga.name=='The Restoration of Eiganjo' and saga.metadata.get('transformed_restoration'):continue
            before=saga.counters.get('lore',0)
            placed=self.add_counters(p,saga,'lore',1,'Saga turn action')
            after=saga.counters.get('lore',before+placed)
            saga.metadata['saga_chapter']=after
            chapters=[chapter for chapter in range(before+1,min(after,3)+1)]
            if chapters:self.put_saga_chapters_on_stack(p,saga,chapters,'precombat main lore counter')

    def put_saga_chapters_on_stack(self,p,saga,chapters,event):
        triggers=[]
        for chapter in chapters:
            trigger=self.build_saga_chapter_trigger(p,saga,chapter)
            if trigger:triggers.append(trigger)
        self.resolve_simultaneous_triggers(event,triggers,starter=p)
        if saga in p.battlefield and saga.counters.get('lore',0)>=3:
            if saga.name in {'The Cruelty of Gix','Elspeth Conquers Death',"Urza's Saga"}:
                self.leave_battlefield(p,saga,'graveyard','Saga final chapter left the stack')
            elif saga.name=='The Restoration of Eiganjo' and not saga.metadata.get('transformed_restoration'):
                self.leave_battlefield(p,saga,'graveyard','Restoration final chapter left the stack without transforming')

    def build_saga_chapter_trigger(self,p,saga,chapter):
        name=saga.name;payload={};targets=[]
        if name=='The Cruelty of Gix' and chapter==1:
            opponent=self._request_decision('cruelty_opponent',p,'The Cruelty of Gix I: choose target opponent.',self.opponents(p),lambda player:player.name)
            payload['opponent']=opponent
        elif name=='The Cruelty of Gix' and chapter==3:
            choices=[(owner,card) for owner in self.players.values() for card in owner.graveyard if card.d.is_creature]
            if choices:payload['grave_target']=self._request_decision('cruelty_reanimate',p,'The Cruelty of Gix III: choose target creature card in a graveyard.',choices,lambda row:f'{row[0].name}: {row[1].d.name}')
        elif name=='Elspeth Conquers Death' and chapter==1:
            choices=[(owner,target) for owner,target in self.all_permanents() if owner is not p and sim.CARDDEF.get(target.copy_of or target.name) and sim.CARDDEF[target.copy_of or target.name].mv>=3 and not self.has_hexproof(target)]
            if choices:
                payload['target']=self._request_decision('ecd_exile_target',p,'Elspeth Conquers Death I: choose target permanent with mana value 3 or greater.',choices,lambda row:f'{row[0].name}: {row[1].name}')
                targets=[payload['target'][1]]
        elif name=='Elspeth Conquers Death' and chapter==3:
            choices=[card for card in p.graveyard if card.d.is_creature or card.d.is_planeswalker]
            if choices:payload['grave_target']=self._request_decision('ecd_return_target',p,'Elspeth Conquers Death III: choose target creature or planeswalker card.',choices,lambda card:card.d.name)
        label=f'chapter {chapter}'
        trigger={'controller':p,'source':name,'label':label,'targets':targets,
                 'resolve':lambda:self.resolve_saga_chapter_refereed(p,saga,chapter,payload)}
        if chapter>=3 and name in {'The Cruelty of Gix','Elspeth Conquers Death',"Urza's Saga"}:
            # CR 714.4 is checked after the final chapter ability leaves the
            # stack and before priority.  The outer saga-step cleanup runs only
            # after resolve_simultaneous_triggers returns, which is too late:
            # that helper opens a priority window after each resolved trigger.
            trigger['post_resolve_sba']=lambda:self.leave_battlefield(
                p,saga,'graveyard','Saga final chapter left the stack') if saga in p.battlefield else None
        return trigger

    def resolve_saga_chapter_refereed(self,p,saga,chapter,payload):
        name=saga.name
        self.log('saga_chapter',p.name,name,f'Chapter {chapter} resolves',chapter=chapter)
        if name=='The Cruelty of Gix':
            if chapter==1:
                opponent=payload['opponent'];self.log('reveal_hand',opponent.name,name,f'{opponent.name} reveals '+(', '.join(card.d.name for card in opponent.hand) or 'an empty hand'))
                eligible=[card for card in opponent.hand if card.d.is_creature or card.d.is_planeswalker]
                card=self._request_decision('cruelty_discard',p,'Choose a creature or planeswalker card for that player to discard, or decline.',eligible,lambda card:card.d.name,allow_pass=True) if eligible else None
                if card:opponent.hand.remove(card);opponent.graveyard.append(card);self.log('discard',opponent.name,card.d.name,name+' I')
            elif chapter==2:
                card=self._request_decision('tutor',p,'The Cruelty of Gix II: choose a card to put into your hand.',list(p.library),lambda card:f'{card.d.name} {card.d.mana_cost}') if p.library else None
                if card:p.library.remove(card);p.hand.append(card);self.rng.shuffle(p.library);self.log('tutor',p.name,card.d.name,name+' II',destination='hand')
                self.lose_life(p,3,name+' II')
            elif chapter==3 and payload.get('grave_target'):
                owner,card=payload['grave_target']
                if card in owner.graveyard:owner.graveyard.remove(card);self._put_card_bf(p,card,name+' III')
        elif name=='Elspeth Conquers Death':
            if chapter==1 and payload.get('target'):
                owner,target=payload['target']
                if self.target_still_legal(p,owner,target):self.exile_perm(owner,target,name+' I')
            elif chapter==2:self.establish_ecd_tax(p)
            elif chapter==3 and payload.get('grave_target') in p.graveyard:
                card=payload['grave_target'];p.graveyard.remove(card);returned=self._put_card_bf(p,card,name+' III')
                counter='loyalty' if card.d.is_planeswalker else '+1/+1';self.add_counters(p,returned,counter,1,name+' III')
        elif name=='The Restoration of Eiganjo':
            if chapter==1:
                choices=[card for card in p.library if card.d.type_line.startswith('Basic Land') and 'Plains' in card.d.type_line]
                card=self._request_decision('restoration_plains',p,'Restoration I: choose a basic Plains card.',choices,lambda card:card.d.name) if choices else None
                if card:p.library.remove(card);p.hand.append(card);self.rng.shuffle(p.library);self.log('tutor',p.name,card.d.name,name+' I',destination='hand',visibility='public')
            elif chapter==2:
                if not p.hand:return
                discard=self._request_decision('restoration_discard',p,'Restoration II: discard a card to create its return trigger?',list(p.hand),lambda card:f'discard {card.d.name}',allow_pass=True)
                if not discard:return
                p.hand.remove(discard);p.graveyard.append(discard);self.log('discard',p.name,discard.d.name,name+' II')
                legal=[card for card in p.graveyard if card.d.is_permanent and card.d.mv<=2]
                target=self._request_decision('restoration_return_target',p,'Restoration II reflexive trigger: choose target permanent card with mana value 2 or less.',legal,lambda card:card.d.name) if legal else None
                if target:
                    def resolve_return():
                        if target in p.graveyard:p.graveyard.remove(target);returned=self._put_card_bf(p,target,name+' II');returned.tapped=True
                    self.resolve_simultaneous_triggers('Restoration II reflexive trigger',[{'controller':p,'source':name,'label':f'return {target.d.name} tapped','resolve':resolve_return}],starter=p)
            elif chapter==3:self.transform_restoration(p,saga)
        elif name=="Urza's Saga":
            if chapter==1 and saga in p.battlefield:saga.metadata['urza_mana']=True
            elif chapter==2 and saga in p.battlefield:saga.metadata['saga_chapter']=max(2,saga.metadata.get('saga_chapter',0))
            elif chapter==3:
                choices=[card for card in p.library if card.d.is_artifact and card.d.mana_cost in {'{0}','{1}'}]
                card=self._request_decision('urza_saga_artifact',p,"Urza's Saga III: choose an artifact with mana cost {0} or {1}, or fail to find.",choices,lambda card:f'{card.d.name} {card.d.mana_cost}',allow_pass=True) if choices else None
                if card:p.library.remove(card);self._put_card_bf(p,card,"Urza's Saga III")
                self.rng.shuffle(p.library)

    def transform_restoration(self,p,saga):
        if saga not in p.battlefield:return
        uid=saga.uid;owner=self.players[saga.owner]
        self.leave_battlefield(p,saga,'exile','Restoration III exile to transform')
        card=next((card for card in owner.exile if card.uid==uid),None)
        if not card:return
        owner.exile.remove(card)
        returned=sim.Perm(uid,saga.name,saga.owner,p.name,False,True,{},None,None,False,3,4,{'vigilance'},self.turn_number,
                          {'transformed_restoration':True})
        p.battlefield.append(returned);p.enchantments_entered_this_turn+=1
        self.log('transform',p.name,saga.name,'Returned transformed as Architect of Restoration',uid=uid)
        self.on_enchantment_etb(p,returned)

    def unlock_awakening_hall(self,p,room,reason='unlock'):
        if room.metadata.get('awakening_unlocked'):return False
        room.metadata['awakening_unlocked']=True
        triggers=self.enchantment_event_triggers(p,fully_unlocked=True)
        def resolve_hall():
            creatures=[card for card in list(p.graveyard) if card.d.is_creature]
            self.log('room_unlock_resolve',p.name,room.name,f'Awakening Hall returns {len(creatures)} creature card(s)')
            returning=[card for card in creatures if card in p.graveyard]
            for card in returning:p.graveyard.remove(card)
            self.put_cards_bf_simultaneously(p,returning,'Awakening Hall unlock')
        triggers.append({'controller':p,'source':room.name,'label':'return all creature cards from your graveyard to the battlefield','resolve':resolve_hall})
        self.log('room_unlock',p.name,room.name,f'Awakening Hall fully unlocked via {reason}')
        self.resolve_simultaneous_triggers('fully unlock a Room',triggers,
                                           starter=self.players[self.turn_order[self.active_idx]])
        return True


    def create_boo(self,p):
        boo=self.token(p,'Boo',1,1,{'trample','haste'})
        self.check_boo_legend_rule(p,boo)
        return boo

    def check_boo_legend_rule(self,p,new_boo=None):
        legends=[q for q in p.battlefield if (q.copy_of or q.name)=='Boo'
                 and not sim.permanent_phased_out(q) and 'Legendary' in self.continuous_view(q).types]
        if len(legends)>1:
            keep=self._request_decision(
                'boo_legend_rule',p,'Legend rule: choose which Boo to keep.',legends,
                lambda q:f'{"new Boo" if q is new_boo else "existing Boo"} {self.effective_power(q)}/{self.effective_toughness(q)}'+(' (mutated)' if q.metadata.get('mutated') else ''))
            for other in list(legends):
                if other is not keep:self.leave_battlefield(p,other,'graveyard','legend rule: Boo')

    def offer_create_boo(self,p):
        create=self._request_decision(
            'minsc_boo_create',p,'Minsc & Boo: create a Boo token?',
            [True,False],lambda value:'create Boo' if value else 'decline')
        return self.create_boo(p) if create else None

    def upkeep(self,p):
        self.phase='upkeep';p.cards_drawn_this_turn=0;p.spells_cast_this_turn=0;p.enchantments_entered_this_turn=0;p.life_gained_this_turn=0;p.counters_placed_this_turn=0;p.miracle_card_uid=None
        for q in p.battlefield:
            if q.name=="Victor, Valgavoth's Seneschal":
                q.metadata['eerie_count_turn_number']=self.turn_number;q.metadata['eerie_count_turn']=0
        triggers=[]
        def add(source,label,resolver,controller=p):
            triggers.append({'controller':controller,'source':source,'label':label,'resolve':resolver})
        for guide in [q for q in p.battlefield
                      if (q.copy_of or q.name)=='Karmic Guide'
                      and q.metadata.pop('echo_pending',False)]:
            def resolve_echo(guide=guide):
                # If this exact battlefield object has left, its echo trigger
                # has no effect.  A returned Guide is a new object with its own
                # future echo obligation.
                if guide not in p.battlefield:return
                cost=sim.CardDef('Karmic Guide echo','{3}{W}{W}','Ability','',1,p.name,5)
                can_pay=self.can_pay(p,cost) is not None
                pay=self._request_decision(
                    'karmic_guide_echo',p,
                    'Karmic Guide echo — pay {3}{W}{W} or sacrifice it.',
                    [True,False],lambda value:'pay {3}{W}{W}' if value else 'sacrifice Karmic Guide') if can_pay else False
                if pay:self.pay(p,cost)
                else:self.leave_battlefield(p,guide,'graveyard','Karmic Guide echo not paid')
            add(guide.name,'echo — sacrifice unless you pay {3}{W}{W}',resolve_echo)
        minsc=self.perm(p,'Minsc & Boo, Timeless Heroes')
        if minsc:
            add(minsc.name,'you may create Boo',lambda:self.offer_create_boo(p))
        # Loaded legacy state may predate departure cleanup, so defensively
        # discard any stale record before constructing optional draw prompts.
        self.pending_arcane_denials=[
            row for row in self.pending_arcane_denials
            if ((self.players.get(row.get('spell_controller')) is not None and
                 not self.players[row['spell_controller']].eliminated) and
                (self.players.get(row.get('denial_controller')) is not None and
                 not self.players[row['denial_controller']].eliminated))]
        due=[row for row in self.pending_arcane_denials if row['due_turn']<=self.turn_number]
        self.pending_arcane_denials=[row for row in self.pending_arcane_denials if row not in due]
        for row in due:
            spell_controller=self.players[row['spell_controller']];denial_controller=self.players[row['denial_controller']]
            add('Arcane Denial',f'{spell_controller.name} may draw two cards',
                lambda spell_controller=spell_controller:self.draw(spell_controller,self._request_decision('arcane_denial_draw',spell_controller,'Arcane Denial: draw up to two cards.',[0,1,2],lambda amount:str(amount)),'Arcane Denial delayed upkeep trigger'),denial_controller)
            add('Arcane Denial',f'{denial_controller.name} may draw one card',
                lambda denial_controller=denial_controller:self.draw(denial_controller,1,'Arcane Denial delayed upkeep trigger') if self._request_decision('arcane_denial_draw',denial_controller,'Arcane Denial: draw a card?',[True,False],lambda value:'draw' if value else 'decline') else None,denial_controller)
        wave=self.perm(p,'Parallax Wave')
        if wave:
            def resolve_fading():
                if wave not in p.battlefield:return
                if wave.counters.get('fade',0)>0:
                    wave.counters['fade']-=1;self.log('fading',p.name,'Parallax Wave',f'Remove fade counter at upkeep; {wave.counters.get("fade",0)} remain')
                else:self.leave_battlefield(p,wave,'graveyard','Fading: unable to remove fade counter; sacrifice')
            add(wave.name,'remove a fade counter; sacrifice if unable',resolve_fading)
        sf=self.perm(p,'Starfield of Nyx')
        if sf:
            ens=[c for c in p.graveyard if c.d.is_enchantment]
            # The trigger's target is mandatory even though returning it is optional.
            # A snooze cannot remove this trigger before it reaches the stack.
            target=self._request_decision('starfield_upkeep',p,'Starfield of Nyx: choose target enchantment card.',ens,lambda c:f'{c.d.name} [{c.d.mana_cost}]') if ens else None
            if target:
                def resolve_starfield(target=target):
                    if not any(card is target for card in p.graveyard):return
                    if self._request_decision('starfield_return',p,f'Starfield of Nyx: return {target.d.name} to the battlefield?',
                            [True,False],lambda yes:'return enchantment' if yes else 'leave it in the graveyard'):
                        self._put_card_bf(p,p.graveyard.pop(p.graveyard.index(target)),'Starfield of Nyx upkeep')
                add(sf.name,f'you may return target {target.d.name}',resolve_starfield)
        amin=self.active_ability_perm(p,'Aminatou, Veil Piercer')
        if amin:add(amin.name,'surveil 2',lambda:self.aminatou_surveil(p))
        arena=self.perm(p,'Phyrexian Arena')
        if arena:add(arena.name,'draw a card and lose 1 life',lambda:(self.lose_life(p,1,'Phyrexian Arena upkeep'),self.draw(p,1,'Phyrexian Arena')))
        tor=self.perm(p,'Indulgent Tormentor')
        if tor:
            op=self._request_decision('tormentor_target',p,'Indulgent Tormentor: choose target opponent.',self.opponents(p),lambda x:f'{x.name} life={x.life}')
            def resolve_tormentor(op=op):
                if op.eliminated:return
                opts=[('decline',None),('pay3',None)]+[('sac',q) for q in op.battlefield if self.is_creature_perm(q)]
                z=self._request_decision('tormentor_opponent_choice',op,'Indulgent Tormentor: sacrifice a creature or pay 3 life; otherwise controller draws.',opts,lambda z:'do neither' if z[0]=='decline' else ('pay 3 life' if z[0]=='pay3' else 'sacrifice '+z[1].name))
                if z[0]=='pay3':self.lose_life(op,3,'Indulgent Tormentor')
                elif z[0]=='sac':self.leave_battlefield(op,z[1],'graveyard','Indulgent Tormentor sacrifice')
                else:self.draw(p,1,'Indulgent Tormentor upkeep')
            add(tor.name,f'{op.name} sacrifices, pays 3 life, or you draw',resolve_tormentor)
        fa=self.perm(p,'Forgotten Ancient')
        if fa and fa.counters.get('+1/+1',0)>0:
            def resolve_forgotten():
                remaining=fa.counters.get('+1/+1',0)
                while remaining>0:
                    targets=[q for q in p.battlefield if self.is_creature_perm(q) and q.uid!=fa.uid]
                    if not targets:break
                    target=self._request_decision('forgotten_ancient_target',p,f'Forgotten Ancient: move counters? {remaining} available.',targets,lambda q:q.name,allow_pass=True)
                    if target is None:break
                    amounts=list(range(1,remaining+1))
                    amt=self._request_decision('forgotten_ancient_amount',p,f'How many counters move to {target.name}?',amounts,lambda x:str(x))
                    fa.counters['+1/+1']-=amt;self.add_counters(p,target,'+1/+1',amt,'Forgotten Ancient upkeep transfer');remaining-=amt
            add(fa.name,'move any number of +1/+1 counters to other creatures',resolve_forgotten)
        ss=self.perm(p,"Sigarda's Splendor")
        if ss:
            def resolve_splendor():
                last=ss.metadata.get('noted_life',p.life)
                if p.life>=last:self.draw(p,1,"Sigarda's Splendor upkeep")
                ss.metadata['noted_life']=p.life
            add(ss.name,'draw if your life is at least its noted value',resolve_splendor)
        rem=self.perm(p,'Mystic Remora')
        if rem:
            def resolve_remora_upkeep():
                if rem not in p.battlefield:return
                self.add_counters(p,rem,'age',1,'Mystic Remora cumulative upkeep')
                age=rem.counters.get('age',0)
                cost=sim.CardDef('Remora upkeep',f'{{{age}}}','Ability','',1,p.name,age)
                can=self.can_pay(p,cost) is not None
                pay=self._request_decision('remora_upkeep',p,f'Mystic Remora cumulative upkeep is {{{age}}}. Pay it?', [True,False],lambda x:'pay' if x else 'sacrifice Remora') if can else False
                if pay:self.pay(p,cost)
                else:self.leave_battlefield(p,rem,'graveyard','did not pay cumulative upkeep')
            add(rem.name,'cumulative upkeep',resolve_remora_upkeep)
        lotus=self.perm(p,'Lotus Blossom')
        if lotus:
            def resolve_lotus():
                place=self._request_decision('lotus_petal',p,'Lotus Blossom: put a petal counter on it?',[True,False],lambda value:'put a petal counter' if value else 'decline')
                if place and lotus in p.battlefield:self.add_counters(p,lotus,'petal',1,'Lotus Blossom upkeep')
            add(lotus.name,'you may put a petal counter on it',resolve_lotus)
        for controller in self.players.values():
            for dance in [q for q in controller.battlefield if q.name=='Dance of the Dead' and q.attached_to]:
                enchanted=next((q for owner in self.players.values() for q in owner.battlefield if q.uid==dance.attached_to and q.controller==p.name),None)
                if not enchanted:continue
                def resolve_dance(dance=dance,enchanted=enchanted):
                    cost=sim.CardDef('Dance of the Dead upkeep','{1}{B}','Ability','',1,p.name,2)
                    can=self.can_pay(p,cost) is not None
                    pay=self._request_decision('dance_untap',p,f'Dance of the Dead: pay {{1}}{{B}} to untap {enchanted.name}?',[True,False],lambda value:'pay and untap' if value else 'decline') if can else False
                    if pay and enchanted in p.battlefield:self.pay(p,cost);enchanted.tapped=False
                add(dance.name,f'you may pay {{1}}{{B}} to untap {enchanted.name}',resolve_dance)
        self.resolve_simultaneous_triggers('beginning of upkeep',triggers,starter=p)

    def announced_spell_state(self,p,card):
        return p.dungeon.setdefault('announced_spells',{}).get(card.uid,{})

    def public_stack_targets(self,values):
        """Return stable public identifiers and labels for locked stack targets."""
        targets=[];target_names=[];seen=set()
        players=list(self.players.values())
        def add(value):
            if isinstance(value,(tuple,list)):
                if isinstance(value,tuple):
                    if value:add(value[-1])
                else:
                    for item in value:add(item)
                return
            uid=getattr(value,'uid',None)
            name=(getattr(value,'name',None) or
                  getattr(getattr(value,'d',None),'name',None))
            if uid:
                identity=str(uid);label=f'{name or "Unknown object"} [{identity}]'
            elif name:
                identity=str(name);label=('PLAYER ' if any(value is player for player in players) else '')+identity
            elif isinstance(value,str):
                identity=value;label=value
            else:return
            if identity in seen:return
            seen.add(identity);targets.append(identity);target_names.append(label)
        for value in values:add(value)
        return targets,target_names

    def announce_spell_choices(self,p,c,x_value=0,overload=False):
        n=c.d.name;state={'targets':[]}
        def legal_permanent(owner,target,creature=False):return self.target_still_legal(p,owner,target,creature,n)
        def select_target(kind,prompt,choices,label,allow_pass=False):
            value=self._request_decision(kind,p,prompt,choices,label,allow_pass=allow_pass)
            if value:
                if isinstance(value,tuple) and len(value)>=2 and hasattr(value[-1],'uid'):state['targets'].append(value[-1])
                elif hasattr(value,'uid'):state['targets'].append(value)
            return value
        if n in {'Bulk Up','Unleash Fury','Give In to Violence'}:
            choices=[(owner,q) for owner,q in self.all_creatures() if legal_permanent(owner,q,True)]
            state['target']=select_target('spell_target',f'{n}: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
        elif n=='Invigorating Surge':
            target=select_target('spell_target',n+': choose target creature you control.',[q for q in p.battlefield if legal_permanent(p,q,True)],lambda q:q.name);state['target']=(p,target)
        elif n=='Ram Through':
            own=select_target('ram_source_target','Ram Through: choose target creature you control.',[q for q in p.battlefield if legal_permanent(p,q,True)],lambda q:q.name)
            enemy=select_target('ram_enemy_target',"Ram Through: choose target creature you don't control.",[(owner,q) for owner in self.opponents(p) for q in owner.battlefield if legal_permanent(owner,q,True)],lambda row:f'{row[0].name}: {row[1].name}')
            state.update(own=own,enemy=enemy)
        elif n in {'Moment of Craving','Deadly Riposte'}:
            choices=[(owner,q) for owner,q in self.all_creatures() if legal_permanent(owner,q,True) and (n!='Deadly Riposte' or q.tapped)]
            state['target']=select_target('spell_target',f'{n}: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
        elif n=='Devouring Light':
            context=p.dungeon.get('cast_priority_context',{});ids=set(context.get('attackers',[]))
            for values in context.get('blocks',{}).values():ids.update(values)
            choices=[(owner,q) for owner,q in self.all_creatures() if q.uid in ids and legal_permanent(owner,q,True)]
            state['target']=select_target('spell_target','Devouring Light: choose target attacking or blocking creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
        elif n in {'Beast Within','Chaos Warp','Pongify','Breathe Your Last','Utter End',"Hero's Downfall",'Murder'}:
            choices=[]
            for owner,q in self.all_permanents():
                d=sim.CARDDEF.get(q.name);legal=legal_permanent(owner,q)
                if n in {'Pongify','Murder'}:legal&=self.is_creature_perm(q)
                elif n in {'Breathe Your Last',"Hero's Downfall"}:legal&=(self.is_creature_perm(q) or self.is_planeswalker_perm(q))
                elif n=='Utter End':legal&=not sim.is_land_permanent(q)
                if legal:choices.append((owner,q))
            state['target']=select_target('removal_target',f'{n}: choose target.',choices,lambda row:f'{row[0].name}: {row[1].name}')
        elif n=='Valorous Stance':
            protect=[q for q in p.battlefield if legal_permanent(p,q,True)]
            destroy=[(owner,q) for owner in self.opponents(p) for q in owner.battlefield if legal_permanent(owner,q,True) and self.toughness(q)>=4]
            modes=(['protect'] if protect else [])+(['destroy'] if destroy else [])
            mode=self._request_decision('valorous_mode',p,'Valorous Stance: choose a mode.',modes,lambda value:value);state['mode']=mode
            state['target']=select_target('spell_target','Choose the target.',protect if mode=='protect' else destroy,
                                   (lambda q:q.name) if mode=='protect' else (lambda row:f'{row[0].name}: {row[1].name}'))
            if mode=='protect':state['target']=(p,state['target'])
        elif n=='Death Grasp':
            legal_targets=[row for row in self.death_grasp_targets(p) if row[0]=='player' or legal_permanent(row[1],row[2])]
            state['target']=self._request_decision('death_grasp_target',p,'Death Grasp: choose one target.',legal_targets,
                lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player' else f'{row[0].upper()} {row[1].name}: {row[2].name}'))
            if state['target'][0]!='player':state['targets'].append(state['target'][2])
        elif n=='Return of the Wildspeaker':
            state['mode']=self._request_decision(
                'wildspeaker_mode',p,'Return of the Wildspeaker: choose a mode as the spell is cast.',
                ['draw','pump'],lambda value:('draw equal to greatest non-Human power' if value=='draw' else 'non-Humans get +3/+3'))
        elif n in {'Zombify','Restart Sequence'}:
            card=select_target('reanimation_spell_target',f'{n}: choose target creature card in your graveyard.',[card for card in p.graveyard if card.d.is_creature],lambda card:f'{card.d.name} {card.d.mana_cost}')
            state['grave_target']=card
        elif n=='Fangs of Kalonia' and not overload:
            target=select_target('spell_target','Fangs of Kalonia: choose target creature you control.',[q for q in p.battlefield if legal_permanent(p,q,True)],lambda q:q.name);state['target']=(p,target)
        elif n=='Aggressive Biomancy':
            target=select_target('spell_target','Aggressive Biomancy: choose target creature you control.',[q for q in p.battlefield if legal_permanent(p,q,True)],lambda q:q.name);state['target']=(p,target)
        elif n=='March from Velis Vel':
            target=select_target('spell_target','March from Velis Vel: choose target creature you control.',[q for q in p.battlefield if legal_permanent(p,q,True)],lambda q:q.name);state['target']=(p,target)
        elif n=='Replication Technique':
            target=select_target('spell_target','Replication Technique: choose target permanent you control.',[q for q in p.battlefield if legal_permanent(p,q)],lambda q:q.name);state['target']=(p,target)
        elif n in {'Animate Dead','Dance of the Dead'}:
            choices=[(owner,card) for owner in self.players.values() for card in owner.graveyard if card.d.is_creature]
            chosen=self._request_decision('aura_grave_target',p,f'{n}: choose target creature card in a graveyard.',choices,lambda row:f'{row[0].name}: {row[1].d.name}')
            state['grave_target']=chosen
        elif n in {'Angelic Destiny','Fallen Ideal','Darksteel Mutation','Changing Loyalty','Glasswing Grace // Age-Graced Chapel','Parasitic Impetus'}:
            choices=[(owner,q) for owner,q in self.all_creatures() if legal_permanent(owner,q,True)]
            chosen=select_target('aura_target',f'{n}: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
            state['target']=chosen
        p.dungeon.setdefault('announced_spells',{})[c.uid]=state
        return state

    def resolve_ward_triggers(self,caster,stack_marker,targets):
        triggers=[];countered={'value':False}
        for target in targets:
            # Ward is a permanent ability. "Any target" effects can also
            # legally target a player, whose PlayerState deliberately has no
            # controller. Player targets therefore bypass the ward scan.
            controller=getattr(target,'controller',None)
            if controller is None:continue
            owner=self.players[controller]
            if owner is caster or not self.has_ward_one(target):continue
            def resolve_ward(owner=owner,target=target):
                tax=sim.CardDef('Ward {1}','{1}','Ability','',1,caster.name,1)
                can=self.can_pay(caster,tax) is not None
                pay=self._request_decision('ward_payment',caster,f'{target.name} has ward {{1}}. Pay it?',[True,False],lambda value:'pay ward' if value else 'do not pay') if can else False
                if pay:self.pay(caster,tax)
                else:countered['value']=True
            triggers.append({'controller':owner,'source':target.name,'label':'ward {1}: counter unless its controller pays {1}','resolve':resolve_ward})
        self.resolve_simultaneous_triggers('ward triggers',triggers,starter=self.players[self.turn_order[self.active_idx]])
        if countered['value'] and stack_marker in self.stack:self.stack.remove(stack_marker)
        return countered['value']

    def devouring_light_payment_plans(self,p):
        """Enumerate exact convoke choices plus the mana left to pay.

        Convoke may tap a creature with summoning sickness.  Each such creature
        pays either one generic mana or one mana of one of its colors.  The
        fixed pod's only modeled cost increase is Elspeth Conquers Death, which
        is folded into the residual generic cost before ordinary mana payment.
        """
        creatures=[q for q in p.battlefield if self.is_creature_perm(q) and not q.tapped]
        white=[q for q in creatures if 'W' in self.continuous_view(q).colors]
        generic_cost=1+self.noncreature_spell_tax(p)
        plans=[]
        for white_paid in range(min(2,len(white))+1):
            for colored in combinations(white,white_paid):
                remaining_creatures=[q for q in creatures if q not in colored]
                for generic_paid in range(min(generic_cost,len(remaining_creatures))+1):
                    for generic in combinations(remaining_creatures,generic_paid):
                        residual_generic=generic_cost-generic_paid
                        residual_white=2-white_paid
                        cost=(f'{{{residual_generic}}}' if residual_generic else '')+'{W}'*residual_white
                        payment=sim.CardDef('Devouring Light residual cost',cost,'Creature','',1,p.name,residual_generic+residual_white)
                        tapped=list(colored)+list(generic)
                        for creature in tapped:creature.tapped=True
                        try:payable=self.can_pay(p,payment) is not None
                        finally:
                            for creature in tapped:creature.tapped=False
                        if not payable:continue
                        roles=[]
                        if colored:roles.append(', '.join(f'{q.name} [{q.uid}] for {{W}}' for q in colored))
                        if generic:roles.append(', '.join(f'{q.name} [{q.uid}] for {{1}}' for q in generic))
                        convoke='; '.join(roles) if roles else 'no creatures'
                        remainder=cost or 'nothing'
                        plans.append({'colored':list(colored),'generic':list(generic),'payment':payment,
                                      'label':f'Convoke {convoke}; pay {remainder} with mana'})
        return plans

    def pay_devouring_light(self,p):
        plans=self.devouring_light_payment_plans(p)
        if not plans:return False
        plan=self._request_decision('convoke_payment',p,
            'Devouring Light: choose all creatures to tap for convoke and how each contributes.',
            plans,lambda value:value['label'])
        creatures=plan['colored']+plan['generic']
        for creature in creatures:creature.tapped=True
        payment=plan['payment']
        if payment.mana_cost and not self.pay(p,payment):
            for creature in creatures:creature.tapped=False
            return False
        self.log('convoke_payment',p.name,'Devouring Light',plan['label'],
                 creatures=[creature.uid for creature in creatures],remaining_cost=payment.mana_cost)
        return True

    @resolution_sequence
    def cast(self,p,c,commander=False,miracle=False,x_value=0,free=False,kicked=False,overload=False,evoke=False,counter_target=None):
        # Bind advice to the decision that initiated this cast. A later target
        # or payment packet may contain a newer plan during the same cast.
        planning_origin=({'cast_decision_id':next((row['decision_id'] for row in reversed(self.decisions)
                          if row['actor']==p.name),None)} if self.planning_contract>=3 else {})
        autoresolve=bool(p.dungeon.pop('next_cast_autoresolve',None))
        stack_was_empty=not self.stack
        announced=self.announce_spell_choices(p,c,x_value=x_value,overload=overload)
        p.dungeon['last_payment_sources']=[]
        additional=None
        if c.d.name in {'Fling',"Kazuul's Fury // Kazuul's Cliffs"}:
            creatures=[q for q in p.battlefield if self.is_creature_perm(q)]
            sacrifice=self._request_decision('fling_sacrifice',p,f'{c.d.name}: choose the creature to sacrifice as an additional cost.',creatures,
                                              lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')
            targets=[row for row in self.death_grasp_targets(p) if row[0]=='player' or self.target_still_legal(p,row[1],row[2],source_name=c.d.name)]
            target=self._request_decision('fling_target',p,f'{c.d.name}: choose any target.',targets,
                       lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player' else f'{row[0].upper()} {row[1].name}: {row[2].name}'))
            additional=('fling',sacrifice,target)
        elif c.d.name=='Crop Rotation':
            lands=[q for q in p.battlefield if sim.is_land_permanent(q)]
            sacrifice=self._request_decision('crop_rotation_sacrifice',p,'Crop Rotation: choose a land to sacrifice as an additional cost.',lands,lambda q:q.name)
            additional=('crop',sacrifice)
        if c.d.name=="Chandra's Ignition":
            targets=[q for q in p.battlefield if self.target_still_legal(p,p,q,True,c.d.name)]
            target=self._request_decision('chandra_target',p,"Chandra's Ignition: choose target creature you control.",targets,
                                          lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')
            p.dungeon['chandra_target_uid']=target.uid
        if c.d.name=='Curse of the Swine':
            candidates=[(owner,q) for owner in self.players.values() for q in owner.battlefield
                        if self.target_still_legal(p,owner,q,True,c.d.name)]
            selected=[]
            for slot in range(x_value):
                target=self._request_decision(
                    'curse_target',p,f'Curse of the Swine: choose target creature {slot+1} of {x_value}.',
                    [row for row in candidates if row not in selected],
                    lambda row:f'{row[0].name}: {row[1].name} {self.effective_power(row[1])}/{self.effective_toughness(row[1])}')
                selected.append(target)
            p.dungeon['curse_target_uids']=[q.uid for _,q in selected]
        payment_def=c.d
        if kicked:payment_def=sim.CardDef(c.d.name+' kicked','{4}{B}{B}',c.d.type_line,c.d.text,1,p.name,6)
        elif overload:payment_def=sim.CardDef(c.d.name+' overload','{4}{G}{G}',c.d.type_line,c.d.text,1,p.name,6)
        elif evoke:
            evoke_costs={'Reveillark':'{5}{W}','Vesperlark':'{1}{W}','Mulldrifter':'{2}{U}'}
            payment_def=sim.CardDef(c.d.name+' evoke',evoke_costs[c.d.name],c.d.type_line,c.d.text,1,p.name,sim.mana_value(evoke_costs[c.d.name]))
        if not free and c.d.name=='Devouring Light':
            if not self.pay_devouring_light(p):return False
        elif not free and not self.pay(p,payment_def,commander=commander,miracle=miracle,x_value=x_value):return False
        cost_triggers=[]
        if additional:
            self.__dict__.setdefault('_ltb_trigger_frames',[]).append(cost_triggers)
            try:
                if additional[0]=='fling':
                    sacrifice=additional[1];p.dungeon['fling_target']=additional[2]
                    p.dungeon['fling_damage']=self.effective_power(sacrifice)
                    self.leave_battlefield(p,sacrifice,'graveyard',c.d.name+' additional cost')
                else:
                    self.leave_battlefield(p,additional[1],'graveyard','Crop Rotation additional cost')
            finally:self._ltb_trigger_frames.pop()
        if commander:
            assert p.commander and p.commander.uid==c.uid;p.commander=None;p.dungeon['commander_casts']=p.dungeon.get('commander_casts',0)+1
        else:
            if c not in p.hand:return False
            p.hand.remove(c)
        p.spells_cast_this_turn+=1;self.mark_appearance(c.d.name,cast=True)
        modes={'kicked':kicked,'overload':overload,'evoke':evoke,
               'necromancy_flash':c.d.name=='Necromancy' and not (self.phase in {'precombat_main','postcombat_main'} and self.players[self.turn_order[self.active_idx]] is p and not self.stack)}
        p.dungeon.setdefault('resolving_cast_modes',{})[c.uid]=modes
        suffix=(' for miracle cost' if miracle else '')+(' for free' if free else '')+(' kicked' if kicked else '')+(' for overload' if overload else '')+(' for evoke' if evoke else '')
        target_values=list(announced.get('targets',[]))
        if 'target' in announced:target_values.append(announced['target'])
        if 'grave_target' in announced:target_values.append(announced['grave_target'])
        if additional and additional[0]=='fling':target_values.append(additional[2])
        if c.d.name=='Curse of the Swine':target_values.extend(selected)
        if c.d.name=="Chandra's Ignition":target_values.append(target)
        if counter_target is not None:target_values.append(counter_target[1])
        target_uids,target_names=self.public_stack_targets(target_values)
        self.log('cast',p.name,c.d.name,f'Cast {c.d.name}'+suffix,uid=c.uid,commander=commander,miracle=miracle,x=x_value,modes=modes,**planning_origin)
        spell_marker={'actor':p.name,'uid':c.uid,'card':c.d.name,
                      'targets':target_uids,'target_names':target_names}
        self.stack.append(spell_marker);self.spell_cast_epoch+=1
        self.log('stack_add',p.name,c.d.name,f'{c.d.name} on stack',
                 targets=target_uids,target_names=target_names)
        if autoresolve and stack_was_empty:
            self.start_priority_stack_autopass(
                p,detail=(
                    f'{c.d.name} was tagged autoresolve and was cast onto an empty stack; '
                    'the caster automatically passes when priority returns unless a new spell is cast'))
        self.wake_passes_for_opposing_spell_targets(p,c,target_values)
        if c.d.name=='Apex Devastator':
            for _ in range(4):self.cascade_once(p,10,'Apex Devastator')
        triggers=list(cost_triggers)
        ward_countered={'value':False}
        def add_trigger(controller,source,label,resolver):
            triggers.append({'controller':controller,'source':source,'label':label,'resolve':resolver})
        if c.d.name=='Hydroid Krasis':
            amount=x_value//2
            add_trigger(p,c.d.name,f'gain {amount} life and draw {amount} card(s)',
                        lambda amount=amount:(self.gain_life(p,amount,'Hydroid Krasis cast trigger'),self.draw(p,amount,'Hydroid Krasis cast trigger')))
        for target in announced.get('targets',[]):
            if not hasattr(target,'controller'):continue
            owner=self.players[target.controller]
            if owner is p or not self.has_ward_one(target):continue
            def resolve_ward(owner=owner,target=target):
                tax=sim.CardDef('Ward {1}','{1}','Ability','',1,p.name,1)
                can=self.can_pay(p,tax) is not None
                pay=self._request_decision('ward_payment',p,f'{target.name} has ward {{1}}. Pay it?',[True,False],lambda value:'pay ward' if value else 'do not pay') if can else False
                if pay:self.pay(p,tax)
                else:ward_countered['value']=True
            add_trigger(owner,target.name,'ward {1}: counter this spell unless its controller pays {1}',resolve_ward)
        for owner in self.players.values():
            fa=self.perm(owner,'Forgotten Ancient')
            if fa:add_trigger(owner,fa.name,'put a +1/+1 counter on Forgotten Ancient',lambda owner=owner,fa=fa:self.add_counters(owner,fa,'+1/+1',1,'Forgotten Ancient spell-cast trigger'))
            tm=self.perm(owner,'Taurean Mauler')
            if tm and owner.name!=p.name:add_trigger(owner,tm.name,'put a +1/+1 counter on Taurean Mauler',lambda owner=owner,tm=tm:self.add_counters(owner,tm,'+1/+1',1,'Taurean Mauler opponent spell trigger'))
            mh=self.perm(owner,'Managorger Hydra')
            if mh:add_trigger(owner,mh.name,'put a +1/+1 counter on Managorger Hydra',lambda owner=owner,mh=mh:self.add_counters(owner,mh,'+1/+1',1,'Managorger Hydra spell trigger'))
        defiler=self.perm(p,'Defiler of Vigor')
        if defiler and c.d.is_permanent and 'G' in __import__('re').findall(r'\{([WUBRG])\}',c.d.mana_cost.split(' // ')[0]):
            def resolve_defiler():
                for cr in [z for z in p.battlefield if self.is_creature_perm(z)]:self.add_counters(p,cr,'+1/+1',1,'Defiler of Vigor green permanent cast')
            add_trigger(p,defiler.name,'put a +1/+1 counter on each creature you control',resolve_defiler)
        splendor=self.perm(p,"Sigarda's Splendor")
        if splendor and 'W' in __import__('re').findall(r'\{([WUBRG])\}',c.d.mana_cost.split(' // ')[0]):
            add_trigger(p,splendor.name,'gain 1 life for casting a white spell',lambda:self.gain_life(p,1,"Sigarda's Splendor white spell"))
        pontiff=self.perm(p,'Pontiff of Blight')
        for permanent in list(p.battlefield):
            instances=[]
            if permanent.name in {'Pontiff of Blight','Sorin of House Markov'}:instances.append('printed extort')
            if pontiff and permanent.uid!=pontiff.uid and self.is_creature_perm(permanent):instances.append('Pontiff-granted extort')
            for instance in instances:
                def resolve_extort(permanent=permanent,instance=instance):
                    cost=sim.CardDef('Extort','{W/B}','Ability','',1,p.name,1)
                    if self.can_pay(p,cost) is None:return
                    pay=self._request_decision('extort_payment',p,f'{permanent.name} {instance}: pay {{W/B}}?',[True,False],lambda value:'pay extort' if value else 'decline')
                    if not pay:return
                    self.pay(p,cost);opponents=list(self.opponents(p))
                    for opponent in opponents:self.lose_life(opponent,1,'Extort')
                    self.gain_life(p,len(opponents),'Extort')
                add_trigger(p,permanent.name,f'{instance}: you may pay {{W/B}} to drain each opponent',resolve_extort)
        for owner in self.players.values():
            if owner.name==p.name or owner.eliminated:continue
            rhystic=self.perm(owner,'Rhystic Study')
            if rhystic:
                def resolve_rhystic(owner=owner):
                    tax=sim.CardDef('Rhystic Study tax','{1}','Ability','',1,p.name,1)
                    can=self.can_pay(p,tax) is not None
                    pay=self._request_decision('rhystic_tax',p,f'{owner.name} controls Rhystic Study. Pay {{1}} for {c.d.name}?',[True,False],lambda x:'pay {1}' if x else 'do not pay') if can else False
                    if pay:self.pay(p,tax)
                    else:self.draw(owner,1,'Rhystic Study opponent spell')
                add_trigger(owner,rhystic.name,f'draw unless {p.name} pays {{1}}',resolve_rhystic)
            remora=self.perm(owner,'Mystic Remora')
            if remora and not c.d.is_creature:
                def resolve_remora(owner=owner):
                    tax=sim.CardDef('Mystic Remora tax','{4}','Ability','',1,p.name,4)
                    can=self.can_pay(p,tax) is not None
                    pay=self._request_decision('remora_tax',p,f'{owner.name} controls Mystic Remora. Pay {{4}} for {c.d.name}?',[True,False],lambda x:'pay {4}' if x else 'do not pay') if can else False
                    if pay:self.pay(p,tax)
                    else:
                        draw=self._request_decision('remora_draw',owner,f'{p.name} did not pay for Mystic Remora. Draw a card?', [True,False],lambda x:'draw' if x else 'decline')
                        if draw:self.draw(owner,1,'Mystic Remora opponent noncreature spell')
                add_trigger(owner,remora.name,f'draw unless {p.name} pays {{4}}',resolve_remora)
        if any(source=='FLOAT:SUNKEN-U' for source in p.dungeon.get('last_payment_sources',[])):
            original_state=dict(announced);original_modes=dict(modes)
            add_trigger(p,'Sunken Palace',f'copy {c.d.name}',
                        lambda:self.resolve_sunken_spell_copy(p,c,x_value,original_state,original_modes))
        self.resolve_simultaneous_triggers(f'{c.d.name} cast',triggers,
                                           starter=self.players[self.turn_order[self.active_idx]])
        # A spell can be removed from the stack while its cast triggers are
        # resolving (for example by a queued Glen Elendra Archmage ability or
        # Summary Dismissal).  Finalize that physical card now and do not open
        # a stale second counterspell window for an object that no longer
        # exists on the stack.
        if spell_marker not in self.stack:
            if commander:
                p.command_tax+=2
                if not any(x.uid==c.uid for x in p.hand+p.graveyard+p.exile) and (not p.commander or p.commander.uid!=c.uid):
                    p.commander=c
                    self.log('commander_zone',p.name,c.d.name,
                             'Countered commander returned to command zone')
            elif not any(x.uid==c.uid for x in p.hand+p.graveyard+p.exile) and (not p.commander or p.commander.uid!=c.uid):
                p.graveyard.append(c)
                self.log('countered',p.name,c.d.name,
                         f'{c.d.name} countered → graveyard')
            else:
                self.log('countered_destination',p.name,c.d.name,
                         f'{c.d.name} left the stack; destination already established by the resolving effect')
            p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None)
            p.dungeon.get('announced_spells',{}).pop(c.uid,None)
            return True
        if ward_countered['value']:
            if spell_marker in self.stack:self.stack.remove(spell_marker)
            if commander:p.commander=c;p.command_tax+=2
            else:p.graveyard.append(c)
            p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None)
            p.dungeon.get('announced_spells',{}).pop(c.uid,None)
            self.log('countered',p.name,c.d.name,'Countered by ward')
            return True
        if self.react_to_spell(p,c):
            if spell_marker in self.stack:self.stack.remove(spell_marker)
            if commander:
                p.command_tax+=2
                if not any(x.uid==c.uid for x in p.hand+p.graveyard+p.exile) and (not p.commander or p.commander.uid!=c.uid):
                    p.commander=c;self.log('commander_zone',p.name,c.d.name,'Countered commander returned to command zone')
            else:
                # Remand already placed the exact physical spell card back in hand. Do not
                # also append it to graveyard after the response window closes.
                if not any(x.uid==c.uid for x in p.hand+p.graveyard+p.exile) and (not p.commander or p.commander.uid!=c.uid):
                    p.graveyard.append(c);self.log('countered',p.name,c.d.name,f'{c.d.name} countered → graveyard')
                else:
                    self.log('countered_destination',p.name,c.d.name,f'{c.d.name} countered; destination already established by counter effect')
            if c.d.is_instant or c.d.is_sorcery:self.mark_appearance(c.d.name,realized=True)
            p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None)
            p.dungeon.get('announced_spells',{}).pop(c.uid,None)
            return True
        self.priority_window(p,'spell response',{'spell_uid':c.uid,'spell_name':c.d.name})
        if spell_marker not in self.stack:
            p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None);return True
        self.stack.remove(spell_marker);self.log('resolve',p.name,c.d.name,f'{c.d.name} resolves')
        if counter_target is not None:
            target_caster,target_card=counter_target
            p.graveyard.append(c);self.mark_appearance(c.d.name,realized=True)
            self.resolve_counterspell_effect(p,c,target_caster,target_card)
            self.log('spell_to_graveyard',p.name,c.d.name,f'{c.d.name} finished resolving → graveyard',uid=c.uid)
            p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None)
            p.dungeon.get('announced_spells',{}).pop(c.uid,None)
            self.check_sba();self.check_ream_combo();return True
        if c.d.is_permanent:
            aura_state=p.dungeon.get('announced_spells',{}).get(c.uid,{})
            if 'Aura' in c.d.type_line and aura_state:
                legal=True
                if aura_state.get('target'):
                    owner,target=aura_state['target'];legal=self.target_still_legal(p,owner,target,True,c.d.name)
                elif aura_state.get('grave_target'):
                    owner,target=aura_state['grave_target'];legal=target in owner.graveyard
                if not legal:
                    p.graveyard.append(c);self.log('spell_fizzle',p.name,c.d.name,'Aura spell has no legal target and is put into its owner\'s graveyard')
                    p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None);p.dungeon.get('announced_spells',{}).pop(c.uid,None)
                    return True
            copy=self.request_body_double_copy(p) if c.d.name=='Body Double' else None
            generated=[];departures=[]
            self.__dict__.setdefault('_generated_trigger_frames',[]).append(generated)
            self.__dict__.setdefault('_ltb_trigger_frames',[]).append(departures)
            try:
                permanent=self._put_card_bf(p,c,'after resolving',copy_of=copy,x_value=x_value);self.check_sba()
            finally:
                self._ltb_trigger_frames.pop();self._generated_trigger_frames.pop()
            permanent.metadata.update(modes)
            if modes['necromancy_flash']:permanent.metadata['flash_cleanup_due']=self.turn_number
            if commander:p.command_tax+=2
            if departures or generated:self.resolve_simultaneous_triggers(
                f'after {c.d.name} permanent spell resolves',departures+generated,
                starter=self.players[self.turn_order[self.active_idx]])
        else:
            p.graveyard.append(c);self.mark_appearance(c.d.name,realized=True)
            p.dungeon['resolving_source_name']=c.d.name
            generated=[];departures=[]
            self.__dict__.setdefault('_generated_trigger_frames',[]).append(generated)
            self.__dict__.setdefault('_ltb_trigger_frames',[]).append(departures)
            try:
                self.resolve_spell(p,c,x_value=x_value);self.check_sba()
            finally:
                self._ltb_trigger_frames.pop();self._generated_trigger_frames.pop();p.dungeon.pop('resolving_source_name',None)
            self.log('spell_to_graveyard',p.name,c.d.name,f'{c.d.name} finished resolving → graveyard',uid=c.uid)
            if departures or generated:self.resolve_simultaneous_triggers(
                f'after {c.d.name} resolves',departures+generated,
                starter=self.players[self.turn_order[self.active_idx]])
        if p.name=='Reaminatour' and p.miracle_card_uid==c.uid:p.miracle_card_uid=None
        p.dungeon.get('resolving_cast_modes',{}).pop(c.uid,None)
        p.dungeon.get('announced_spells',{}).pop(c.uid,None)
        self.check_sba()
        self.check_ream_combo();return True

    def resolve_spell(self,p,c,x_value=0):
        state=self.announced_spell_state(p,c);name=c.d.name
        if name=='Summary Dismissal' and c.uid in self.__dict__.get('_summary_dismissal_ability_casts',set()):
            ability_markers=[item for item in list(self.stack) if isinstance(item,dict) and
                             (item.get('ability_kind') or item.get('trigger_event'))]
            spell_markers=[item for item in list(self.stack) if isinstance(item,dict) and
                           item.get('uid') and item.get('card') and item not in ability_markers]
            for marker in ability_markers:
                if marker in self.stack:self.stack.remove(marker)
            self.log('counter_abilities',p.name,name,
                     f'Countered {len(ability_markers)} triggered/activated ability object(s)')
            for marker in spell_markers:
                if marker not in self.stack:continue
                self.stack.remove(marker);owner=self.players[marker['actor']]
                definition=sim.CARDDEF.get(marker['card'])
                if definition is None:continue
                physical=sim.CardObj(marker['uid'],definition)
                if marker['card']==sim.COMMANDERS.get(owner.name):
                    owner.commander=physical
                    self.log('commander_zone',owner.name,marker['card'],
                             'Summary Dismissal exiled the commander spell; it returned to the command zone',uid=marker['uid'])
                else:
                    owner.exile.append(physical)
                    self.log('exile',owner.name,marker['card'],
                             'Summary Dismissal exiles the spell from the stack',uid=marker['uid'])
            return
        if name=='Blasphemous Act':
            victims=[
                (name,owner,permanent,13)
                for owner in self.players.values()
                for permanent in list(owner.battlefield)
                if self.is_creature_perm(permanent)
            ]
            self.log('mass_damage',p.name,name,
                     f'{name} deals 13 damage to each creature',count=len(victims))
            self.deal_damage_batch(p,victims,[],name)
            return
        if name=='Consider':
            if p.library:
                top=p.library[-1]
                self.mark_appearance(top.d.name)
                bin_card=self._request_decision(
                    'consider_surveil',p,
                    f'Consider: surveil 1. Keep {top.d.name} on top or put it into your graveyard?',
                    [False,True],
                    lambda value:f'bin {top.d.name}' if value else f'keep {top.d.name} on top')
                if bin_card:
                    p.library.pop();p.graveyard.append(top)
                    self.log('surveil_bin',p.name,top.d.name,'Consider surveil')
                else:
                    self.log('surveil_keep',p.name,top.d.name,'Consider surveil')
            self.draw(p,1,name)
            return
        if name in {'Bulk Up','Unleash Fury','Give In to Violence','Invigorating Surge','Ram Through',
                    'Moment of Craving','Deadly Riposte','Devouring Light','Beast Within','Chaos Warp','Pongify',
                    'Breathe Your Last','Utter End',"Hero's Downfall",'Murder','Valorous Stance','Death Grasp',
                    'Zombify','Restart Sequence','Fangs of Kalonia','Aggressive Biomancy','March from Velis Vel','Replication Technique',
                    'Return of the Wildspeaker'}:
            self.resolve_announced_spell(p,c,state,x_value)
            p.dungeon.get('announced_spells',{}).pop(c.uid,None)
            return
        if c.d.name=="Chandra's Ignition":
            uid=p.dungeon.pop('chandra_target_uid',None)
            target=self.find_card_obj_on_bf(p,uid) if uid else None
            if not target:
                self.log('spell_fizzle',p.name,c.d.name,"Chandra's Ignition has no legal target and does not resolve")
                return
            damage=self.effective_power(target)
            self.log('mass_damage',p.name,c.d.name,f'{target.name} deals {damage} to each other creature and opponent',target_uid=target.uid)
            creature_rows=[(target,owner,permanent,damage) for owner in self.players.values() for permanent in list(owner.battlefield)
                           if permanent.uid!=target.uid and self.is_creature_perm(permanent)]
            player_rows=[(target,opponent,damage) for opponent in self.opponents(p)]
            self.deal_damage_batch(p,creature_rows,player_rows,c.d.name)
            return
        if c.d.name in {'Fling',"Kazuul's Fury // Kazuul's Cliffs"}:
            damage=p.dungeon.pop('fling_damage',0);row=p.dungeon.pop('fling_target',None)
            if not row:return
            kind,owner,obj=row
            self.resolve_any_target_damage(p,row,damage,c.d.name)
            self.log('direct_damage',p.name,c.d.name,f'{c.d.name} deals {damage} to {obj.name}',target=obj.name,damage=damage)
            return
        if c.d.name=='Crop Rotation':
            lands=[card for card in p.library if card.d.is_land]
            if lands:
                choice=self._request_decision('crop_rotation_land',p,'Crop Rotation: choose a land card to put onto the battlefield.',lands,lambda card:f'{card.d.name} | {card.d.type_line}')
                p.library.remove(choice);land=self._put_card_bf(p,choice,'Crop Rotation');land.tapped=self.land_enters_tapped(p,choice)
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Crop Rotation')
            return
        if c.d.name=='Heroic Intervention':
            for q in p.battlefield:q.metadata['heroic_protected_turn']=self.turn_number
            self.log('protection',p.name,c.d.name,'Permanents you control gain hexproof and indestructible until end of turn')
            return
        if c.d.name=='Valorous Stance':
            own=[q for q in p.battlefield if self.is_creature_perm(q)]
            enemy=[(owner,q) for owner in self.opponents(p) for q in owner.battlefield
                   if self.is_creature_perm(q) and self.toughness(q)>=4 and not self.has_hexproof(q)]
            modes=(['protect'] if own else [])+(['destroy'] if enemy else [])
            mode=self._request_decision('valorous_mode',p,'Valorous Stance: choose a mode.',modes,lambda value:'give a creature indestructible' if value=='protect' else 'destroy a toughness-4-or-greater creature')
            if mode=='protect':
                target=self._request_decision('protection_target',p,'Choose creature to gain indestructible until end of turn.',own,lambda q:q.name)
                target.metadata['heroic_protected_turn']=self.turn_number
            else:
                owner,target=self._request_decision('removal_target',p,'Choose creature to destroy.',enemy,lambda row:f'{row[0].name}: {row[1].name}')
                self.destroy(owner,target,c.d.name)
            return
        if c.d.name=='Inspiring Call':
            creatures=[q for q in p.battlefield if self.is_creature_perm(q) and q.counters.get('+1/+1',0)>0]
            self.draw(p,len(creatures),c.d.name)
            for q in creatures:q.metadata['heroic_protected_turn']=self.turn_number
            return
        if c.d.name=='Return of the Wildspeaker':
            nonhumans=[q for q in p.battlefield if self.is_creature_perm(q) and (not sim.CARDDEF.get(q.name) or 'Human' not in sim.CARDDEF[q.name].type_line)]
            mode=self._request_decision('wildspeaker_mode',p,'Return of the Wildspeaker: choose a mode.',['draw','pump'],lambda value:'draw equal to greatest non-Human power' if value=='draw' else 'non-Humans get +3/+3')
            if mode=='draw':self.draw(p,max((self.effective_power(q) for q in nonhumans),default=0),c.d.name)
            else:
                for q in nonhumans:q.metadata['wildspeaker_bonus']=3
            return
        if c.d.name=='Give In to Violence':
            choices=[(owner,q) for owner in self.players.values() for q in owner.battlefield if self.is_creature_perm(q) and (owner is p or not self.has_hexproof(q))]
            owner,target=self._request_decision('pump_target',p,'Give In to Violence: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
            target.metadata['fixed_power_bonus']=target.metadata.get('fixed_power_bonus',0)+2
            target.metadata['fixed_toughness_bonus']=target.metadata.get('fixed_toughness_bonus',0)+2
            target.metadata['lifelink_turn']=self.turn_number;return
        if c.d.name in {'Moment of Craving','Deadly Riposte'}:
            choices=[(owner,q) for owner in self.opponents(p) for q in owner.battlefield if self.is_creature_perm(q) and not self.has_hexproof(q) and (c.d.name!='Deadly Riposte' or q.tapped)]
            owner,target=self._request_decision('damage_target',p,f'{c.d.name}: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name} {self.effective_power(row[1])}/{self.effective_toughness(row[1])}')
            if c.d.name=='Moment of Craving':
                target.metadata['fixed_power_bonus']=target.metadata.get('fixed_power_bonus',0)-2
                target.metadata['fixed_toughness_bonus']=target.metadata.get('fixed_toughness_bonus',0)-2
                self.gain_life(p,2,c.d.name);self.check_sba()
            else:
                if self.effective_toughness(target)<=3:self.destroy(owner,target,c.d.name+' lethal damage')
                self.gain_life(p,2,c.d.name)
            return
        if c.d.name=='Devouring Light':
            context=p.dungeon.get('cast_priority_context',{});ids=set(context.get('attackers',[]))
            for values in context.get('blocks',{}).values():ids.update(values)
            choices=[(owner,q) for owner in self.players.values() for q in owner.battlefield if q.uid in ids]
            owner,target=self._request_decision('combat_exile_target',p,'Devouring Light: choose target attacking or blocking creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
            self.exile_perm(owner,target,c.d.name);return
        if c.d.name=='Drown in Dreams':
            commander_present=self.controls_commander(p)
            modes=['draw','mill']+(['both'] if commander_present else [])
            mode=self._request_decision('drown_mode',p,'Drown in Dreams: choose mode'+('s' if commander_present else '')+'.',modes,lambda value:value)
            if mode in {'draw','both'}:
                target=self._request_decision('drown_draw_target',p,f'Choose player to draw {x_value}.',list(self.players.values()),lambda player:f'{player.name} hand={len(player.hand)} library={len(player.library)}')
                self.draw(target,x_value,c.d.name)
            if mode in {'mill','both'}:
                target=self._request_decision('drown_mill_target',p,f'Choose player to mill {2*x_value}.',list(self.players.values()),lambda player:f'{player.name} library={len(player.library)}')
                for _ in range(min(2*x_value,len(target.library))):target.graveyard.append(target.library.pop())
                self.log('mill',p.name,c.d.name,f'{target.name} mills {2*x_value}',target=target.name)
            return
        if c.d.name=='Eureka Moment':
            self.draw(p,2,c.d.name);self.extra_land_from_hand(p,c.d.name);return
        if c.d.name in {"Nature's Lore",'Three Visits','Farseek','Rampant Growth','Cultivate',"Kodama's Reach"}:
            name=c.d.name
            if name in {"Nature's Lore",'Three Visits'}:
                candidates=[card for card in p.library if card.d.is_land and 'Forest' in card.d.type_line]
                if candidates:
                    choice=self._request_decision('ramp_land',p,f'{name}: choose a Forest card to put onto the battlefield.',candidates,
                                                  lambda card:f'{card.d.name} | {card.d.type_line}')
                    tapped=self.land_enters_tapped(p,choice);p.library.remove(choice);land=self._put_card_bf(p,choice,name);land.tapped=False if self.perm(p,'Spelunking') else tapped
            elif name=='Farseek':
                candidates=[card for card in p.library if card.d.is_land and any(kind in card.d.type_line for kind in ['Plains','Island','Swamp','Mountain'])]
                if candidates:
                    choice=self._request_decision('ramp_land',p,'Farseek: choose a Plains, Island, Swamp, or Mountain card.',candidates,
                                                  lambda card:f'{card.d.name} | {card.d.type_line}')
                    p.library.remove(choice);land=self._put_card_bf(p,choice,name);land.tapped=True
            elif name=='Rampant Growth':
                candidates=[card for card in p.library if card.d.type_line.startswith('Basic Land')]
                if candidates:
                    choice=self._request_decision('ramp_land',p,'Rampant Growth: choose a basic land card.',candidates,lambda card:card.d.name)
                    p.library.remove(choice);land=self._put_card_bf(p,choice,name);land.tapped=True
            else:
                chosen=[]
                for slot in range(2):
                    candidates=[card for card in p.library if card.d.type_line.startswith('Basic Land') and card not in chosen]
                    if not candidates:break
                    choice=self._request_decision('ramp_land',p,f'{name}: choose basic land {slot+1} of 2.',candidates,lambda card:card.d.name)
                    chosen.append(choice);p.library.remove(choice)
                    if slot==0:
                        land=self._put_card_bf(p,choice,name);land.tapped=True
                    else:
                        p.hand.append(choice);self.log('tutor',p.name,choice.d.name,f'{name}: revealed basic land to hand',visibility='public')
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,f'Shuffle after {name}')
            return
        if c.d.name=='Evacuation':
            self.resolve_evacuation_refereed(p)
            return
        if c.d.name=='Whelming Wave':
            protected_types={'Kraken','Leviathan','Octopus','Serpent'}
            for owner in self.players.values():
                for permanent in list(owner.battlefield):
                    if self.is_creature_perm(permanent) and not any(
                        self.has_creature_type(permanent,creature_type)
                        for creature_type in protected_types
                    ):
                        self.bounce(owner,permanent,c.d.name)
            return
        if c.d.name=='Finale of Revelation':
            if c in p.graveyard:p.graveyard.remove(c)
            if x_value>=10:
                p.library.extend(p.graveyard);p.graveyard.clear();self.rng.shuffle(p.library)
                self.log('shuffle',p.name,c.d.name,'Finale shuffled graveyard into library')
                p.dungeon['no_max_hand']=True
            self.draw(p,min(max(0,x_value),40),c.d.name)
            if x_value>=10:
                if self.selection_batch_enabled():
                    tapped=[q for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land and q.tapped]
                    for land in self._request_selection('finale_untap_selection',p,'Finale of Revelation: choose up to five lands to untap.',tapped,
                            lambda q:f'{q.name} [{q.uid}]',maximum=5):land.tapped=False
                else:
                    for slot in range(5):
                        tapped=[q for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land and q.tapped]
                        if not tapped:break
                        land=self._request_decision('finale_untap',p,f'Finale of Revelation: choose land {slot+1} of up to five to untap, or stop.',tapped,lambda q:q.name,allow_pass=True)
                        if not land:break
                        land.tapped=False
            p.exile.append(c);self.log('exile',p.name,c.d.name,'Finale of Revelation exiles itself after resolving')
            return
        if c.d.name=='Curse of the Swine':
            exiled=[]
            for uid in p.dungeon.pop('curse_target_uids',[]):
                permanent=self.find_card_obj_on_bf(p,uid)
                if not permanent:
                    permanent=next((q for owner in self.players.values() for q in owner.battlefield if q.uid==uid),None)
                if permanent:
                    owner=self.players[permanent.controller]
                    # Revalidate every target on resolution.  A target can gain
                    # hexproof or protection after Curse was cast; both make it
                    # illegal and must prevent both exile and the Boar token.
                    if not self.target_still_legal(p,owner,permanent,True,c.d.name):continue
                    self.exile_perm(owner,permanent,'Curse of the Swine');exiled.append(owner)
            for owner in exiled:self.token(owner,'Boar',2,2)
            return
        if c.d.name=='Brainstorm':
            self.draw(p,3,'Brainstorm')
            if self.selection_batch_enabled():
                count=min(2,len(p.hand))
                selected=self._request_selection('brainstorm_putback_order',p,
                    f'Brainstorm: select {count} cards in bottom-to-top order; the last selected card will be drawn first.',p.hand,
                    lambda card:f'{card.d.name} [{card.uid}]',minimum=count,maximum=count,ordered=True)
            else:
                selected=[]
                for slot in range(min(2,len(p.hand))):
                    choice=self._request_decision('brainstorm_putback',p,
                        f'Brainstorm: choose putback {slot+1} of 2'+(' (this card will be the top card).' if slot==1 else ' (the next putback will be above it).'),
                        [card for card in p.hand if card not in selected],lambda card:f'{card.d.name} {card.d.mana_cost}')
                    selected.append(choice)
            for card in selected:
                p.hand.remove(card);p.library.append(card);self.log('put_on_top',p.name,card.d.name,'Brainstorm ordered putback')
            return
        if c.d.name=='Sylvan Scrying':
            lands=[card for card in p.library if card.d.is_land]
            if lands:
                choice=self._request_decision('sylvan_land',p,'Sylvan Scrying: choose a land card to put into your hand.',lands,lambda card:f'{card.d.name} | {card.d.type_line}')
                p.library.remove(choice);p.hand.append(choice);self.mark_appearance(choice.d.name);self.log('tutor',p.name,choice.d.name,'Sylvan Scrying',destination='hand',visibility='public')
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Sylvan Scrying')
            return
        if c.d.name=='Hour of Promise':
            for slot in range(2):
                lands=[card for card in p.library if card.d.is_land]
                if not lands:break
                choice=self._request_decision('hour_land',p,f'Hour of Promise: choose land {slot+1} to put onto the battlefield tapped, or stop.',lands,
                             lambda card:f'{card.d.name} | {card.d.type_line}',allow_pass=True)
                if not choice:break
                p.library.remove(choice);land=self._put_card_bf(p,choice,'Hour of Promise')
                land.tapped=not bool(self.perm(p,'Spelunking'))
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Hour of Promise')
            if sum(1 for land in p.battlefield if sim.land_has_type(land,'Desert',p))>=3:
                self.token(p,'Zombie',2,2);self.token(p,'Zombie',2,2)
            return
        if c.d.name=="Rishkar's Expertise":
            greatest=max((self.effective_power(q) for q in p.battlefield if self.is_creature_perm(q)),default=0)
            self.draw(p,min(greatest,40),c.d.name)
            legal=[card for card in p.hand if not card.d.is_land and card.d.mv<=5]
            choice=self._request_decision(
                'rishkars_expertise_cast',p,
                "Rishkar's Expertise: cast a mana-value-5-or-less spell from hand without paying its mana cost, or decline.",
                legal,lambda card:f'{card.d.name} {card.d.mana_cost}',allow_pass=True)
            if choice:self.cast(p,choice,free=True,x_value=0)
            return
        if c.d.name=='Replenish':
            enchantments=[card for card in list(p.graveyard) if card.d.is_enchantment]
            returning=[];aura_names={'Animate Dead','Dance of the Dead','Necromancy','Angelic Destiny','Fallen Ideal',
                                     'Darksteel Mutation','Changing Loyalty','Glasswing Grace // Age-Graced Chapel','Parasitic Impetus'}
            for card in enchantments:
                if 'Aura' not in card.d.type_line and card.d.name not in aura_names:
                    returning.append(card);continue
                state={'entered_without_cast':True}
                if card.d.name in {'Animate Dead','Dance of the Dead','Necromancy'}:
                    choices=[(owner,target) for owner in self.players.values() for target in owner.graveyard if target.d.is_creature]
                    chosen=self._request_decision('aura_entry_attachment',p,f'Replenish: choose a creature card for {card.d.name} to enchant.',choices,
                        lambda row:f'{row[0].name}: {row[1].d.name}') if choices else None
                    if not chosen:continue
                    state['grave_target']=chosen
                else:
                    choices=[(owner,target) for owner,target in self.all_creatures()
                             if not (self.source_colors(card) & self.continuous_view(target).rules.get('protection_colors',set()))]
                    chosen=self._request_decision('aura_entry_attachment',p,f'Replenish: choose a creature for {card.d.name} to enchant.',choices,
                        lambda row:f'{row[0].name}: {row[1].name}') if choices else None
                    if not chosen:continue
                    state['target']=chosen
                p.dungeon.setdefault('announced_spells',{})[card.uid]=state;returning.append(card)
            for card in returning:p.graveyard.remove(card)
            self.put_cards_bf_simultaneously(p,returning,'Replenish')
            for card in returning:p.dungeon.get('announced_spells',{}).pop(card.uid,None)
            return
        return super().resolve_spell(p,c,x_value=x_value)

    def resolve_sunken_spell_copy(self,p,original,x_value,original_state,modes):
        """Put Sunken Palace's spell copy on the stack without casting it."""
        copy=sim.CardObj(f'COPY-{original.uid}-{self.seq+1}',original.d)
        state=dict(original_state)
        if original_state.get('targets'):
            reselect=self._request_decision('sunken_copy_targets',p,
                f'Sunken Palace copies {original.d.name}. Choose whether to keep its targets or choose new targets.',
                [False,True],lambda value:'choose new targets' if value else 'keep the same targets')
            if reselect:
                prior=p.dungeon.setdefault('announced_spells',{}).get(copy.uid)
                state=self.announce_spell_choices(p,copy,x_value=x_value,overload=modes.get('overload',False))
                if prior is not None:p.dungeon['announced_spells'][copy.uid]=prior
        p.dungeon.setdefault('announced_spells',{})[copy.uid]=state
        p.dungeon.setdefault('resolving_cast_modes',{})[copy.uid]=dict(modes)
        marker={'actor':p.name,'uid':copy.uid,'card':original.d.name,'spell_copy':True}
        self.stack.append(marker);self.log('stack_add',p.name,'Sunken Palace',f'Copy of {original.d.name} on stack',uid=copy.uid)
        if self.react_to_spell(p,copy):
            if marker in self.stack:self.stack.remove(marker)
            self.log('copy_countered',p.name,original.d.name,'Sunken Palace copy was countered')
        else:
            self.priority_window(p,'Sunken Palace spell-copy response',{'spell_uid':copy.uid,'spell_name':copy.d.name,'copy':True})
            if marker in self.stack:
                self.stack.remove(marker);self.log('resolve',p.name,original.d.name,f'Copy of {original.d.name} resolves')
                if original.d.is_permanent:
                    base_power,base_toughness=sim.base_stats(original.d.name,original.d)
                    permanent=sim.Perm(copy.uid,original.d.name,p.name,p.name,False,True,{},None,None,True,
                                       base_power,base_toughness,set(sim.KEYWORDS.get(original.d.name,set())),self.turn_number)
                    p.battlefield.append(permanent);permanent.metadata.update(modes)
                    self.log('token_etb',p.name,original.d.name,f'Spell copy resolves as a token copy of {original.d.name}',uid=copy.uid)
                    self.on_etb(p,permanent,x_value=x_value)
                else:self.resolve_spell(p,copy,x_value=x_value)
        for zone_name in ('hand','graveyard','exile','library'):
            zone=getattr(p,zone_name)
            zone[:]=[card for card in zone if card.uid!=copy.uid]
        p.dungeon.get('announced_spells',{}).pop(copy.uid,None)
        p.dungeon.get('resolving_cast_modes',{}).pop(copy.uid,None)
        self.log('copy_ceases',p.name,original.d.name,'Sunken Palace spell copy ceases to exist')

    def resolve_announced_spell(self,p,c,state,x_value):
        name=c.d.name
        if not state:
            state=self.announce_spell_choices(p,c,x_value=x_value,
                                              overload=p.dungeon.get('resolving_cast_modes',{}).get(c.uid,{}).get('overload',False))
        if name in {'Bulk Up','Unleash Fury'}:
            owner,target=state['target']
            if self.target_still_legal(p,owner,target,True):
                bonus=self.effective_power(target);target.metadata['fixed_power_bonus']=target.metadata.get('fixed_power_bonus',0)+bonus
        elif name=='Give In to Violence':
            owner,target=state['target']
            if self.target_still_legal(p,owner,target,True):
                target.metadata['fixed_power_bonus']=target.metadata.get('fixed_power_bonus',0)+2
                target.metadata['fixed_toughness_bonus']=target.metadata.get('fixed_toughness_bonus',0)+2;target.metadata['lifelink_turn']=self.turn_number
        elif name=='Invigorating Surge':
            owner,target=state['target']
            if self.target_still_legal(p,owner,target,True):
                self.add_counters(p,target,'+1/+1',1,name)
                current=target.counters.get('+1/+1',0)
                if current:self.add_counters(p,target,'+1/+1',current,name+' double')
        elif name=='Ram Through':
            own=state['own'];enemy_owner,enemy=state['enemy']
            if own not in p.battlefield or not self.target_still_legal(p,enemy_owner,enemy,True):return
            damage=self.effective_power(own)
            lethal=(1 if 'deathtouch' in self.keywords_for(own) else
                    max(0,self.effective_toughness(enemy)-enemy.metadata.get('damage_marked',0)))
            excess=max(0,damage-lethal) if 'trample' in self.keywords_for(own) else 0
            dealt_to_creature=damage-excess
            self.deal_damage_batch(p,[(own,enemy_owner,enemy,dealt_to_creature)],
                                   [(own,enemy_owner,excess)] if excess else [],name)
        elif name in {'Moment of Craving','Deadly Riposte'}:
            owner,target=state['target']
            if not self.target_still_legal(p,owner,target,True):return
            if name=='Moment of Craving':
                target.metadata['fixed_power_bonus']=target.metadata.get('fixed_power_bonus',0)-2;target.metadata['fixed_toughness_bonus']=target.metadata.get('fixed_toughness_bonus',0)-2
            else:
                self.deal_damage_batch(p,[(name,owner,target,3)],[],name)
            self.gain_life(p,2,name);self.check_sba()
        elif name=='Devouring Light':
            owner,target=state['target']
            if self.target_still_legal(p,owner,target,True):self.exile_perm(owner,target,name)
        elif name=='Return of the Wildspeaker':
            nonhumans=[q for q in p.battlefield if self.is_creature_perm(q) and
                       (not sim.CARDDEF.get(q.name) or 'Human' not in sim.CARDDEF[q.name].type_line)]
            if state['mode']=='draw':self.draw(p,max((self.effective_power(q) for q in nonhumans),default=0),name)
            else:
                for creature in nonhumans:creature.metadata['wildspeaker_bonus']=3
        elif name in {'Beast Within','Chaos Warp','Pongify','Breathe Your Last','Utter End',"Hero's Downfall",'Murder'}:
            owner,target=state['target']
            if not self.target_still_legal(p,owner,target,creature=name in {'Pongify','Murder'}):return
            if name=='Chaos Warp':
                physical_owner=self.players[target.owner];self.leave_battlefield(owner,target,'library',name)
                self.rng.shuffle(physical_owner.library);self.log('shuffle',physical_owner.name,None,'Chaos Warp')
                if physical_owner.library:
                    top=physical_owner.library[-1];self.log('reveal',physical_owner.name,top.d.name,'Chaos Warp reveals top card')
                    if top.d.is_permanent:
                        physical_owner.library.pop();self._put_card_bf(physical_owner,top,'Chaos Warp')
            elif name=='Utter End':self.exile_perm(owner,target,name)
            else:
                colors=set(__import__('re').findall(r'\{([WUBRG])\}',sim.CARDDEF.get(target.name).mana_cost if sim.CARDDEF.get(target.name) else ''))|set(target.metadata.get('colors',[]))
                destroyed=self.destroy(owner,target,name)
                if name=='Beast Within':self.token(owner,'Beast',3,3)
                elif name=='Pongify':self.token(owner,'Ape',3,3)
                elif name=='Breathe Your Last':self.gain_life(p,len(colors),name)
        elif name=='Valorous Stance':
            owner,target=state['target']
            if not self.target_still_legal(p,owner,target,True):return
            if state['mode']=='protect':target.metadata['heroic_protected_turn']=self.turn_number
            elif self.toughness(target)>=4:self.destroy(owner,target,name)
        elif name=='Death Grasp':
            self.resolve_any_target_damage(p,state['target'],x_value,name);self.gain_life(p,x_value,name)
        elif name in {'Zombify','Restart Sequence'}:
            target=state['grave_target']
            if target in p.graveyard:p.graveyard.remove(target);self._put_card_bf(p,target,name)
        elif name=='Fangs of Kalonia':
            modes=p.dungeon.get('resolving_cast_modes',{}).get(c.uid,{})
            creatures=[q for q in p.battlefield if self.is_creature_perm(q)] if modes.get('overload') else [state['target'][1]]
            affected=[]
            for creature in creatures:
                if creature in p.battlefield:
                    before=creature.counters.get('+1/+1',0);placed=self.add_counters(p,creature,'+1/+1',1,name)
                    if placed:affected.append(creature)
            for creature in affected:
                current=creature.counters.get('+1/+1',0)
                if current:self.add_counters(p,creature,'+1/+1',current,name+' double')
        elif name=='Aggressive Biomancy':
            owner,target=state['target']
            if not self.target_still_legal(p,owner,target,True):return
            for _ in range(x_value):self.create_copiable_token(p,target,haste=False,fight=True)
        elif name=='March from Velis Vel':
            owner,target=state['target']
            if not self.target_still_legal(p,owner,target,True):return
            types=sorted({subtype for land in p.battlefield if sim.is_land_permanent(land) for subtype in self.nonbasic_land_types(land)})
            if not types:return
            chosen=self._request_decision('march_land_type',p,'March from Velis Vel: choose a nonbasic land type.',types,lambda value:value)
            for land in [land for land in p.battlefield if chosen in self.nonbasic_land_types(land)]:
                land.metadata.update({'march_copy':target.copy_of or target.name,'march_power':self.power(target),'march_toughness':self.toughness(target),'march_keywords':list(self.keywords_for(target)),'march_animated':True})
        elif name=='Replication Technique':
            owner,target=state['target']
            if target in p.battlefield:self.create_copiable_token(p,target)

    def nonbasic_land_types(self,land):
        definition=sim.CARDDEF.get(land.copy_of or land.name)
        if not definition or '—' not in definition.type_line:return set()
        return {part for part in definition.type_line.split('—',1)[1].strip().split() if part not in {'Plains','Island','Swamp','Mountain','Forest'}}

    def create_copiable_token(self,p,target,haste=False,fight=False,nonlegendary=False):
        effective=target.copy_of or target.name;definition=sim.CARDDEF.get(effective)
        uid=f'TOK-{self.game_no}-{self.seq+1}-{effective}'
        base_power,base_toughness=sim.base_stats(effective,definition)
        keywords=set(sim.KEYWORDS.get(effective,set()))
        if definition is None:
            # Ad-hoc creature tokens (for example the modeled 2/2 Zombie)
            # have no catalog definition, but their token-defining base stats
            # and keywords are still copiable values.
            base_power,base_toughness=target.base_power,target.base_toughness
            keywords=set(target.keywords)
        token=sim.Perm(uid,effective,p.name,p.name,False,True,{},None,effective,True,
                       base_power,base_toughness,keywords,self.turn_number)
        if nonlegendary or target.metadata.get('nonlegendary'):token.metadata['nonlegendary']=True
        if haste:token.keywords.add('haste')
        p.battlefield.append(token);self.log('token_etb',p.name,effective,f'Created a token copy of {effective}',uid=uid)
        self.on_etb(p,token)
        if effective=='Boo':self.check_boo_legend_rule(p,token)
        if fight:
            choices=[(owner,q) for owner in self.opponents(p) for q in owner.battlefield if self.is_creature_perm(q) and not self.has_hexproof(q)]
            chosen=self._request_decision('biomancy_fight_target',p,f'{effective} token: choose up to one target creature to fight.',choices,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if choices else None
            if chosen:
                owner,enemy=chosen;own_damage=self.effective_power(token);back=self.effective_power(enemy)
                self.deal_damage_batch(p,[(token,owner,enemy,own_damage),(enemy,p,token,back)],[],'Aggressive Biomancy fight')
        return token

    def resolve_evacuation_refereed(self,p):
        creatures=[(owner,q) for owner in self.players.values() for q in list(owner.battlefield) if self.is_creature_perm(q)]
        commander_choices={}
        for owner,q in creatures:
            if q.uid==owner.dungeon.get('commander_uid'):
                commander_choices[q.uid]=self._request_decision('evacuation_commander_zone',owner,
                    f'Evacuation would return {q.name} to your hand. Put it in the command zone instead?',
                    [False,True],lambda value:'return to hand' if not value else 'put in command zone')
        generated=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(generated)
        try:
            for owner,q in creatures:
                if q not in owner.battlefield:continue
                self.leave_battlefield(owner,q,'hand','Evacuation')
                if commander_choices.get(q.uid):
                    card=next((card for card in owner.hand if card.uid==q.uid),None)
                    if card:
                        owner.hand.remove(card);owner.commander=card;self.log('commander_zone',owner.name,q.name,'Evacuation commander-zone replacement')
        finally:self._ltb_trigger_frames.pop()
        if generated:self.resolve_simultaneous_triggers('Evacuation leave-the-battlefield triggers',generated,starter=p)
        for owner in self.players.values():owner.dungeon.pop('infinite_spirits_turn',None)
        self.log('global_bounce',p.name,'Evacuation',f'Returned {len(creatures)} creatures; creature tokens and the established Spirit army ceased to exist')

    # ---------- declarative activated-ability discovery ----------
    TAP_ACTIONS={
        'hall_heliod','urza_saga_construct','wolf_run','rogues_passage','shattered_spire_counter',
        'earth_crystal_distribute','lazotep_copy','sunken_palace','basilisk_gate','hashep_green',
        'hashep_pump','volatile_fault','blast_zone_counters','blast_zone_destroy','horizon_mana',
        'horizon_land','horizon_draw','wonderscape_sage','magus_candelabra','urzas_cave',
        'trenchpost','lotus_blossom_mana','trading_post_life','trading_post_goat',
        'trading_post_recur','trading_post_draw','mikaeus_self','mikaeus_team',
        'loran_draw','expedition_map','mazes_end','mind_stone_draw','silent_clearing_draw',
        'pristine_talisman_mana',
    }
    CREATURE_TAP_ACTIONS={'wonderscape_sage','magus_candelabra','mikaeus_self','mikaeus_team','loran_draw'}
    LOYALTY_ACTIONS={
        'aminatou_plus','aminatou_minus','aminatou_ultimate','nissa_plus','nissa_zero','nissa_ultimate',
        'sorin_house_plus','sorin_house_minus','sorin_house_ultimate','minsc_plus','minsc_minus',
        'sorin_vengeful_plus','sorin_vengeful_minus',
    }

    def ability_cost(self,name,cost):
        return sim.CardDef(name,cost,'Ability','',1,'',sim.mana_value(cost))

    def can_pay_ability(self,p,cost,source=None,tap=False):
        was_tapped=None
        if source is not None and tap:
            if source.tapped:return False
            was_tapped=source.tapped;source.tapped=True
        try:return self.can_pay(p,self.ability_cost('activated ability',cost)) is not None
        finally:
            if was_tapped is not None:source.tapped=was_tapped

    def all_permanents(self):
        return [(owner,q) for owner in self.players.values() for q in owner.battlefield]

    def all_creatures(self):
        return [(owner,q) for owner,q in self.all_permanents() if self.is_creature_perm(q)]

    def source_ready_for_registered_action(self,p,source,kind):
        if kind in self.TAP_ACTIONS and source.tapped:return False
        if kind in self.CREATURE_TAP_ACTIONS and source.summoning_sick:return False
        return True

    def registered_action_is_legal(self,p,source,registration):
        kind=registration.kind
        source_name=source.name if hasattr(source,'name') else source.d.name
        def legal_target(owner,target,creature=False):return self.target_still_legal(p,owner,target,creature,source_name)
        if registration.zone=='graveyard':
            return (kind=='ramunap_land' and self.perm(p,'Ramunap Excavator') is not None and
                    source in p.graveyard and source.d.is_land and p.land_plays_used<p.land_play_limit)
        if registration.zone=='hand':
            if source not in p.hand:return False
            if kind=='talon_from_hand':return self.can_pay_ability(p,'{4}')
            if kind=='channel_touch':
                return self.can_pay_ability(p,'{1}{W}') and any(
                    ((sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact) or self.is_creature_perm(q)) and
                    legal_target(owner,q) for owner,q in self.all_permanents())
            legends=sum(1 for q in p.battlefield if sim.CARDDEF.get(q.name) and 'Legendary' in sim.CARDDEF[q.name].type_line and self.is_creature_perm(q))
            if kind=='channel_otawara':
                cost=f'{{{max(0,3-legends)}}}{{U}}'
                return self.can_pay_ability(p,cost) and any(
                    ((sim.CARDDEF.get(q.name) and (sim.CARDDEF[q.name].is_artifact or sim.CARDDEF[q.name].is_enchantment)) or self.is_creature_perm(q) or self.is_planeswalker_perm(q))
                    and legal_target(owner,q) for owner,q in self.all_permanents())
            if kind=='channel_eiganjo':
                cost=f'{{{max(0,2-legends)}}}{{W}}'
                combat_ids=set(p.dungeon.get('cast_priority_context',{}).get('attackers',[]))
                for values in p.dungeon.get('cast_priority_context',{}).get('blocks',{}).values():combat_ids.update(values)
                return self.can_pay_ability(p,cost) and any(q.uid in combat_ids for _,q in self.all_creatures())
            return False
        if source not in p.battlefield or not self.source_ready_for_registered_action(p,source,kind):return False
        if kind in self.LOYALTY_ACTIONS:
            if source.metadata.get('activated_turn')==self.turn_number:return False
            loyalty=source.counters.get('loyalty',0)
            if kind.endswith('ultimate') and loyalty<6:return False
            if kind in {'aminatou_minus','sorin_house_minus'} and loyalty<1:return False
            if kind=='sorin_vengeful_minus':return any(
                card.d.is_creature and card.d.mv<=loyalty for card in p.graveyard)
            if kind=='minsc_minus' and loyalty<2:return False
            if kind.startswith('sorin_house_') and not source.metadata.get('transformed_sorin'):return False
            if kind=='aminatou_minus':return any(q.uid!=source.uid and q.owner==p.name for _,q in self.all_permanents())
            if kind=='nissa_ultimate':return loyalty>=6 and bool([q for q in p.battlefield if sim.is_land_permanent(q)])
            if kind=='sorin_house_minus':return bool(self.death_grasp_targets(p))
            if kind=='sorin_house_ultimate':return loyalty>=6 and any(legal_target(op,q,True) for op in self.opponents(p) for q in op.battlefield)
            if kind=='minsc_plus':return True
            if kind=='minsc_minus':return any(self.is_creature_perm(q) for q in p.battlefield)
            return True
        if kind in {'equip_boots','equip_helm','equip_armor'}:
            costs={'equip_boots':'{1}','equip_helm':'{5}','equip_armor':'{3}{W}'}
            return self.can_pay_ability(p,costs[kind]) and any(legal_target(p,q,True) for q in p.battlefield)
        if kind=='innkeeper_level2':return source.metadata.get('level',1)==1 and self.can_pay_ability(p,'{G}')
        if kind=='innkeeper_level3':return source.metadata.get('level',1)==2 and self.can_pay_ability(p,'{3}{G}')
        if kind=='unlock_awakening_hall':return not source.metadata.get('awakening_unlocked') and self.can_pay_ability(p,'{6}{B}{B}')
        if kind=='sakura_tribe':return any(c.d.type_line.startswith('Basic Land') for c in p.library)
        if kind=='wolf_run':return self.can_pay_ability(p,'{R}{G}',source,True) and any(legal_target(owner,q,True) for owner,q in self.all_creatures())
        if kind=='rogues_passage':return self.can_pay_ability(p,'{4}',source,True) and any(legal_target(owner,q,True) for owner,q in self.all_creatures())
        if kind=='hall_heliod':return self.can_pay_ability(p,'{1}{W}',source,True) and any(c.d.is_enchantment for c in p.graveyard)
        if kind=='urza_saga_construct':return source.metadata.get('saga_chapter',source.counters.get('lore',0))>=2 and self.can_pay_ability(p,'{2}',source,True)
        if kind=='shattered_spire_counter':return self.can_pay_ability(p,'{1}{G}',source,True) and any(self.is_creature_perm(q) or (sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact) for q in p.battlefield)
        if kind=='earth_crystal_distribute':return self.can_pay_ability(p,'{4}{G}{G}',source,True) and any(self.is_creature_perm(q) for q in p.battlefield)
        if kind=='lazotep_copy':return any(c.d.is_creature for c in p.graveyard) and any(sim.land_has_type(q,'Desert',p) for q in p.battlefield)
        if kind=='sunken_palace':return len(p.graveyard)>=7 and self.can_pay_ability(p,'{1}{U}',source,True)
        if kind=='mirage_mirror':return self.can_pay_ability(p,'{2}') and any(q.uid!=source.uid and legal_target(owner,q) for owner,q in self.all_permanents())
        if kind=='basilisk_gate':return self.can_pay_ability(p,'{2}',source,True) and any(legal_target(owner,q,True) for owner,q in self.all_creatures())
        if kind=='hashep_green':return p.life>1
        if kind=='hashep_pump':return self.can_pay_ability(p,'{1}{G}{G}',source,True) and any(sim.land_has_type(q,'Desert',p) for q in p.battlefield) and any(self.is_creature_perm(q) for q in p.battlefield)
        if kind=='volatile_fault':return self.can_pay_ability(p,'{1}',source,True) and any(sim.is_land_permanent(q) and q.name not in {'Plains','Island','Swamp','Mountain','Forest'} for op in self.opponents(p) for q in op.battlefield)
        if kind=='blast_zone_counters':return not source.tapped
        if kind=='blast_zone_destroy':return self.can_pay_ability(p,'{3}',source,True)
        if kind=='horizon_mana':return p.life>1 and any(sim.is_land_permanent(q) and q.uid!=source.uid and sim.land_colors(p,q) for q in p.battlefield)
        if kind=='horizon_land':return self.can_pay_ability(p,'{3}',source,True) and any(c.d.is_land for c in p.hand)
        if kind=='horizon_draw':return self.can_pay_ability(p,'{1}',source,True)
        if kind=='wonderscape_sage':return any(sim.is_land_permanent(q) for q in p.battlefield)
        if kind=='animate_lumbering':return self.can_pay_ability(p,'{2}{G}{U}')
        if kind=='magus_candelabra':return any(q.tapped and sim.is_land_permanent(q) for q in p.battlefield)
        if kind=='urzas_cave':return self.can_pay_ability(p,'{3}',source,True) and any(c.d.is_land for c in p.library)
        if kind=='trenchpost':return self.can_pay_ability(p,'{3}',source,True) and bool([x for x in self.players.values() if not x.eliminated])
        if kind=='lotus_blossom_mana':return source.counters.get('petal',0)>0
        if kind=='pristine_talisman_mana':return True
        if kind.startswith('trading_post_'):
            if not self.can_pay_ability(p,'{1}',source,True):return False
            if kind=='trading_post_life':return bool(p.hand)
            if kind=='trading_post_goat':return p.life>1
            if kind=='trading_post_recur':return any(self.is_creature_perm(q) for q in p.battlefield) and any(c.d.is_artifact for c in p.graveyard)
            if kind=='trading_post_draw':return any(sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact for q in p.battlefield)
        if kind=='mikaeus_self':return True
        if kind=='mikaeus_team':return source.counters.get('+1/+1',0)>0 and any(self.is_creature_perm(q) and q.uid!=source.uid for q in p.battlefield)
        if kind in {'animate_fortress'}:return self.can_pay_ability(p,'{2}{W}{B}')
        if kind=='alseid_protection':return self.can_pay_ability(p,'{1}') and any(
            self.is_creature_perm(q) or (sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_enchantment)
            for q in p.battlefield)
        if kind=='glen_counter':
            if not self.can_pay_ability(p,'{U}'):return False
            return any(item.get('actor')!=p.name and sim.CARDDEF.get(item.get('card')) and
                       not sim.CARDDEF[item['card']].is_creature for item in self.stack if isinstance(item,dict))
        if kind=='omen_scry':return self.can_pay_ability(p,'{2}{U}')
        if kind=='splendor_draw':return self.can_pay_ability(p,'{2}{W}') and sum(not player.eliminated for player in self.players.values())>=2
        if kind=='loran_draw':return bool(self.opponents(p))
        if kind=='expedition_map':return self.can_pay_ability(p,'{2}',source,True) and any(card.d.is_land for card in p.library)
        if kind=='mazes_end':return self.can_pay_ability(p,'{3}',source,True) and any('Gate' in card.d.type_line for card in p.library)
        if kind=='dawn_soldier':return self.can_pay_ability(p,'{3}{W}')
        if kind=='midnight_snack':return self.can_pay_ability(p,'{2}{B}') and bool(self.opponents(p))
        if kind in {'mind_stone_draw','silent_clearing_draw'}:return self.can_pay_ability(p,'{1}',source,True)
        return False

    def registered_actions(self,p,timing):
        actions=[]
        include_priority=timing=='priority';include_sorcery=timing=='sorcery';include_land=timing=='land_play'
        if timing in {'sorcery','priority'}:
            for source in p.battlefield:
                # Copy effects replace the permanent's copiable rules text.
                # Discover actions from the copied identity, not the physical
                # card name, so a Mirage Mirror copy does not retain Mirror's
                # printed activation until end of turn.
                identities=[source.copy_of or source.name]
                if source.name=="Thespian's Stage" and source.copy_of:
                    identities.append(source.name)
                for identity_name in identities:
                    for registration in registrations_for(identity_name,'battlefield',include_sorcery,include_priority,False):
                        if self.registered_action_is_legal(p,source,registration):
                            actions.append((registration.kind,source,{'ability_label':registration.label}))
            for card in p.hand:
                for registration in registrations_for(card.d.name,'hand',include_sorcery,include_priority,False):
                    if self.registered_action_is_legal(p,card,registration):
                        actions.append((registration.kind,card,{'ability_label':registration.label}))
        if timing in {'sorcery','land_play'} and self.perm(p,'Ramunap Excavator'):
            for card in p.graveyard:
                for registration in registrations_for('Ramunap Excavator','graveyard',False,False,True):
                    if self.registered_action_is_legal(p,card,registration):
                        actions.append((registration.kind,card,{'ability_label':registration.label}))
        return actions

    def pay_registered_cost(self,p,source,cost='',tap=False,sacrifice_source=False,life=0):
        if source is not None and tap:
            if source.tapped:return False
            source.tapped=True
        avoid_source=(source if source is not None and getattr(source,'name',None)=='Lumbering Falls'
                      and not tap and not sacrifice_source else None)
        if cost and not self.pay(p,self.ability_cost(f'{source.name if hasattr(source,"name") else "card"} activation',cost),
                                 avoid_source=avoid_source):
            if source is not None and tap:source.tapped=False
            return False
        if life:
            if p.life<=life:
                if source is not None and tap:source.tapped=False
                return False
            self.lose_life(p,life,f'{source.name} activation cost')
        if sacrifice_source and source in p.battlefield:
            self.leave_battlefield(p,source,'graveyard',f'{source.name} activation cost')
        return True

    @resolution_sequence
    def put_registered_stack_item(self,p,source,label,resolver,targets=None,cost_triggers=None,copy_factory=None):
        # The activation's targets are now fixed. Its targeting-specific
        # rationale policy must not leak into nested priority decisions.
        self.__dict__.pop('_activated_ability_decision_root',None)
        sunken_copy=any(payment_source=='FLOAT:SUNKEN-U' for payment_source in p.dungeon.get('last_payment_sources',[]))
        marker={'actor':p.name,'card':source.name if hasattr(source,'name') else source.d.name,
                'ability_kind':'registered','ability_label':label,
                'target_uids':[q.uid for q in (targets or []) if hasattr(q,'uid')]}
        self.stack.append(marker)
        self.log('stack_add',p.name,marker['card'],label,targets=marker['target_uids'])
        # Triggers created while paying an activation cost wait until the
        # activation is complete, then are put on the stack above that ability.
        if cost_triggers:
            self.resolve_simultaneous_triggers(f'{marker["card"]} activation-cost triggers',cost_triggers,
                                               starter=self.players[self.turn_order[self.active_idx]])
            if marker not in self.stack:return False
        if self.resolve_ward_triggers(p,marker,targets or []):
            self.log('ability_countered',p.name,marker['card'],'Countered by ward');return False
        if sunken_copy and marker in self.stack:
            self.resolve_simultaneous_triggers('Sunken Palace delayed trigger',[{
                'controller':p,'source':'Sunken Palace','label':f'copy {label}',
                'resolve':lambda:self.resolve_sunken_ability_copy(p,source,label,resolver,targets or [],copy_factory),
            }],starter=self.players[self.turn_order[self.active_idx]])
            if marker not in self.stack:return False
        if self.react_to_abilities(p):return False
        self.priority_window(p,f'{marker["card"]} activated ability response',{'ability':label,'targets':marker['target_uids']})
        if marker not in self.stack:
            self.log('ability_countered',p.name,marker['card'],label);return False
        self.stack.remove(marker)
        self.log('ability_resolve',p.name,marker['card'],label)
        p.dungeon['resolving_source_name']=marker['card']
        generated=[];departures=[]
        self.__dict__.setdefault('_generated_trigger_frames',[]).append(generated)
        self.__dict__.setdefault('_ltb_trigger_frames',[]).append(departures)
        try:
            resolver();self.check_sba()
        finally:
            self._ltb_trigger_frames.pop();self._generated_trigger_frames.pop();p.dungeon.pop('resolving_source_name',None)
        if departures or generated:self.resolve_simultaneous_triggers(
            f'after {marker["card"]} activated ability resolves',departures+generated,
            starter=self.players[self.turn_order[self.active_idx]])
        self.check_ream_combo();return True

    def pay_legacy_activation_cost(self,cost_action):
        """Run a legacy cost atomically and collect triggers it creates.

        This is the migration bridge for the few historical bespoke actions.
        The activation is put on the stack first, then these cost-created
        triggers are placed above it by ``put_registered_stack_item``.
        """
        cost_triggers=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(cost_triggers)
        try:paid=cost_action()
        finally:self._ltb_trigger_frames.pop()
        return paid,cost_triggers

    def _sunken_retarget_candidates(self,p,source,target):
        if isinstance(target,sim.PlayerState):return [player for player in self.players.values() if not player.eliminated]
        if not hasattr(target,'uid'):return [target]
        if any(target in getattr(owner,zone) for owner in self.players.values() for zone in ('graveyard','exile')):
            candidates=[]
            definition=target.d if hasattr(target,'d') else None
            for owner in self.players.values():
                for zone in ('graveyard','exile'):
                    for card in getattr(owner,zone):
                        if not definition or ((not definition.is_creature or card.d.is_creature) and
                           (not definition.is_artifact or card.d.is_artifact) and
                           (not definition.is_enchantment or card.d.is_enchantment)):candidates.append(card)
            return candidates
        rows=[]
        for owner,permanent in self.all_permanents():
            same_kind=(self.is_creature_perm(target)==self.is_creature_perm(permanent) and
                       sim.is_land_permanent(target)==sim.is_land_permanent(permanent) and
                       self.is_planeswalker_perm(target)==self.is_planeswalker_perm(permanent))
            if same_kind and self.target_still_legal(p,owner,permanent,source_name=source.name if hasattr(source,'name') else source.d.name):rows.append(permanent)
        return rows

    def _retarget_payload(self,payload,old_targets,new_targets):
        mapping={id(old):new for old,new in zip(old_targets,new_targets)}
        def replace(value):
            if id(value) in mapping:return mapping[id(value)]
            if isinstance(value,list):return [replace(item) for item in value]
            if isinstance(value,tuple):return tuple(replace(item) for item in value)
            if isinstance(value,dict):return {key:replace(item) for key,item in value.items()}
            return value
        result=replace(payload)
        if isinstance(result,dict) and result.get('target') is not None:
            target=result['target']
            permanent=target[-1] if isinstance(target,tuple) else target
            if hasattr(permanent,'controller') and 'owner' in result:result['owner']=self.players[permanent.controller]
            if isinstance(target,tuple) and len(target)>=3 and hasattr(target[-1],'controller'):
                result['target']=(target[0],self.players[target[-1].controller],target[-1])
        return result

    def resolve_sunken_ability_copy(self,p,source,label,resolver,targets,copy_factory=None):
        copy_targets=list(targets);copy_resolver=resolver
        if targets and copy_factory:
            change=self._request_decision('sunken_copy_ability_targets',p,
                f'Sunken Palace copies {label}. Choose whether to keep its targets or choose new targets.',
                [False,True],lambda value:'choose new targets' if value else 'keep the same targets')
            if change:
                copy_targets=[]
                for index,target in enumerate(targets):
                    candidates=self._sunken_retarget_candidates(p,source,target)
                    chosen=self._request_decision('sunken_copy_ability_target',p,
                        f'Sunken Palace copy: choose new target {index+1} of {len(targets)}.',candidates,
                        lambda candidate:getattr(candidate,'name',getattr(getattr(candidate,'d',None),'name',str(candidate))))
                    copy_targets.append(chosen)
                copy_resolver=copy_factory(copy_targets)
        marker={'actor':p.name,'card':source.name if hasattr(source,'name') else source.d.name,
                'ability_kind':'copy','ability_label':label,'target_uids':[q.uid for q in copy_targets if hasattr(q,'uid')]}
        self.stack.append(marker);self.log('stack_add',p.name,'Sunken Palace',f'Copy of {label} on stack',targets=marker['target_uids'])
        self.log('copy_targets',p.name,'Sunken Palace','Ability-copy targets locked',targets=marker['target_uids'])
        if self.resolve_ward_triggers(p,marker,copy_targets):return False
        if self.react_to_abilities(p):return False
        self.priority_window(p,'Sunken Palace ability-copy response',{'ability':label,'targets':marker['target_uids'],'copy':True})
        if marker not in self.stack:return False
        self.stack.remove(marker);self.log('ability_resolve',p.name,'Sunken Palace',f'Copy of {label} resolves')
        copy_resolver();self.check_sba();return True

    def react_to_abilities(self,starter):
        """Offer Summary Dismissal against triggered/activated abilities.

        Ordinary counterspells cannot counter abilities.  Summary Dismissal is
        the one card in this pod that can, and it counters every ability
        currently represented on the stack in one action.
        """
        ability_markers=[item for item in self.stack if isinstance(item,dict) and
                         (item.get('ability_kind') or item.get('trigger_event'))]
        if not ability_markers:return False
        start=self.turn_order.index(starter.name)
        responders=[self.players[self.turn_order[(start+offset)%len(self.turn_order)]]
                    for offset in range(len(self.turn_order))]
        for responder_index,responder in enumerate(responders):
            if responder.eliminated:continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.active_priority_seat_snooze(responder,'ability response'):
                self.log('priority_seat_snooze_auto',responder.name,None,
                         'ability response: automatically passes while SNOOZE ALL is active')
                continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.priority_autopasses_current_stack(responder):continue
            card=self.card_in_hand(responder,'Summary Dismissal')
            if not card or self.can_pay(responder,card.d) is None:continue
            if self.scheduler_suppresses_priority(responder,'ability response',[('summary_response',card,{})]):continue
            context={'ability_response':True,'ability_count':len(ability_markers)}
            object_passes=self.active_priority_object_passes(responder,'ability response')
            general_actions=[
                action for action in self.legal_priority_actions(
                    responder,'spell response',context,include_held=True)
                if (action[1] is not card and
                    not self.priority_action_is_object_passed(action,object_passes))]
            earlier_general=any(
                self.player_has_unsuppressed_general_priority(
                    earlier,'spell response',context)
                for earlier in responders[:responder_index])
            summary_passed=any(entry.source is card for entry in object_passes)
            all_wake_general=list(general_actions)
            visible_general=[] if earlier_general else general_actions
            wake_general=[] if earlier_general else all_wake_general
            wake_actions=([] if summary_passed else [('summary_response',card,{})])+all_wake_general
            if summary_passed and not wake_general:continue
            pass_on=self.priority_pass_on_option(responder,wake_actions)
            response_options=([('summary',True),('summary',False)] if not summary_passed else [])+[
                ('priority_action',action) for action in visible_general]
            for entry in ([] if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION else object_passes):
                if not any(row[0]=='wake' and row[1] is entry.source for row in response_options):
                    response_options.append(('wake',entry.source))
            if pass_on:response_options.append(('pass_on',pass_on))
            if self.stack and self.decision_surface_revision<SCHEDULER_SURFACE_REVISION:response_options.append(('autopass_stack',('autopass_stack',None,{})))
            concede=self.priority_concede_action()
            if concede:response_options.append(('concede',concede))
            chosen=self._request_decision(
                'summary_dismissal_abilities',responder,
                (f'{len(ability_markers)} triggered/activated ability object(s) are on the stack. Choose a response or PASS.'
                 if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION else
                 f'{len(ability_markers)} triggered/activated ability object(s) are on the stack. Take an instant-speed action, wake a snoozed object, PASS ON the sole unsuppressed source, AUTOPASS this stack, or pass.'),
                response_options,
                lambda row:(
                    self.priority_prompt_action_label(responder,row[1])
                    if row[0] in {'priority_action','pass_on','autopass_stack','concede'} else
                    (self.priority_action_label(responder,('wake_priority_object',row[1],{}))
                     if row[0]=='wake' else
                     (self.priority_source_prompt_label(responder,card,'cast Summary Dismissal')
                      if row[1] else 'pass'))),
                gameplan_access=True,
                request_metadata=self.priority_pass_on_request_metadata(
                    responder,pass_on,response_options.index(('pass_on',pass_on)))
                    if pass_on else None)
            if chosen[0]=='concede':
                self.concede_from_priority(responder,'ability response')
                if self.winner or self.pilot_terminal:return True
                continue
            if chosen[0]=='priority_action':
                self.execute_bridged_priority_action(responder,chosen[1],context)
                return self.react_to_abilities(starter)
            if chosen[0]=='pass_on':
                if chosen[1][0]=='pass_on_priority_objects':
                    payload=self._decision_auxiliary_payload(
                        getattr(self,'_last_decision_id','')).get('pass_on_batch') or {}
                    self.arm_priority_object_pass_batch(
                        responder,chosen[1],'ability response',payload)
                else:
                    schedule=self._request_pass_on_schedule(responder,chosen[1][1])
                    self.arm_priority_object_pass(
                        responder,chosen[1][1],'ability response',schedule)
                continue
            if chosen[0]=='wake':
                self.clear_priority_object_pass(
                    responder,chosen[1],
                    f'{self.priority_source_name(chosen[1])} was explicitly woken in an ability response')
                return self.react_to_abilities(starter)
            if chosen[0]=='autopass_stack':
                self.start_priority_stack_autopass(responder);continue
            use=chosen[1]
            if not use:
                if not earlier_general:self.mark_specialized_priority_pass(responder)
                continue
            self.clear_specialized_priority_passes()
            self.clear_priority_object_pass(
                responder,card,f'{card.d.name} was selected; its object pass is cancelled')
            modes=self.__dict__.setdefault('_summary_dismissal_ability_casts',set())
            modes.add(card.uid)
            try:self.cast(responder,card)
            finally:modes.discard(card.uid)
            return not any(marker in self.stack for marker in ability_markers)
        return False

    def choose_x_for_cost(self,p,source,base_cost,max_x=20,tap=False,prompt='Choose X.'):
        legal=[]
        for value in range(max_x+1):
            cost=base_cost(value)
            if self.can_pay_ability(p,cost,source,tap):legal.append(value)
        if not legal:return None
        return self._request_decision('x_value',p,prompt,legal,lambda value:str(value))

    def attach_equipment(self,p,equipment,target):
        if equipment not in p.battlefield or target not in p.battlefield:return False
        old_uid=equipment.attached_to
        if old_uid:
            old=next((q for owner in self.players.values() for q in owner.battlefield if q.uid==old_uid),None)
            if old and equipment.name=='Celestial Armor':old.metadata.pop('celestial_armor_uid',None)
        equipment.attached_to=target.uid
        if equipment.name=='Celestial Armor':target.metadata['celestial_armor_uid']=equipment.uid
        self.log('equip',p.name,equipment.name,f'{equipment.name} equips {target.name}',target_uid=target.uid)
        return True

    def _temporary_copy(self,source,target):
        if 'temporary_copy_original' not in source.metadata:
            source.metadata['temporary_copy_original']={
                'copy_of':source.copy_of,'base_power':source.base_power,'base_toughness':source.base_toughness,
                'keywords':sorted(source.keywords),'name':source.name,
            }
        effective=target.copy_of or target.name
        definition=sim.CARDDEF.get(effective)
        source.copy_of=effective
        source.base_power,source.base_toughness=sim.base_stats(effective,definition)
        source.keywords=set(sim.KEYWORDS.get(effective,set()))
        self.log('copy_effect',source.controller,source.name,f'{source.name} becomes a copy of {effective} until end of turn',target_uid=target.uid)
        if effective=='Dark Depths':
            p=self.players[source.controller]
            others=[q for q in p.battlefield if q.uid!=source.uid and (q.copy_of or q.name)=='Dark Depths']
            if others:
                keep=self.stage_depths_legend_choice(p,source,others)
                for permanent in [source]+others:
                    if permanent is not keep and permanent in p.battlefield:
                        self.leave_battlefield(p,permanent,'graveyard','legend rule: Dark Depths')
            if source in p.battlefield:
                self.queue_dark_depths_state_trigger(p,source,f'{source.name} copied Dark Depths')

    def activate_registered_ability(self,p,source,kind,ability_label=None,**kwargs):
        label=ability_label or kind
        source_name=source.name if hasattr(source,'name') else source.d.name
        def legal_target(owner,target,creature=False):return self.target_still_legal(p,owner,target,creature,source_name)
        p.dungeon['last_payment_sources']=[]
        if kind=='ramunap_land':
            if source not in p.graveyard or p.land_plays_used>=p.land_play_limit:return False
            p.graveyard.remove(source);p.hand.append(source)
            result=self.play_land(p,source)
            if result:self.log('graveyard_land_play',p.name,source.d.name,'Played from graveyard via Ramunap Excavator')
            return result

        # Unlocking a door is a sorcery-speed special action.  It does not use
        # the stack, although the unlock and eerie abilities it causes do.
        if kind=='unlock_awakening_hall':
            if source not in p.battlefield or source.metadata.get('awakening_unlocked'):return False
            if not self.pay_registered_cost(p,source,'{6}{B}{B}'):return False
            return self.unlock_awakening_hall(p,source,'paid unlock special action')

        # Loyalty abilities: loyalty is paid before the ability can be answered.
        if kind in self.LOYALTY_ACTIONS:
            if source not in p.battlefield or source.metadata.get('activated_turn')==self.turn_number:return False
            targets=[];payload={}
            if kind=='aminatou_minus':
                choices=[(owner,q) for owner,q in self.all_permanents() if q.uid!=source.uid and q.owner==p.name and legal_target(owner,q)]
                chosen=self._request_decision('aminatou_blink_target',p,'Aminatou -1: choose another target permanent you own.',choices,lambda row:f'{row[0].name}: {row[1].name}')
                payload['target']=chosen;targets=[chosen[1]]
            elif kind=='minsc_plus':
                legal=[q for q in p.battlefield if self.is_creature_perm(q) and ({'trample','haste'} & self.keywords_for(q))]
                chosen=self._request_decision('minsc_plus_target',p,'Minsc & Boo +1: choose up to one target creature with trample or haste.',legal,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}',allow_pass=True) if legal else None
                payload['target']=chosen
                if chosen:targets=[chosen]
            elif kind=='nissa_ultimate':
                if self.selection_batch_enabled():
                    chosen=self._request_selection('nissa_land_targets',p,'Nissa -6: choose up to two target lands.',
                        [q for q in p.battlefield if sim.is_land_permanent(q)],lambda q:f'{q.name} [{q.uid}]',maximum=2)
                else:
                    remaining=[q for q in p.battlefield if sim.is_land_permanent(q)];chosen=[]
                    for slot in range(2):
                        if not remaining:break
                        land=self._request_decision('nissa_land_target',p,f'Nissa -6: choose target land {slot+1}, or stop.',remaining,lambda q:q.name,allow_pass=True)
                        if not land:break
                        chosen.append(land);remaining.remove(land)
                payload['lands']=chosen;targets=chosen
            elif kind=='sorin_house_minus':
                chosen=self._request_decision('sorin_damage_target',p,'Sorin -1: choose any target.',self.death_grasp_targets(p),
                    lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player' else f'{row[0].upper()} {row[1].name}: {row[2].name}'))
                payload['target']=chosen;targets=[chosen[2]]
            elif kind=='sorin_house_ultimate':
                choices=[(op,q) for op in self.opponents(p) for q in op.battlefield if legal_target(op,q,True)]
                chosen=self._request_decision('sorin_control_target',p,'Sorin -6: choose target creature.',choices,lambda row:f'{row[0].name}: {row[1].name}')
                payload['target']=chosen;targets=[chosen[1]]
            elif kind=='sorin_vengeful_plus':
                choices=[('player',owner,owner) for owner in self.players.values() if not owner.eliminated]
                choices.extend(
                    ('planeswalker',owner,q) for owner,q in self.all_permanents()
                    if self.is_planeswalker_perm(q) and legal_target(owner,q))
                chosen=self._request_decision(
                    'sorin_vengeful_damage_target',p,
                    'Sorin, Vengeful Bloodlord +2: choose target player or planeswalker.',choices,
                    lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player'
                                else f'PLANESWALKER {row[1].name}: {row[2].name}'))
                payload['target']=chosen;targets=[chosen[2]]
            elif kind=='sorin_vengeful_minus':
                choices=[card for card in p.graveyard
                         if card.d.is_creature and card.d.mv<=source.counters.get('loyalty',0)]
                chosen=self._request_decision(
                    'sorin_vengeful_reanimate_target',p,
                    'Sorin, Vengeful Bloodlord -X: choose a creature card with mana value no greater than Sorin loyalty.',
                    choices,lambda card:f'{card.d.name} mana value {card.d.mv}')
                payload['card']=chosen;payload['x']=chosen.d.mv
            costs={'aminatou_plus':1,'aminatou_minus':-1,'aminatou_ultimate':-6,
                   'nissa_plus':2,'nissa_zero':0,'nissa_ultimate':-6,
                   'sorin_house_plus':2,'sorin_house_minus':-1,'sorin_house_ultimate':-6,
                   'sorin_vengeful_plus':2,'minsc_plus':1,'minsc_minus':-2}
            change=(-payload['x'] if kind=='sorin_vengeful_minus' else costs[kind])
            cost_triggers=[]
            if change>0:self.add_counters(p,source,'loyalty',change,label,defer_triggers=cost_triggers)
            else:source.counters['loyalty']=source.counters.get('loyalty',0)+change
            source.metadata['activated_turn']=self.turn_number
            return self.put_registered_stack_item(p,source,label,lambda:self.resolve_registered_loyalty(p,source,kind,payload),targets,cost_triggers=cost_triggers)

        if kind in {'channel_touch','channel_otawara','channel_eiganjo'}:
            card=source
            if card not in p.hand:return False
            legends=sum(1 for q in p.battlefield if sim.CARDDEF.get(q.name) and 'Legendary' in sim.CARDDEF[q.name].type_line and self.is_creature_perm(q))
            if kind=='channel_touch':
                choices=[(owner,q) for owner,q in self.all_permanents() if ((sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact) or self.is_creature_perm(q)) and legal_target(owner,q)]
                cost='{1}{W}'
            elif kind=='channel_otawara':
                choices=[(owner,q) for owner,q in self.all_permanents() if ((sim.CARDDEF.get(q.name) and (sim.CARDDEF[q.name].is_artifact or sim.CARDDEF[q.name].is_enchantment)) or self.is_creature_perm(q) or self.is_planeswalker_perm(q)) and legal_target(owner,q)]
                cost=f'{{{max(0,3-legends)}}}{{U}}'
            else:
                ids=set(p.dungeon.get('cast_priority_context',{}).get('attackers',[]))
                for values in p.dungeon.get('cast_priority_context',{}).get('blocks',{}).values():ids.update(values)
                choices=[(owner,q) for owner,q in self.all_creatures() if q.uid in ids and legal_target(owner,q,True)]
                cost=f'{{{max(0,2-legends)}}}{{W}}'
            if not choices:return False
            owner,target=self._request_decision('channel_target',p,f'{card.d.name}: choose target.',choices,lambda row:f'{row[0].name}: {row[1].name}')
            if not self.pay_registered_cost(p,None,cost):return False
            p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Channel activation cost')
            proxy=sim.Perm(card.uid,card.d.name,p.name,p.name)
            return self.put_registered_stack_item(p,proxy,label,lambda:self.resolve_channel(p,kind,owner,target),[target])

        if kind=='talon_from_hand':
            card=source
            if not self.pay_registered_cost(p,None,'{4}'):return False
            proxy=sim.Perm(card.uid,card.d.name,p.name,p.name)
            def resolve_talon():
                if card not in p.hand:return
                p.hand.remove(card);permanent=self._put_card_bf(p,card,'Talon Gates hand ability');permanent.summoning_sick=False
            return self.put_registered_stack_item(p,proxy,label,resolve_talon)

        if source not in p.battlefield:return False
        if kind in {'hashep_green','horizon_mana','lotus_blossom_mana','sunken_palace','pristine_talisman_mana'}:
            return self.resolve_registered_mana_ability(p,source,kind)

        # Announce all targets, X values, divisions, and non-target cost choices before paying.
        payload={};targets=[];cost='';tap=kind in self.TAP_ACTIONS;sacrifice_source=False
        if kind=='hall_heliod':
            card=self._request_decision('hall_enchantment_target',p,"Hall of Heliod's Generosity: choose target enchantment card.",[c for c in p.graveyard if c.d.is_enchantment],lambda c:c.d.name)
            payload['card']=card;cost='{1}{W}'
        elif kind=='urza_saga_construct':cost='{2}'
        elif kind=='wolf_run':
            owner,target=self._request_decision('wolf_run_target',p,'Kessig Wolf Run: choose target creature.',[(o,q) for o,q in self.all_creatures() if legal_target(o,q,True)],lambda row:f'{row[0].name}: {row[1].name}')
            x=self.choose_x_for_cost(p,source,lambda value:f'{{{value}}}{{R}}{{G}}',20,True,'Kessig Wolf Run: choose X.')
            if x is None:return False
            payload.update(owner=owner,target=target,x=x);targets=[target];cost=f'{{{x}}}{{R}}{{G}}'
        elif kind=='rogues_passage':
            owner,target=self._request_decision('passage_target',p,"Rogue's Passage: choose target creature.",[(o,q) for o,q in self.all_creatures() if legal_target(o,q,True)],lambda row:f'{row[0].name}: {row[1].name}')
            payload.update(owner=owner,target=target);targets=[target];cost='{4}'
        elif kind=='sakura_tribe':sacrifice_source=True
        elif kind in {'equip_boots','equip_helm','equip_armor'}:
            target=self._request_decision('equip_target',p,f'{source.name}: choose target creature you control.',[q for q in p.battlefield if legal_target(p,q,True)],lambda q:q.name)
            payload['target']=target;targets=[target];tap=False
            cost={'equip_boots':'{1}','equip_helm':'{5}','equip_armor':'{3}{W}'}[kind]
        elif kind in {'innkeeper_level2','innkeeper_level3'}:
            cost='{G}' if kind.endswith('level2') else '{3}{G}';tap=False
        elif kind=='shattered_spire_counter':
            target=self._request_decision('spire_target',p,'Ozolith, the Shattered Spire: choose target artifact or creature you control.',[q for q in p.battlefield if self.is_creature_perm(q) or (sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact)],lambda q:q.name)
            payload['target']=target;targets=[target];cost='{1}{G}'
        elif kind=='earth_crystal_distribute':
            creatures=[q for q in p.battlefield if self.is_creature_perm(q)]
            options=[((q,2),) for q in creatures]+[((a,1),(b,1)) for i,a in enumerate(creatures) for b in creatures[i+1:]]
            division=self._request_decision('earth_crystal_division',p,'The Earth Crystal: distribute two counters among one or two target creatures.',options,lambda rows:', '.join(f'{q.name}: {amount}' for q,amount in rows))
            payload['division']=division;targets=[q for q,_ in division];cost='{4}{G}{G}'
        elif kind=='lazotep_copy':
            card=self._request_decision('lazotep_target',p,'Lazotep Quarry: choose target creature card from your graveyard.',[c for c in p.graveyard if c.d.is_creature],lambda c:f'{c.d.name} MV {c.d.mv}')
            deserts=[q for q in p.battlefield if sim.land_has_type(q,'Desert',p)]
            desert=self._request_decision('desert_sacrifice',p,'Lazotep Quarry: choose a Desert to sacrifice.',deserts,lambda q:q.name)
            payload.update(card=card,desert=desert);cost=f'{{{card.d.mv+2}}}'
        elif kind=='mirage_mirror':
            owner,target=self._request_decision('mirage_target',p,'Mirage Mirror: choose target artifact, creature, enchantment, or land.',[(o,q) for o,q in self.all_permanents() if q.uid!=source.uid and sim.CARDDEF.get(q.name) and (sim.CARDDEF[q.name].is_artifact or self.is_creature_perm(q) or sim.CARDDEF[q.name].is_enchantment or sim.is_land_permanent(q)) and legal_target(o,q)],lambda row:f'{row[0].name}: {row[1].name}')
            payload.update(owner=owner,target=target);targets=[target];cost='{2}';tap=False
        elif kind=='basilisk_gate':
            owner,target=self._request_decision('basilisk_target',p,'Basilisk Gate: choose target creature.',[(o,q) for o,q in self.all_creatures() if legal_target(o,q,True)],lambda row:f'{row[0].name}: {row[1].name}')
            payload.update(owner=owner,target=target);targets=[target];cost='{2}'
        elif kind=='hashep_pump':
            target=self._request_decision('hashep_target',p,'Hashep Oasis: choose target creature you control.',[q for q in p.battlefield if self.is_creature_perm(q)],lambda q:q.name)
            desert=self._request_decision('desert_sacrifice',p,'Hashep Oasis: choose a Desert to sacrifice.',[q for q in p.battlefield if sim.land_has_type(q,'Desert',p)],lambda q:q.name)
            payload.update(target=target,desert=desert);targets=[target];cost='{1}{G}{G}'
        elif kind=='volatile_fault':
            owner,target=self._request_decision('volatile_target',p,'Volatile Fault: choose target nonbasic land an opponent controls.',[(o,q) for o in self.opponents(p) for q in o.battlefield if sim.is_land_permanent(q) and q.name not in {'Plains','Island','Swamp','Mountain','Forest'}],lambda row:f'{row[0].name}: {row[1].name}')
            payload.update(owner=owner,target=target);targets=[target];cost='{1}';sacrifice_source=True
        elif kind=='blast_zone_counters':
            x=self.choose_x_for_cost(p,source,lambda value:f'{{{2*value}}}',10,True,'Blast Zone: choose X charge counters.')
            if x is None:return False
            payload['x']=x;cost=f'{{{2*x}}}'
        elif kind=='blast_zone_destroy':cost='{3}';sacrifice_source=True
        elif kind=='horizon_land':cost='{3}'
        elif kind=='horizon_draw':cost='{1}';sacrifice_source=True
        elif kind=='wonderscape_sage':
            land=self._request_decision('wonderscape_land_cost',p,'Wonderscape Sage: choose a land to return as a cost.',[q for q in p.battlefield if sim.is_land_permanent(q)],lambda q:q.name)
            definition=sim.CARDDEF.get(land.copy_of or land.name);subtypes=(definition.type_line.split('—',1)[1].strip().split() if definition and '—' in definition.type_line else [])
            payload.update(land=land,had_nonbasic_type=any(t not in {'Plains','Island','Swamp','Mountain','Forest'} for t in subtypes))
        elif kind=='animate_lumbering':cost='{2}{G}{U}';tap=False
        elif kind=='magus_candelabra':
            lands=[q for q in p.battlefield if sim.is_land_permanent(q) and q.tapped]
            x=self.choose_x_for_cost(p,source,lambda value:f'{{{value}}}',min(20,len(lands)),True,'Magus of the Candelabra: choose X lands to untap.')
            if not x:return False
            if self.selection_batch_enabled():
                chosen=self._request_selection('magus_land_targets',p,f'Magus: choose exactly {x} target lands.',lands,
                    lambda q:f'{q.name} [{q.uid}]',minimum=x,maximum=x)
            else:
                chosen=[]
                for slot in range(x):
                    land=self._request_decision('magus_land_target',p,f'Magus: choose target land {slot+1} of {x}.',[q for q in lands if q not in chosen],lambda q:q.name)
                    chosen.append(land)
            payload['lands']=chosen;targets=chosen;cost=f'{{{x}}}'
        elif kind=='urzas_cave':cost='{3}';sacrifice_source=True
        elif kind=='trenchpost':
            target=self._request_decision('trenchpost_target',p,'Trenchpost: choose target player.',[x for x in self.players.values() if not x.eliminated],lambda x:f'{x.name} library={len(x.library)}')
            payload['player']=target;cost='{3}'
        elif kind.startswith('trading_post_'):
            cost='{1}'
            if kind=='trading_post_life':
                card=self._request_decision('trading_discard',p,'Trading Post: choose a card to discard as a cost.',list(p.hand),lambda c:f'{c.d.name} {c.d.mana_cost}');payload['discard']=card
            elif kind=='trading_post_recur':
                creature=self._request_decision('trading_creature_cost',p,'Trading Post: choose a creature to sacrifice.',[q for q in p.battlefield if self.is_creature_perm(q)],lambda q:q.name)
                card=self._request_decision('trading_artifact_target',p,'Trading Post: choose target artifact card in your graveyard.',[c for c in p.graveyard if c.d.is_artifact],lambda c:c.d.name)
                payload.update(creature=creature,card=card)
            elif kind=='trading_post_draw':
                artifact=self._request_decision('trading_artifact_cost',p,'Trading Post: choose an artifact to sacrifice.',[q for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_artifact],lambda q:q.name);payload['artifact']=artifact
        elif kind=='mikaeus_self':pass
        elif kind=='mikaeus_team':pass
        elif kind=='animate_fortress':cost='{2}{W}{B}';tap=False
        elif kind=='alseid_protection':
            target=self._request_decision('alseid_target',p,
                "Alseid of Life's Bounty: choose target creature or enchantment you control.",
                [q for q in p.battlefield if self.is_creature_perm(q) or (sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_enchantment)],
                lambda q:q.name)
            color=self._request_decision('protection_color',p,'Choose a color.',list('WUBRG'),lambda value:value)
            payload.update(target=target,color=color);targets=[target];cost='{1}';tap=False;sacrifice_source=True
        elif kind=='glen_counter':
            spells=[item for item in self.stack if isinstance(item,dict) and item.get('actor')!=p.name and
                    sim.CARDDEF.get(item.get('card')) and not sim.CARDDEF[item['card']].is_creature]
            if not spells:return False
            target=self._request_decision('glen_spell_target',p,'Glen Elendra Archmage: choose target noncreature spell.',spells,
                lambda item:f'{item["actor"]}: {item["card"]}')
            payload['stack_target']=target;cost='{U}';tap=False;sacrifice_source=True
        elif kind=='omen_scry':cost='{2}{U}';tap=False;sacrifice_source=True
        elif kind=='splendor_draw':
            alive=[player for player in self.players.values() if not player.eliminated]
            first=self._request_decision('splendor_first_target',p,'Gleaming Splendor: choose the first target player.',alive,lambda player:player.name)
            second=self._request_decision('splendor_second_target',p,'Gleaming Splendor: choose the second target player.',[player for player in alive if player is not first],lambda player:player.name)
            payload['players']=(first,second);cost='{2}{W}';tap=False
        elif kind=='loran_draw':
            opponent=self._request_decision('loran_opponent_target',p,'Loran: choose target opponent.',self.opponents(p),lambda player:player.name)
            payload['opponent']=opponent
        elif kind=='expedition_map':cost='{2}';sacrifice_source=True
        elif kind=='mazes_end':cost='{3}';payload['return_source']=True
        elif kind=='dawn_soldier':cost='{3}{W}';tap=False
        elif kind=='midnight_snack':
            opponent=self._request_decision('midnight_snack_target',p,'Midnight Snack: choose target opponent.',self.opponents(p),lambda player:f'{player.name} life={player.life}')
            payload['opponent']=opponent;cost='{2}{B}';tap=False;sacrifice_source=True
        elif kind in {'mind_stone_draw','silent_clearing_draw'}:cost='{1}';sacrifice_source=True
        else:return False

        cost_triggers=[]
        self.__dict__.setdefault('_ltb_trigger_frames',[]).append(cost_triggers)
        paid=self.pay_registered_cost(p,source,cost,tap=tap,sacrifice_source=sacrifice_source,
                                      life=1 if kind=='trading_post_goat' else 0)
        if not paid:
            self._ltb_trigger_frames.pop();return False
        if kind=='lazotep_copy':
            desert=payload['desert']
            if desert in p.battlefield:self.leave_battlefield(p,desert,'graveyard','Lazotep Quarry activation cost')
        if kind=='hashep_pump':
            desert=payload['desert']
            if desert in p.battlefield:self.leave_battlefield(p,desert,'graveyard','Hashep Oasis activation cost')
        if kind=='wonderscape_sage':self.bounce(p,payload['land'],'Wonderscape Sage activation cost')
        if kind=='trading_post_life':
            card=payload['discard'];p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Trading Post activation cost')
        if kind=='trading_post_recur' and payload['creature'] in p.battlefield:self.leave_battlefield(p,payload['creature'],'graveyard','Trading Post activation cost')
        if kind=='trading_post_draw' and payload['artifact'] in p.battlefield:self.leave_battlefield(p,payload['artifact'],'graveyard','Trading Post activation cost')
        if kind=='mikaeus_team':source.counters['+1/+1']-=1
        if payload.get('return_source') and source in p.battlefield:
            self.leave_battlefield(p,source,'hand',f'{source.name} activation cost')
        self._ltb_trigger_frames.pop()
        return self.put_registered_stack_item(p,source,label,
            lambda:self.resolve_registered_nonmana(p,source,kind,payload),targets,cost_triggers=cost_triggers,
            copy_factory=lambda new_targets:lambda:self.resolve_registered_nonmana(
                p,source,kind,self._retarget_payload(payload,targets,new_targets)))

    def target_still_legal(self,p,owner,target,creature=False,source_name=None):
        if target not in owner.battlefield or sim.permanent_phased_out(target):return False
        if 'shroud' in self.keywords_for(target) or (owner is not p and self.has_hexproof(target)) or (creature and not self.is_creature_perm(target)):return False
        source_name=source_name or p.dungeon.get('resolving_source_name')
        source_colors=self.source_colors(source_name)
        protected=self.continuous_view(target).rules.get('protection_colors',set())
        return not bool(source_colors & protected)

    def source_colors(self,source):
        """Return the colors of a spell, ability source, or permanent object."""
        if source is None:return set()
        if hasattr(source,'uid') and hasattr(source,'name'):
            return set(self.continuous_view(source).colors)
        name=source.d.name if hasattr(source,'d') else str(source)
        definition=sim.CARDDEF.get(name)
        if not definition:return set()
        return set(__import__('re').findall(r'[WUBRG]',definition.mana_cost.split(' // ')[0]))

    def protection_prevents_damage(self,source,target):
        protected=self.continuous_view(target).rules.get('protection_colors',set())
        return bool(protected & self.source_colors(source))

    def resolve_any_target_damage(self,p,row,amount,reason):
        kind,owner,obj=row
        if kind=='player':
            if not obj.eliminated:self.deal_damage_batch(p,[],[(p.dungeon.get('resolving_source_name') or reason,obj,amount)],reason)
            return
        if not self.target_still_legal(p,owner,obj):
            self.log('ability_fizzle',p.name,reason,f'Target {obj.name} is no longer legal');return
        if kind=='planeswalker':
            if not self.protection_prevents_damage(p.dungeon.get('resolving_source_name') or reason,obj):obj.counters['loyalty']=obj.counters.get('loyalty',0)-amount
            self.check_sba()
        else:
            self.deal_damage_batch(p,[(p.dungeon.get('resolving_source_name') or reason,owner,obj,amount)],[],reason)

    def deal_damage_batch(self,controller,creature_damage,player_damage,reason,starter=None):
        """Deal one simultaneous damage event and batch all waiting triggers."""
        damaged_priests=[];lifelink_totals={};dealt_rows=[]
        for source,owner,target,amount in creature_damage:
            if amount<=0 or target not in owner.battlefield:continue
            if self.protection_prevents_damage(source,target):
                self.log('damage_prevented',owner.name,getattr(source,'name',str(source)),f'Protection prevents {amount} damage to {target.name}',target_uid=target.uid,amount=amount)
                continue
            target.metadata['damage_marked']=target.metadata.get('damage_marked',0)+amount
            if hasattr(source,'uid') and 'deathtouch' in self.keywords_for(source):target.metadata['deathtouch_damage_turn']=self.turn_number
            dealt_rows.append((source,amount));self.log('damage',controller.name,reason,f'{target.name} is dealt {amount} damage',target_uid=target.uid,amount=amount)
            if target.name=='High Priest of Penance':damaged_priests.append((self.players[target.controller],target))
        for source,player,amount in player_damage:
            if amount<=0 or player.eliminated:continue
            self.lose_life(player,amount,reason);dealt_rows.append((source,amount))
        for source,amount in dealt_rows:
            if hasattr(source,'uid') and 'lifelink' in self.keywords_for(source):
                source_controller=self.players[source.controller];lifelink_totals[source_controller.name]=lifelink_totals.get(source_controller.name,0)+amount
        for name,amount in lifelink_totals.items():self.gain_life(self.players[name],amount,f'{reason} lifelink')
        death_triggers=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(death_triggers)
        self.check_sba();self._ltb_trigger_frames.pop()
        damage_triggers=[]
        for priest_controller,priest in damaged_priests:
            trigger=self._high_priest_damage_trigger(priest_controller,priest)
            if trigger:damage_triggers.append(trigger)
        generated=death_triggers+damage_triggers
        if generated:self.resolve_simultaneous_triggers(f'{reason}: damage and death triggers',generated,starter=starter or controller)
        return sum(amount for _,amount in dealt_rows)

    def resolve_registered_loyalty(self,p,source,kind,payload):
        if kind=='aminatou_plus':
            self.draw(p,1,'Aminatou +1')
            if p.hand:
                card=self._request_decision('aminatou_topdeck',p,'Aminatou +1: choose a card from your hand to put on top of your library.',list(p.hand),lambda c:f'{c.d.name} {c.d.mana_cost}')
                p.hand.remove(card);p.library.append(card);self.log('put_on_top',p.name,card.d.name,'Aminatou +1')
        elif kind=='minsc_plus':
            target=payload.get('target')
            if target and target in p.battlefield:self.add_counters(p,target,'+1/+1',3,'Minsc & Boo +1')
        elif kind=='minsc_minus':
            creatures=[q for q in p.battlefield if self.is_creature_perm(q)]
            if not creatures:return
            sacrificed=self._request_decision('minsc_minus_sacrifice',p,'Minsc & Boo -2: sacrifice a creature.',creatures,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')
            amount=self.effective_power(sacrificed)
            hamster=self.has_creature_type(sacrificed,'Hamster')
            self.leave_battlefield(p,sacrificed,'graveyard','Minsc & Boo -2 sacrifice')
            choices=self.death_grasp_targets(p)
            if not choices:return
            chosen=self._request_decision('minsc_minus_target',p,f'Minsc & Boo reflexive trigger: choose any target for {amount} damage.',choices,
                lambda row:(f'PLAYER {row[2].name} life={row[2].life}' if row[0]=='player' else f'{row[0].upper()} {row[1].name}: {row[2].name}'))
            target_obj=chosen[2]
            def resolve_minsc_reflexive():
                self.resolve_any_target_damage(p,chosen,amount,'Minsc & Boo -2')
                if hamster:self.draw(p,min(amount,40),'Minsc & Boo -2 Hamster draw')
            self.resolve_simultaneous_triggers('Minsc & Boo reflexive trigger',[{
                'controller':p,'source':source.name,'label':f'deal {amount} damage to {target_obj.name}; '+('draw that many cards' if hamster else 'no draw'),
                'targets':[target_obj],'resolve':resolve_minsc_reflexive,
            }],starter=self.players[self.turn_order[self.active_idx]])
        elif kind=='aminatou_minus':
            owner,target=payload['target']
            if not self.target_still_legal(p,owner,target):return
            uid=target.uid;self.leave_battlefield(owner,target,'exile','Aminatou -1')
            physical_owner=self.players[target.owner]
            card=next((c for c in physical_owner.exile if c.uid==uid),None)
            if card:
                physical_owner.exile.remove(card);self._put_card_bf(p,card,'Aminatou -1 return')
        elif kind=='aminatou_ultimate':
            direction=self._request_decision('aminatou_direction',p,'Aminatou -6: choose a direction.',['left','right'],lambda value:value)
            alive=[self.players[name] for name in self.turn_order if not self.players[name].eliminated]
            snapshots={player.name:[q for q in player.battlefield if not sim.is_land_permanent(q) and q.uid!=source.uid] for player in alive}
            for index,receiver in enumerate(alive):
                giver=alive[(index+1)%len(alive)] if direction=='left' else alive[(index-1)%len(alive)]
                for permanent in snapshots[giver.name]:
                    current=self.players[permanent.controller]
                    if permanent in current.battlefield:current.battlefield.remove(permanent)
                    receiver.battlefield.append(permanent);permanent.controller=receiver.name
            self.log('control_exchange',p.name,source.name,f'Each player gains the next player\'s nonland permanents to the {direction}')
        elif kind=='nissa_plus':self.scry(p,2,'Nissa +2')
        elif kind=='nissa_zero':
            if not p.library:return
            card=p.library[-1];loyalty=source.counters.get('loyalty',0)
            qualifies=card.d.is_land or (card.d.is_creature and card.d.mv<=loyalty)
            if qualifies:
                put=self._request_decision('nissa_zero_put',p,f'Nissa 0 sees {card.d.name}. Put it onto the battlefield?',[True,False],lambda value:'put onto battlefield' if value else 'leave on top')
                if put:
                    p.library.pop();self._put_card_bf(p,card,'Nissa 0')
            self.log('look_top',p.name,source.name,f'Nissa 0 looked at the top card; qualifying={qualifies}')
        elif kind=='nissa_ultimate':
            for land in payload['lands']:
                if land in p.battlefield:
                    land.tapped=False;land.metadata['nissa_animated_turn']=self.turn_number
                    land.metadata['nissa_power']=5
                    for keyword in ('flying','haste'):
                        if keyword not in land.keywords:land.metadata.setdefault('temporary_keywords',[]).append(keyword)
                        land.keywords.add(keyword)
        elif kind=='sorin_house_plus':
            p.dungeon['food']=p.dungeon.get('food',0)+1;self.log('food',p.name,source.name,'Created a Food token',food=p.dungeon['food'])
        elif kind=='sorin_house_minus':
            self.resolve_any_target_damage(p,payload['target'],p.life_gained_this_turn,source.name)
        elif kind=='sorin_house_ultimate':
            owner,target=payload['target']
            if not self.target_still_legal(p,owner,target,True):return
            owner.battlefield.remove(target);p.battlefield.append(target);target.controller=p.name
            target.metadata['additional_types']=sorted(set(target.metadata.get('additional_types',[]))|{'Vampire'})
            white=any(q.uid not in {source.uid,target.uid} and 'W' in sim.CARDDEF.get(q.name,sim.CardDef('', '', '', '',1,'',0)).mana_cost for q in p.battlefield if sim.CARDDEF.get(q.name))
            if white:target.counters['lifelink']=target.counters.get('lifelink',0)+1;target.keywords.add('lifelink')
            self.log('control_change',p.name,source.name,f'Gain control of {target.name}; it becomes a Vampire'+(' with lifelink' if white else ''),target_uid=target.uid)
        elif kind=='sorin_vengeful_plus':
            self.resolve_any_target_damage(p,payload['target'],1,source.name)
            self.gain_life(p,1,source.name+' lifelink')
        elif kind=='sorin_vengeful_minus':
            card=payload['card']
            if card not in p.graveyard:return
            p.graveyard.remove(card);permanent=self._put_card_bf(p,card,source.name)
            permanent.metadata['additional_types']=sorted(
                set(permanent.metadata.get('additional_types',[]))|{'Vampire'})

    def resolve_channel(self,p,kind,owner,target):
        if not self.target_still_legal(p,owner,target,creature=(kind=='channel_eiganjo')):
            self.log('ability_fizzle',p.name,kind,f'Target {target.name} is no longer legal');return
        if kind=='channel_touch':
            uid=target.uid;self.leave_battlefield(owner,target,'exile','Touch the Spirit Realm channel')
            due=self.turn_number+(1 if self.phase in {'end_step','cleanup'} else 0)
            self.pending_delayed_returns.append({'uid':uid,'due_turn':due,'controller':p.name,'source':'Touch the Spirit Realm'})
        elif kind=='channel_otawara':self.bounce(owner,target,'Otawara channel')
        else:
            self.deal_damage_batch(p,[('Eiganjo, Seat of the Empire',owner,target,4)],[],'Eiganjo channel')

    def resolve_registered_mana_ability(self,p,source,kind):
        if source not in p.battlefield or source.tapped:return False
        if self.is_creature_perm(source) and source.summoning_sick:return False
        if kind=='hashep_green':
            source.tapped=True;self.lose_life(p,1,'Hashep Oasis mana ability');p.dungeon.setdefault('floating_mana',[]).append('G')
        elif kind=='horizon_mana':
            colors=set()
            for land in p.battlefield:
                if sim.is_land_permanent(land) and land.uid!=source.uid:colors|=sim.land_colors(p,land)
            if not colors:return False
            color=self._request_decision('mana_type',p,'Horizon of Progress: choose a mana type a land you control could produce.',sorted(colors),lambda value:value)
            source.tapped=True;self.lose_life(p,1,'Horizon of Progress mana ability');p.dungeon.setdefault('floating_mana',[]).append(color)
        elif kind=='lotus_blossom_mana':
            amount=source.counters.get('petal',0)
            if amount<=0:return False
            color=self._request_decision('mana_color',p,f'Lotus Blossom: choose one color for {amount} mana.',list('WUBRG'),lambda value:value)
            if self.perm(p,'Mana Reflection'):amount*=2
            source.tapped=True;self.leave_battlefield(p,source,'graveyard','Lotus Blossom mana ability cost')
            p.dungeon.setdefault('floating_mana',[]).extend([color]*amount)
        elif kind=='pristine_talisman_mana':
            source.tapped=True
            amount=2 if self.perm(p,'Mana Reflection') else 1
            p.dungeon.setdefault('floating_mana',[]).extend(['C']*amount)
            self.gain_life(p,1,'Pristine Talisman mana ability')
        else:
            if len(p.graveyard)<7 or not self.pay_registered_cost(p,source,'{1}{U}',tap=True):return False
            if self.selection_batch_enabled():
                chosen=self._request_selection('sunken_exile_selection',p,'Sunken Palace: choose exactly seven graveyard cards to exile.',p.graveyard,
                    lambda card:f'{card.d.name} [{card.uid}]',minimum=7,maximum=7)
            else:
                chosen=[]
                for slot in range(7):
                    card=self._request_decision('sunken_exile_cost',p,f'Sunken Palace: choose graveyard card {slot+1} of 7 to exile.',[c for c in p.graveyard if c not in chosen],lambda c:c.d.name)
                    chosen.append(card)
            for card in chosen:p.graveyard.remove(card);p.exile.append(card)
            p.dungeon.setdefault('floating_mana',[]).append('SUNKEN-U')
        self.log('mana_ability',p.name,source.name,f'Resolved {kind}',floating=list(p.dungeon.get('floating_mana',[])))
        return True

    def resolve_registered_nonmana(self,p,source,kind,payload):
        if kind=='hall_heliod':
            card=payload['card']
            if card in p.graveyard:p.graveyard.remove(card);p.library.append(card);self.log('put_on_top',p.name,card.d.name,"Hall of Heliod's Generosity",visibility='public')
        elif kind=='urza_saga_construct':
            token=self.token(p,'Construct',0,0);token.metadata['construct_token']=True;token.metadata['artifact']=True
        elif kind=='wolf_run':
            owner,target=payload['owner'],payload['target']
            if self.target_still_legal(p,owner,target,True):
                target.metadata['wolf_run_power']=target.metadata.get('wolf_run_power',0)+payload['x']
                if 'trample' not in target.keywords:target.metadata.setdefault('temporary_keywords',[]).append('trample')
                target.keywords.add('trample')
        elif kind=='rogues_passage':
            owner,target=payload['owner'],payload['target']
            if self.target_still_legal(p,owner,target,True):target.metadata['unblockable_turn']=self.turn_number
        elif kind=='sakura_tribe':
            basics=[c for c in p.library if c.d.type_line.startswith('Basic Land')]
            if basics:
                card=self._request_decision('sakura_basic',p,'Sakura-Tribe Elder: choose a basic land.',basics,lambda c:c.d.name)
                p.library.remove(card);land=self._put_card_bf(p,card,'Sakura-Tribe Elder');land.tapped=True
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Sakura-Tribe Elder')
        elif kind in {'equip_boots','equip_helm','equip_armor'}:self.attach_equipment(p,source,payload['target'])
        elif kind=='innkeeper_level2':
            if source in p.battlefield and source.metadata.get('level',1)==1:source.metadata['level']=2
        elif kind=='innkeeper_level3':
            if source in p.battlefield and source.metadata.get('level',1)==2:source.metadata['level']=3
        elif kind=='shattered_spire_counter':
            target=payload['target']
            if target in p.battlefield:self.add_counters(p,target,'+1/+1',1,source.name)
        elif kind=='earth_crystal_distribute':
            for target,amount in payload['division']:
                if target in p.battlefield:self.add_counters(p,target,'+1/+1',amount,source.name)
        elif kind=='lazotep_copy':
            card=payload['card']
            if card in p.graveyard:
                p.graveyard.remove(card);p.exile.append(card);self.create_lazotep_copy(p,card)
        elif kind=='mirage_mirror':
            owner,target=payload['owner'],payload['target']
            if self.target_still_legal(p,owner,target):self._temporary_copy(source,target)
        elif kind=='basilisk_gate':
            owner,target=payload['owner'],payload['target']
            if self.target_still_legal(p,owner,target,True):
                gates=sum(1 for q in p.battlefield if sim.land_has_type(q,'Gate',p))
                target.metadata['basilisk_bonus']=target.metadata.get('basilisk_bonus',0)+gates
        elif kind=='hashep_pump':
            target=payload['target']
            if target in p.battlefield:target.metadata['hashep_bonus']=target.metadata.get('hashep_bonus',0)+3
        elif kind=='volatile_fault':
            owner,target=payload['owner'],payload['target']
            if target in owner.battlefield:
                self.destroy(owner,target,'Volatile Fault')
                basics=[c for c in owner.library if c.d.type_line.startswith('Basic Land')]
                if basics:
                    search=self._request_decision('volatile_basic',owner,'Volatile Fault: search for a basic land?',basics,lambda c:c.d.name,allow_pass=True)
                    if search:owner.library.remove(search);land=self._put_card_bf(owner,search,'Volatile Fault');land.tapped=self.land_enters_tapped(owner,search)
                self.rng.shuffle(owner.library);self.log('shuffle',owner.name,None,'Shuffle after Volatile Fault')
            p.treasures+=1;self.log('treasure',p.name,'Volatile Fault','Create a Treasure',treasures=p.treasures)
        elif kind=='blast_zone_counters':self.add_counters(p,source,'charge',payload['x'],'Blast Zone')
        elif kind=='blast_zone_destroy':
            charge=source.counters.get('charge',0)
            generated=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(generated)
            try:
                for owner,permanent in list(self.all_permanents()):
                    definition=sim.CARDDEF.get(permanent.copy_of or permanent.name)
                    mv=definition.mv if definition else 0
                    if not sim.is_land_permanent(permanent) and mv==charge:self.destroy(owner,permanent,'Blast Zone')
            finally:self._ltb_trigger_frames.pop()
            if generated:self.resolve_simultaneous_triggers('Blast Zone destruction triggers',generated,starter=p)
        elif kind=='horizon_land':
            lands=[c for c in p.hand if c.d.is_land]
            if lands:
                card=self._request_decision('horizon_land_choice',p,'Horizon of Progress: put a land from hand onto the battlefield tapped?',lands,lambda c:c.d.name,allow_pass=True)
                if card:p.hand.remove(card);land=self._put_card_bf(p,card,'Horizon of Progress');land.tapped=True
        elif kind=='horizon_draw':self.draw(p,1,'Horizon of Progress')
        elif kind=='wonderscape_sage':
            self.draw(p,1,'Wonderscape Sage')
            if not payload['had_nonbasic_type'] and p.hand:
                card=self._request_decision('wonderscape_discard',p,'Wonderscape Sage: choose a card to discard.',list(p.hand),lambda c:f'{c.d.name} {c.d.mana_cost}')
                p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Wonderscape Sage')
        elif kind=='animate_lumbering':
            if source in p.battlefield:
                source.metadata['lumbering_animated_turn']=self.turn_number;source.metadata['lumbering_power']=3
                if 'hexproof' not in source.keywords:source.metadata.setdefault('temporary_keywords',[]).append('hexproof')
                source.keywords.add('hexproof')
        elif kind=='magus_candelabra':
            for land in payload['lands']:
                if any(land in owner.battlefield for owner in self.players.values()):land.tapped=False
        elif kind=='urzas_cave':
            lands=[c for c in p.library if c.d.is_land]
            if lands:
                card=self._request_decision('urzas_cave_land',p,"Urza's Cave: choose a land card.",lands,lambda c:f'{c.d.name} | {c.d.type_line}')
                p.library.remove(card);land=self._put_card_bf(p,card,"Urza's Cave");land.tapped=True
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,"Shuffle after Urza's Cave")
        elif kind=='trenchpost':
            loci=sum(1 for q in p.battlefield if sim.land_has_type(q,'Locus',p))
            self.mill(payload['player'],loci,'Trenchpost')
        elif kind=='trading_post_life':self.gain_life(p,4,'Trading Post')
        elif kind=='trading_post_goat':self.token(p,'Goat',0,1)
        elif kind=='trading_post_recur':
            card=payload['card']
            if card in p.graveyard:p.graveyard.remove(card);p.hand.append(card);self.log('return_to_hand',p.name,card.d.name,'Trading Post')
        elif kind=='trading_post_draw':self.draw(p,1,'Trading Post')
        elif kind=='mikaeus_self':
            if source in p.battlefield:self.add_counters(p,source,'+1/+1',1,source.name)
        elif kind=='mikaeus_team':
            for creature in [q for q in p.battlefield if self.is_creature_perm(q) and q.uid!=source.uid]:self.add_counters(p,creature,'+1/+1',1,source.name)
        elif kind=='animate_fortress':
            if source in p.battlefield:source.metadata['fortress_animated_turn']=self.turn_number;source.metadata['fortress_power']=1;source.metadata['fortress_toughness']=4
        elif kind=='alseid_protection':
            target=payload['target']
            if target in p.battlefield:
                target.metadata.setdefault('protection_colors_turn',{})[payload['color']]=self.turn_number
                self.log('protection',p.name,source.name,f'{target.name} gains protection from {payload["color"]} until end of turn',target_uid=target.uid,color=payload['color'])
        elif kind=='glen_counter':
            target=payload['stack_target']
            if target in self.stack:self.stack.remove(target);self.log('counterspell',p.name,source.name,f'Counters {target["card"]}',target=target['card'])
        elif kind=='omen_scry':self.scry(p,2,'Omen of the Sea activation')
        elif kind=='splendor_draw':
            for player in payload['players']:
                if not player.eliminated:self.draw(player,1,'Gleaming Splendor activation')
        elif kind=='loran_draw':
            self.draw(p,1,'Loran of the Third Path')
            if not payload['opponent'].eliminated:self.draw(payload['opponent'],1,'Loran of the Third Path')
        elif kind=='expedition_map':
            lands=[card for card in p.library if card.d.is_land]
            if lands:
                card=self._request_decision('expedition_map_land',p,'Expedition Map: choose a land card.',lands,lambda card:f'{card.d.name} | {card.d.type_line}')
                p.library.remove(card);p.hand.append(card);self.log('tutor',p.name,card.d.name,'Expedition Map to hand',destination='hand',visibility='public')
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Expedition Map')
        elif kind=='mazes_end':
            gates=[card for card in p.library if 'Gate' in card.d.type_line]
            if gates:
                card=self._request_decision('mazes_end_gate',p,"Maze's End: choose a Gate card.",gates,lambda card:card.d.name)
                p.library.remove(card);land=self._put_card_bf(p,card,"Maze's End")
                land.tapped=self.land_enters_tapped(p,card);land.summoning_sick=False
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,"Shuffle after Maze's End")
            names={permanent.copy_of or permanent.name for permanent in p.battlefield if sim.land_has_type(permanent,'Gate',p)}
            if len(names)>=10:
                self.winner=p.name;self.win_turn=self.turn_number;self.win_reason="Maze's End controls ten Gates with different names"
                self.log('winner',p.name,"Maze's End",self.win_reason)
        elif kind=='dawn_soldier':self.token(p,'Soldier',1,1,{'lifelink'})
        elif kind=='midnight_snack':
            opponent=payload['opponent']
            if not opponent.eliminated:self.lose_life(opponent,p.life_gained_this_turn,'Midnight Snack')
        elif kind in {'mind_stone_draw','silent_clearing_draw'}:self.draw(p,1,source.name)

    def create_lazotep_copy(self,p,card):
        uid=f'TOK-{self.game_no}-{self.seq+1}-{card.d.name}'
        token=sim.Perm(uid,card.d.name,p.name,p.name,False,True,{},None,card.d.name,True,4,4,set(sim.KEYWORDS.get(card.d.name,set())),self.turn_number)
        token.metadata.update({'zombie_copy':True,'additional_types':['Zombie'],'color':'B'})
        p.battlefield.append(token);self.log('token_etb',p.name,card.d.name,f'Created a 4/4 black Zombie copy of {card.d.name}',uid=uid)
        self.on_etb(p,token)
        return token

    # ---------- spell sequencing ----------
    @read_only_views
    def legal_main_actions(self,p,context=None):
        actions=self.registered_actions(p,'sorcery')
        # Mana abilities are legal while the active player has priority even
        # when no payment is pending. Pristine Talisman's attached lifegain is
        # strategically material, so expose that activation on the main menu.
        for action in self.registered_actions(p,'priority'):
            if action[0]=='pristine_talisman_mana':actions.append(action)
        for fetch in [q for q in p.battlefield if q.name in sim.FETCHES and not q.tapped]:actions.append(('fetch_activate',fetch,{}))
        bauble=self.perm(p,"Wayfarer's Bauble")
        bauble_cost=sim.CardDef("Wayfarer's Bauble activation",'{2}','Ability','',1,p.name,2)
        if bauble and self.can_pay(p,bauble_cost) is not None and any(c.d.type_line.startswith('Basic Land') for c in p.library):
            actions.append(('bauble_activate',bauble,{}))
        if p.name=='Reaminatour':
            # Explicit activated abilities: ledger exposes them; referee decides whether/when to use them.
            wave=self.perm(p,'Parallax Wave')
            if wave and wave.counters.get('fade',0)>0 and any(self.is_creature_perm(q) for pp in self.players.values() for q in pp.battlefield if q.uid!=wave.uid):
                actions.append(('wave_activate',wave,{}))
            seer=self.perm(p,'Viscera Seer')
            if seer and any(self.is_creature_perm(q) for q in p.battlefield):actions.append(('seer_activate',seer,{}))
            devo=self.perm(p,'Fanatical Devotion')
            if devo and any(self.is_creature_perm(q) for q in p.battlefield):actions.append(('devotion_activate',devo,{}))
            dhbf=self.perm(p,'Dimir House Guard')
            if dhbf and any(self.is_creature_perm(q) for q in p.battlefield):actions.append(('houseguard_sac',dhbf,{}))
            ideal=self.perm(p,'Fallen Ideal')
            if ideal and ideal.attached_to and any(self.is_creature_perm(q) for q in p.battlefield):actions.append(('fallen_sac',ideal,{}))
            dh=self.card_in_hand(p,'Dimir House Guard')
            if dh and self.can_pay(p,sim.CardDef('transmute','{1}{B}{B}','Ability','',1,p.name,3)):
                actions.append(('transmute',dh,{}))
            if self.perm(p,'Chthonian Nightmare') and p.energy>=1 and any(c.d.is_creature for c in p.graveyard) and any(self.is_creature_perm(q) for q in p.battlefield):
                actions.append(('nightmare',None,{}))
            top=self.perm(p,"Sensei's Divining Top")
            top_cost=sim.CardDef("Sensei's Divining Top look",'{1}','Ability','',1,p.name,1)
            if top and self.can_pay(p,top_cost) is not None:actions.append(('top_look',top,{}))
            if top and not top.tapped and p.library:actions.append(('top_draw',top,{}))
        if p.name=='Omo':
            sage=self.perm(p,'Sage of the Maze')
            gates=sum(1 for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land and ('Gate' in sim.CARDDEF[q.name].type_line.split(' // ')[0] or q.counters.get('everything',0)>0))
            if sage and not sage.tapped and not sage.summoning_sick and gates>0:
                actions.append(('sage_animate',sage,{}))
            # Main-phase action selection is itself a priority window, so
            # Mirage Mirror's instant-speed activated ability must remain
            # available here.  Most legacy priority abilities have dedicated
            # main-menu projections above; Mirror is catalog-registered and
            # otherwise disappeared immediately after it resolved.
            for action in self.registered_actions(p,'priority'):
                if action[0]=='mirage_mirror':actions.append(action)
            uro=next((c for c in p.graveyard if c.d.name=="Uro, Titan of Nature's Wrath"),None)
            others=[c for c in p.graveyard if c.uid!=(uro.uid if uro else None)]
            esc=sim.CardDef('Uro escape','{G}{G}{U}{U}','Ability','',1,p.name,4)
            if uro and len(others)>=5 and self.can_pay(p,esc):actions.append(('escape_uro',uro,{}))
        for depths in [q for q in p.battlefield if (q.copy_of or q.name)=='Dark Depths' and q.counters.get('ice',0)>0]:
            depth_cost=sim.CardDef('Dark Depths activation','{3}','Ability','',1,p.name,3)
            if self.can_pay(p,depth_cost) is not None:actions.append(('dark_depths',depths,{}))
        for stage in [q for q in p.battlefield if q.name=="Thespian's Stage"]:
            if self.can_activate_stage(p,stage):actions.append(('stage_copy',stage,{}))
        domri=self.perm(p,'Domri, Anarch of Bolas')
        if domri and domri.metadata.get('activated_turn')!=self.turn_number:
            actions.append(('domri_plus',domri,{}))
            own=[q for q in p.battlefield if self.is_creature_perm(q)]
            enemy=[q for op in self.opponents(p) for q in op.battlefield if self.is_creature_perm(q)]
            if domri.counters.get('loyalty',0)>=2 and own and enemy:actions.append(('domri_minus',domri,{}))
        if p.commander and self.can_pay(p,p.commander.d,commander=True):actions.append(('commander',p.commander,{}))
        for c in p.hand:
            if c.d.is_land:continue
            if c.d.name in {'Animate Dead','Dance of the Dead','Necromancy'} and not any(
                card.d.is_creature for owner in self.players.values() for card in owner.graveyard
            ):
                continue
            if c.d.is_instant and c.d.name not in {'Consider','Opt','Brainstorm','Enlightened Tutor','Vampiric Tutor','Gifts Ungiven','Growth Spiral','Eureka Moment','Drown in Dreams','Crop Rotation','Evacuation','Beast Within','Chaos Warp','Pongify','Breathe Your Last','Utter End',"Hero's Downfall",'Murder','Valorous Stance','Prayer of Binding','Grasp of Fate','Darksteel Mutation','Curse of the Swine','Bulk Up','Unleash Fury','Invigorating Surge','Ram Through','Fling',"Kazuul's Fury // Kazuul's Cliffs",'Heroic Intervention','Inspiring Call','Return of the Wildspeaker','Give In to Violence','Moment of Craving','Deadly Riposte','Devouring Light'}:
                continue
            if c.d.name in {'Bulk Up','Unleash Fury','Invigorating Surge'} and not any(self.is_creature_perm(q) for q in p.battlefield):
                continue
            if c.d.name=='Ram Through' and (not any(self.is_creature_perm(q) for q in p.battlefield) or not any(self.is_creature_perm(q) for op in self.opponents(p) for q in op.battlefield)):
                continue
            if c.d.name=='Devouring Light':
                if self._priority_cast_has_legal_target(p,c,context) and self.devouring_light_payment_plans(p):
                    actions.append(('cast',c,{}))
                continue
            miracle=(p.name=='Reaminatour' and p.miracle_card_uid==c.uid and c.d.is_enchantment)
            x=self.max_x_payable(p,c.d,miracle) if '{X}' in c.d.mana_cost else 0
            if c.d.name=='Nullpriest of Oblivion':
                if self.can_pay(p,c.d) is not None:actions.append(('cast',c,{'kicked':False}))
                kicked_def=sim.CardDef(c.d.name+' kicked','{4}{B}{B}',c.d.type_line,c.d.text,1,p.name,6)
                if any(card.d.is_creature for card in p.graveyard) and self.can_pay(p,kicked_def) is not None:actions.append(('cast',c,{'kicked':True}))
                continue
            if c.d.name=='Fangs of Kalonia':
                if any(self.is_creature_perm(q) for q in p.battlefield) and self.can_pay(p,c.d) is not None:actions.append(('cast',c,{'overload':False}))
                overload_def=sim.CardDef(c.d.name+' overload','{4}{G}{G}',c.d.type_line,c.d.text,1,p.name,6)
                if any(self.is_creature_perm(q) for q in p.battlefield) and self.can_pay(p,overload_def) is not None:actions.append(('cast',c,{'overload':True}))
                continue
            if c.d.name in {'Reveillark','Vesperlark','Mulldrifter'}:
                if self.can_pay(p,c.d) is not None:actions.append(('cast',c,{'evoke':False}))
                evoke_costs={'Reveillark':'{5}{W}','Vesperlark':'{1}{W}','Mulldrifter':'{2}{U}'}
                evoke_def=sim.CardDef(c.d.name+' evoke',evoke_costs[c.d.name],c.d.type_line,c.d.text,1,p.name,sim.mana_value(evoke_costs[c.d.name]))
                if self.can_pay(p,evoke_def) is not None:actions.append(('cast',c,{'evoke':True}))
                continue
            if c.d.name=='Curse of the Swine':
                creature_count=sum(1 for owner in self.players.values() for q in owner.battlefield if self.is_creature_perm(q))
                for value in range(1,min(x,creature_count)+1):
                    if self.can_pay(p,c.d,miracle=miracle,x_value=value) is not None:
                        actions.append(('cast',c,{'miracle':miracle,'x_value':value}))
                continue
            if '{X}' in c.d.mana_cost:
                for value in range(x+1):
                    if self.can_pay(p,c.d,miracle=miracle,x_value=value) is not None:
                        actions.append(('cast',c,{'miracle':miracle,'x_value':value}))
                continue
            if self.can_pay(p,c.d,miracle=miracle,x_value=x) is not None:
                actions.append(('cast',c,{'miracle':miracle,'x_value':x}))
        return actions

    PRIORITY_ACTIVATIONS={
        'fetch_activate','bauble_activate','wave_activate','seer_activate',
        'devotion_activate','houseguard_sac','fallen_sac','top_look','top_draw',
        'dark_depths','stage_copy',
    }
    COUNTER_RESPONSE_CARDS={
        'Swan Song','Fierce Guardianship','Remand','Counterspell','Arcane Denial','Summary Dismissal'
    }

    def has_material_priority_ability(self,d):
        if d.is_planeswalker or 'Activate only as a sorcery' in d.text:return False
        if 'Channel' in d.text:return True
        clauses=[clause.strip() for clause in d.text.replace('\n',' ').split('.') if ':' in clause]
        material_terms=['Sacrifice','Remove a','target','Target','Draw','draw','Create','create',
                        'Return','return','double','gets +','protection','hexproof','indestructible','mill']
        for clause in clauses:
            _,effect=clause.split(':',1)
            if effect.strip().startswith('Add '):continue  # mana abilities do not use the stack
            if any(term in clause for term in material_terms):return True
        return False

    @staticmethod
    def has_flash_timing(c):
        """Return whether a card has flash timing, without mistaking Flashback for Flash."""
        return bool(re.search(r'\bflash\b',c.d.text,re.IGNORECASE))

    def _priority_cast_has_legal_target(self,p,c,context=None):
        """Keep priority prompts to spells the exact referee can legally resolve now."""
        name=c.d.name
        if name in {'Bulk Up','Unleash Fury','Invigorating Surge'}:
            return any(self.is_creature_perm(q) for q in p.battlefield)
        if name=='Ram Through':
            return (any(self.is_creature_perm(q) for q in p.battlefield) and
                    any(self.is_creature_perm(q) and not self.has_hexproof(q)
                        for op in self.opponents(p) for q in op.battlefield))
        if name=='Evacuation':
            return any(self.is_creature_perm(q) for owner in self.players.values() for q in owner.battlefield)
        if name=='Valorous Stance':
            return (any(self.is_creature_perm(q) for q in p.battlefield) or
                    any(self.is_creature_perm(q) and self.toughness(q)>=4 and not self.has_hexproof(q)
                        for op in self.opponents(p) for q in op.battlefield))
        if name in {'Heroic Intervention','Inspiring Call','Return of the Wildspeaker'}:
            return any(self.is_creature_perm(q) for q in p.battlefield)
        if name in {'Fling',"Kazuul's Fury // Kazuul's Cliffs"}:
            return any(self.is_creature_perm(q) for q in p.battlefield)
        if name=='Give In to Violence':
            return any(self.is_creature_perm(q) for owner in self.players.values() for q in owner.battlefield)
        if name=='Moment of Craving':
            return any(self.is_creature_perm(q) and not self.has_hexproof(q) for op in self.opponents(p) for q in op.battlefield)
        if name=='Deadly Riposte':
            return any(self.is_creature_perm(q) and q.tapped and not self.has_hexproof(q) for op in self.opponents(p) for q in op.battlefield)
        if name=='Devouring Light':
            ids=set((context or {}).get('attackers',[]))
            for values in (context or {}).get('blocks',{}).values():ids.update(values)
            return bool(ids)
        if name=='Crop Rotation':
            return (any(sim.is_land_permanent(q) for q in p.battlefield) and
                    any(c2.d.is_land for c2 in p.library))
        if name=='Drown in Dreams':return bool(p.library)
        if name in {'Changing Loyalty','Celestial Armor'}:
            return any(self.is_creature_perm(q) for owner in self.players.values() for q in owner.battlefield)
        if name=='Necromancy':
            return any(c2.d.is_creature for owner in self.players.values() for c2 in owner.graveyard)
        if name in {'Beast Within','Chaos Warp','Pongify','Breathe Your Last','Utter End',
                    "Hero's Downfall",'Murder','Valorous Stance','Prayer of Binding'}:
            for op in self.opponents(p):
                for q in op.battlefield:
                    d=sim.CARDDEF.get(q.name)
                    if self.has_hexproof(q):continue
                    legal=True
                    if name=='Utter End':legal=not sim.is_land_permanent(q)
                    if name in {'Pongify','Murder'}:legal=self.is_creature_perm(q)
                    if name=='Breathe Your Last':legal=self.is_creature_perm(q) or self.is_planeswalker_perm(q)
                    if name=="Hero's Downfall":legal=self.is_creature_perm(q) or self.is_planeswalker_perm(q)
                    if name=='Valorous Stance':legal=self.is_creature_perm(q) and self.toughness(q)>=4
                    if q.name=='Elenda, Saint of Dusk' and c.d.is_instant:legal=False
                    if legal:return True
            return False
        return True

    @read_only_views
    def legal_priority_actions(self,p,timing,context=None,include_held=False):
        """Project supported actions using the actual phase, player and stack."""
        # CR 117.1a: returning priority after a main-phase trigger resolves can
        # permit ordinary spells too. The name of this menu does not restrict
        # every spell to instant speed. Never grant that timing mid-resolution.
        sorcery_timing=(self.phase in {'precombat_main','postcombat_main'} and
                        self.turn_order[self.active_idx]==p.name and not self.stack and
                        not getattr(self,'_generated_trigger_frames',[]) and
                        not getattr(self,'_ltb_trigger_frames',[]))
        actions=self.registered_actions(p,'priority')
        for action in self.legal_main_actions(p,context=context):
            kind,c,kwargs=action
            # Registered priority abilities were projected above.  Sorcery-speed
            # registrations can also appear in legal_main_actions, but they are
            # neither flash permanents nor spells and must not be reinterpreted.
            if kwargs.get('ability_label'):continue
            if kind in self.PRIORITY_ACTIVATIONS:
                if kind=='seer_activate':
                    creatures=sum(1 for q in p.battlefield if self.is_creature_perm(q))
                    material_window=any(key in timing for key in ['end step','upkeep','spell response','after blockers'])
                    if creatures<=1 and not material_window:continue
                if kind in {'bauble_activate','top_look','top_draw','dark_depths','stage_copy'}:
                    if not any(key in timing for key in ['end of','end step','upkeep','spell response']):continue
                actions.append(action);continue
            # The remaining main-action surface also contains sorcery-speed
            # activations (for example Sage of the Maze) whose sources are
            # battlefield Perm objects, not CardObj instances.  Only cast
            # actions can contribute a flash permanent or instant here.
            if kind!='cast':continue
            flash_permanent=c.d.is_permanent and self.has_flash_timing(c)
            if c.d.is_instant or flash_permanent or sorcery_timing:
                if self._priority_cast_has_legal_target(p,c,context):actions.append(action)
        liliana=self.perm(p,'Liliana the Faultless')
        liliana_cost=sim.CardDef('Liliana the Faultless activation','{1}','Ability','',1,p.name,1)
        liliana_targets=[q for q in p.battlefield if q.uid!=(liliana.uid if liliana else None) and
                          (self.is_creature_perm(q) or self.is_planeswalker_perm(q))]
        if liliana and not liliana.tapped and not liliana.summoning_sick and p.hand and liliana_targets and self.can_pay(p,liliana_cost) is not None:
            actions.append(('liliana_activate',liliana,{}))
        represented={c.uid for _,c,_ in actions if c is not None}
        for c in p.hand:
            flash=self.has_flash_timing(c)
            channel='Channel' in c.d.text
            if c.uid in represented or c.d.name in CARD_ABILITIES or c.d.name in self.COUNTER_RESPONSE_CARDS:continue
            if not (c.d.is_instant or flash or channel):continue
            if not channel and self.can_pay(p,c.d) is None:continue
            # A represented targeted spell can be absent from this window simply
            # because it has no legal target (for example Devouring Light outside
            # combat).  That is not an unsupported action and must not fail closed.
            if not channel and not self._priority_cast_has_legal_target(p,c,context):continue
            self.fail_closed_unrepresented_action(p,c,'hand priority action')
        for q in p.battlefield:
            d=sim.CARDDEF.get(q.name)
            if not d or q.uid in represented or q.name in CARD_ABILITIES or q.name in sim.FETCHES or q.name=='Sorin of House Markov' or not self.has_material_priority_ability(d):continue
            if '{T}' in d.text and (q.tapped or (self.is_creature_perm(q) and q.summoning_sick)):continue
            self.fail_closed_unrepresented_action(p,q,'battlefield priority ability')
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION or include_held or self.priority_window_is_responsive(timing,context):return actions
        signature=self.priority_state_signature(p)
        held=p.dungeon.get('priority_holds',{})
        return [a for a in actions if held.get(self.priority_action_key(a))!=signature]

    def fail_closed_unrepresented_action(self,p,obj,context):
        name=obj.d.name if hasattr(obj,'d') else obj.name
        row={'game':self.game_no,'seq':self.seq,'card':name,
             'text':obj.d.text if hasattr(obj,'d') else sim.CARDDEF[name].text,'context':context}
        if row not in self.material_unsupported:self.material_unsupported.append(row)
        raise UnrefereedDecisionError(f'Action construction failed closed: exact handler required for {name} ({context})')

    def priority_action_key(self,action):
        kind,c,_=action
        return f'{kind}:{c.uid if c is not None else "none"}'

    @staticmethod
    def priority_window_is_responsive(timing,context=None):
        return bool(context) or any(
            key in timing for key in
            ['spell response','after attackers','after blockers','triggers on stack'])

    @staticmethod
    def priority_action_source(action):
        return action[1]

    def priority_source_name(self,source):
        if hasattr(source,'d'):return source.d.name
        return source.name

    def priority_source_zone(self,p,source):
        """Return the source's current action-bearing zone by object identity."""
        if source is p.commander:return 'commander'
        for zone in ('hand','battlefield','graveyard','exile'):
            if any(candidate is source for candidate in getattr(p,zone)):
                if zone=='battlefield' and getattr(source,'controller',p.name)!=p.name:return None
                return zone
        return None

    def priority_deadline_player(self,p):
        """Last living seat in turn order before ``p`` takes its next turn."""
        names=self.turn_order;index=names.index(p.name)
        for offset in range(1,len(names)):
            candidate=self.players[names[(index-offset)%len(names)]]
            if not candidate.eliminated:return candidate
        return None

    def priority_end_step_is_deadline(self,p,timing):
        """Whether this is the root end-step window immediately before ``p``."""
        if self.phase!='end_step' or timing!='end step':return False
        active=self.players[self.turn_order[self.active_idx]]
        if active.eliminated:return False
        names=self.turn_order;index=self.active_idx
        for offset in range(1,len(names)+1):
            candidate=self.players[names[(index+offset)%len(names)]]
            if not candidate.eliminated:return candidate is p
        return False

    def priority_deadline_is_still_ahead(self,p,wake,entry):
        """Whether ``wake`` still takes an end step before ``p``'s next turn."""
        names=self.turn_order;active_index=self.active_idx
        pilot_distance=(names.index(p.name)-active_index)%len(names)
        if pilot_distance==0:
            # On the orbit in which the pass was armed (or immediately after a
            # deadline renewal), the rest of the pilot's current/next orbit is
            # still ahead.  On a later pilot turn, a changed deadline was missed.
            return self.turn_number<=entry.wake_not_before_turn
        wake_distance=(names.index(wake.name)-active_index)%len(names)
        if wake_distance==0:return self.phase!='cleanup'
        return wake_distance<pilot_distance

    def arm_priority_seat_snooze(self,p,schedule=None):
        """Suppress optional prompts for one seat until a public timing boundary."""
        wake=self.priority_deadline_player(p)
        if wake is None:
            raise UnrefereedDecisionError('Cannot SNOOZE ALL without a living deadline seat')
        normalized=parse_pass_on_schedule(schedule) if schedule is not None else None
        if normalized:
            key=(normalized['edge'],normalized['phase'])
            current=self.priority_boundary_counts.get(key,0)
            entry=PrioritySeatSnooze(
                armed_turn=self.turn_number,wake_not_before_turn=0,wake_player='',
                wake_edge=normalized['edge'],wake_phase=normalized['phase'],
                requested_occurrences=normalized['occurrences'],
                wake_ordinal=current+normalized['occurrences'])
            detail=(
                f'Optional decision points are snoozed until the '
                f'{normalized["occurrences"]} matching {normalized["edge"]} of '
                f'{normalized["phase"].replace("_"," ")} boundary from now')
            fields={
                'wake_edge':entry.wake_edge,'wake_phase':entry.wake_phase,
                'requested_occurrences':entry.requested_occurrences,
                'wake_ordinal':entry.wake_ordinal,
            }
        else:
            active=self.players[self.turn_order[self.active_idx]]
            already_at_deadline=(self.phase=='end_step' and active is wake)
            entry=PrioritySeatSnooze(
                armed_turn=self.turn_number,
                wake_not_before_turn=self.turn_number+(1 if already_at_deadline else 0),
                wake_player=wake.name)
            detail=(
                f'Optional decision points are snoozed through {wake.name}\'s turn, the '
                f'living turn immediately before {p.name}\'s next turn')
            fields={
                'wake_player':entry.wake_player,
                'wake_not_before_turn':entry.wake_not_before_turn,
            }
        p.dungeon['priority_seat_snooze']=entry
        self.log('priority_seat_snooze_start',p.name,None,detail,**fields)
        return entry

    def clear_priority_seat_snooze(self,p,reason):
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            return self.scheduler.wake(self,p,reason)
        entry=p.dungeon.pop('priority_seat_snooze',None)
        if entry is None:return False
        self.log('priority_seat_snooze_end',p.name,None,reason,
                 wake_player=entry.wake_player or None,wake_edge=entry.wake_edge,
                 wake_phase=entry.wake_phase,wake_ordinal=entry.wake_ordinal or None)
        return True

    def active_priority_seat_snooze(self,p,timing=''):
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            return self.scheduler.table_snoozed(self,p)
        entry=p.dungeon.get('priority_seat_snooze')
        if entry is None:return None
        if entry.wake_edge:
            current=self.priority_boundary_counts.get((entry.wake_edge,entry.wake_phase),0)
            if current>=entry.wake_ordinal:
                self.clear_priority_seat_snooze(
                    p,'The scheduled SNOOZE ALL boundary has arrived')
                return None
            return entry
        current_wake=self.priority_deadline_player(p)
        if current_wake is None:
            self.clear_priority_seat_snooze(p,'No living deadline seat remains')
            return None
        if (self.turn_number>=entry.wake_not_before_turn and
                not self.priority_deadline_is_still_ahead(p,current_wake,entry)):
            self.clear_priority_seat_snooze(
                p,'The default SNOOZE ALL deadline is no longer ahead')
            return None
        if entry.wake_player!=current_wake.name:
            entry.wake_player=current_wake.name
        return entry

    def priority_object_passes(self,p):
        return p.dungeon.setdefault('priority_object_passes',{})

    def _clear_priority_holds_for_uid(self,p,uid):
        holds=p.dungeon.get('priority_holds',{})
        for key in list(holds):
            if key.endswith(':'+uid):holds.pop(key,None)
        if not holds:p.dungeon.pop('priority_holds',None)

    def live_priority_object_passes(self,p):
        """Return actor-owned live entries, pruning stale incarnations first."""
        passes=p.dungeon.get('priority_object_passes',{})
        live=[]
        for uid,entry in list(passes.items()):
            zone=self.priority_source_zone(p,entry.source)
            current=(self.priority_boundary_counts.get((entry.wake_edge,entry.wake_phase),0)
                     if entry.wake_edge else None)
            expired=entry.wake_edge and entry.wake_ordinal<=current
            if zone==entry.source_zone and not expired:
                live.append(entry);continue
            passes.pop(uid,None);self._clear_priority_holds_for_uid(p,uid)
            detail=(
                f'The scheduled boundary already arrived; {entry.source_name} may open priority prompts again'
                if expired else
                f'{entry.source_name} changed zones or controller; it may open priority prompts again'
            )
            self.log('priority_object_pass_end',p.name,entry.source_name,detail,
                     uid=entry.source_uid,wake_edge=entry.wake_edge,
                     wake_phase=entry.wake_phase,wake_ordinal=entry.wake_ordinal or None)
        if not passes:p.dungeon.pop('priority_object_passes',None)
        return sorted(live,key=lambda entry:(entry.source_name.casefold(),entry.source_uid))

    def describe_priority_object_passes(self,p):
        """Serializable actor-private view, intentionally independent of storage layout."""
        rows=[]
        for entry in self.live_priority_object_passes(p):
            if entry.wake_edge:
                current=self.priority_boundary_counts.get((entry.wake_edge,entry.wake_phase),0)
                remaining=max(0,entry.wake_ordinal-current)
                wake={
                    'type':'boundary','edge':entry.wake_edge,'phase':entry.wake_phase,
                    'requested_occurrences':entry.requested_occurrences,
                    'remaining_occurrences':remaining,'wake_ordinal':entry.wake_ordinal,
                }
                description=(f'{remaining} more {entry.wake_edge} of '
                             f'{entry.wake_phase.replace("_"," ")} boundary occurrence(s)')
            else:
                wake={
                    'type':'legacy_end_step','wake_player':entry.wake_player,
                    'wake_not_before_turn':entry.wake_not_before_turn,
                }
                description=f'{entry.wake_player}\'s next qualifying end step'
            rows.append({
                'source_uid':entry.source_uid,'source_name':entry.source_name,
                'source_zone':entry.source_zone,'wake':wake,
                'wake_description':description,
            })
        return rows

    def observe_priority_boundary(self,edge,phase,active_player=None):
        """Advance one public phase/step boundary and wake matching object passes."""
        # Mana pools empty as each step or phase begins.  This includes mana
        # made by a nonactive player while responding during the prior turn;
        # it must never survive into the next draw step or player's turn.
        if edge=='beginning':
            self.empty_mana_pools(f'beginning of {phase.replace("_", " ")}')
        if self.planning_contract>=3:
            self.log('planner_phase_boundary',(active_player.name if active_player else self.turn_order[self.active_idx]),None,
                     'Public phase boundary',edge=edge,boundary_phase=phase)
        schedule=parse_pass_on_schedule({'occurrences':1,'edge':edge,'phase':phase})
        key=(schedule['edge'],schedule['phase'])
        ordinal=self.priority_boundary_counts.get(key,0)+1
        self.priority_boundary_counts[key]=ordinal
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            for pilot in self.players.values():self.scheduler.current(self,pilot)
        for pilot in self.players.values():
            passes=pilot.dungeon.get('priority_object_passes',{})
            for uid,entry in list(passes.items()):
                if self.priority_source_zone(pilot,entry.source)!=entry.source_zone:
                    passes.pop(uid,None)
                    self._clear_priority_holds_for_uid(pilot,uid)
                    self.log('priority_object_pass_end',pilot.name,entry.source_name,
                             f'{entry.source_name} changed zones or controller; it may open priority prompts again',
                             uid=entry.source_uid,wake_edge=entry.wake_edge,wake_phase=entry.wake_phase)
                    continue
                if not entry.wake_edge or (entry.wake_edge,entry.wake_phase)!=key:continue
                remaining=entry.wake_ordinal-ordinal
                if remaining<=0:
                    passes.pop(uid,None)
                    self._clear_priority_holds_for_uid(pilot,uid)
                    self.log('priority_object_pass_end',pilot.name,entry.source_name,
                             f'{edge} of {phase.replace("_"," ")} occurrence {ordinal} arrived; '
                             f'{entry.source_name} may open priority prompts again',
                             uid=entry.source_uid,wake_edge=edge,wake_phase=phase,
                             wake_ordinal=entry.wake_ordinal,active_player=getattr(active_player,'name',None))
                else:
                    self.log('priority_object_pass_tick',pilot.name,entry.source_name,
                             f'{edge} of {phase.replace("_"," ")} occurred; {remaining} matching '
                             'boundary occurrence(s) remain',uid=entry.source_uid,
                             wake_edge=edge,wake_phase=phase,wake_ordinal=entry.wake_ordinal,
                             remaining=remaining,active_player=getattr(active_player,'name',None))
            if not passes:pilot.dungeon.pop('priority_object_passes',None)
            seat_snooze=pilot.dungeon.get('priority_seat_snooze')
            if seat_snooze is None:continue
            scheduled=(
                seat_snooze.wake_edge and
                (seat_snooze.wake_edge,seat_snooze.wake_phase)==key and
                ordinal>=seat_snooze.wake_ordinal
            )
            default=(
                not seat_snooze.wake_edge and edge=='end' and phase=='end_step'
                and getattr(active_player,'name',None)==seat_snooze.wake_player
                and self.turn_number>=seat_snooze.wake_not_before_turn
            )
            if scheduled or default:
                self.clear_priority_seat_snooze(
                    pilot,
                    f'{edge} of {phase.replace("_"," ")} arrived; normal decision prompts resume')
        return ordinal

    def empty_mana_pools(self,boundary):
        """Empty every player's ordinary and Domri-generated mana at a boundary."""
        for player in self.players.values():
            floating=list(player.dungeon.pop('floating_mana',[]))
            domri=list(player.dungeon.pop('domri_floating',[]))
            if floating or domri:
                self.log('mana_pool_empty',player.name,None,
                         f'Mana pool empties at {boundary}',
                         floating=floating,domri_floating=domri,boundary=boundary)

    def clear_priority_object_pass(self,p,source,reason):
        passes=p.dungeon.get('priority_object_passes',{})
        uid=getattr(source,'uid',None);entry=passes.get(uid)
        if not entry or entry.source is not source:return False
        passes.pop(uid,None)
        self._clear_priority_holds_for_uid(p,uid)
        if not passes:p.dungeon.pop('priority_object_passes',None)
        self.log('priority_object_pass_end',p.name,entry.source_name,reason,
                 uid=entry.source_uid,wake_player=entry.wake_player,
                 wake_edge=entry.wake_edge,wake_phase=entry.wake_phase,
                 wake_ordinal=entry.wake_ordinal or None)
        return True

    def wake_priority_object_passes(self,p,reason):
        """Cancel every live object pass for a player facing a new threat."""
        for entry in list(self.live_priority_object_passes(p)):
            self.clear_priority_object_pass(p,entry.source,reason)

    def wake_passes_for_opposing_spell_targets(self,caster,card,targets):
        """Wake each targeted opponent's passed-on objects once a spell is cast."""
        threatened=[]

        def visit(value):
            if value in self.players.values():
                if value is not caster and value not in threatened:threatened.append(value)
                return
            controller=getattr(value,'controller',None)
            if controller in self.players:
                player=self.players[controller]
                if player is not caster and player not in threatened:threatened.append(player)
                return
            if isinstance(value,(tuple,list)):
                for item in value:visit(item)

        for target in targets:visit(target)
        for player in threatened:
            if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
                self.scheduler.targeted(self,player)
                continue
            self.wake_priority_object_passes(
                player,
                f'{card.d.name} controlled by {caster.name} targeted {player.name} or a permanent they control')

    def reschedule_priority_object_pass(self,p,source,schedule,control_id=None):
        """Replace one live deadline without making its source prompt-active."""
        uid=getattr(source,'uid',None);passes=p.dungeon.get('priority_object_passes',{})
        previous=passes.get(uid)
        if (previous is None or previous.source is not source or
                self.priority_source_zone(p,source)!=previous.source_zone):
            raise UnrefereedDecisionError('Cannot reschedule a stale or unsnoozed priority object')
        normalized=parse_pass_on_schedule(schedule);key=(normalized['edge'],normalized['phase'])
        current=self.priority_boundary_counts.get(key,0)
        replacement=PriorityObjectPass(
            source=source,source_uid=source.uid,source_name=self.priority_source_name(source),
            source_zone=previous.source_zone,armed_turn=self.turn_number,wake_not_before_turn=0,
            wake_player='',wake_edge=normalized['edge'],wake_phase=normalized['phase'],
            requested_occurrences=normalized['occurrences'],
            wake_ordinal=current+normalized['occurrences'])
        passes[uid]=replacement;self._clear_priority_holds_for_uid(p,uid)
        self.log(
            'priority_object_pass_reschedule',p.name,replacement.source_name,
            f'{replacement.source_name} remains passed on and will wake after '
            f'{normalized["occurrences"]} matching {normalized["edge"]} of '
            f'{normalized["phase"].replace("_"," ")} boundary occurrence(s)',
            uid=uid,control_id=control_id,old_wake_edge=previous.wake_edge,
            old_wake_phase=previous.wake_phase,old_wake_ordinal=previous.wake_ordinal or None,
            wake_edge=replacement.wake_edge,wake_phase=replacement.wake_phase,
            requested_occurrences=replacement.requested_occurrences,
            wake_ordinal=replacement.wake_ordinal)
        return replacement

    def apply_priority_object_pass_control(self,p,control):
        """Apply one validated replay action atomically to the actor's live entries."""
        try:control=validate_pass_on_control(control)
        except ValueError as exc:
            raise UnrefereedDecisionError(f'Invalid PASS ON control: {exc}') from exc
        if control['control_id'] in self.consumed_pass_on_controls:
            raise UnrefereedDecisionError('A PASS ON control was replayed more than once')
        if control['actor']!=p.name:
            raise UnrefereedDecisionError('A pilot cannot manage another pilot\'s PASS ON entries')
        passes=p.dungeon.get('priority_object_passes',{})
        resolved=[]
        for uid in control['source_uids']:
            entry=passes.get(uid)
            if (entry is None or entry.source_uid!=uid or
                    self.priority_source_zone(p,entry.source)!=entry.source_zone):
                raise UnrefereedDecisionError(
                    f'PASS ON control targets stale or unavailable object UID {uid}')
            resolved.append(entry)
        if control['action']=='reschedule':
            self.reschedule_priority_object_pass(
                p,resolved[0].source,control['schedule'],control['control_id'])
        else:
            for entry in resolved:
                self.clear_priority_object_pass(
                    p,entry.source,
                    f'{entry.source_name} was explicitly unsnoozed by its pilot '
                    f'(control {control["control_id"]})')
        self.consumed_pass_on_controls.add(control['control_id'])
        return True

    def active_priority_object_passes(self,p,timing):
        """Return live object passes, expiring deadlines and zone changes first."""
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            return self.scheduler.object_schedules(self,p)
        passes=p.dungeon.get('priority_object_passes',{})
        if not passes:return []
        deadline=self.priority_end_step_is_deadline(p,timing)
        current_wake=self.priority_deadline_player(p)
        active=[]
        for uid,entry in list(passes.items()):
            zone=self.priority_source_zone(p,entry.source)
            if zone!=entry.source_zone:
                passes.pop(uid,None)
                self._clear_priority_holds_for_uid(p,uid)
                self.log('priority_object_pass_end',p.name,entry.source_name,
                         f'{entry.source_name} changed zones or controller; it may open priority prompts again',
                         uid=entry.source_uid,wake_player=entry.wake_player)
                continue
            if entry.wake_edge:
                active.append(entry)
                continue
            if current_wake is not None:
                previous=entry.wake_player
                if (self.turn_number>=entry.wake_not_before_turn and
                        not self.priority_deadline_is_still_ahead(p,current_wake,entry)):
                    passes.pop(uid,None)
                    self._clear_priority_holds_for_uid(p,uid)
                    self.log('priority_object_pass_end',p.name,entry.source_name,
                             f'The scheduled or replacement deadline is no longer ahead; {entry.source_name} may open priority prompts again',
                             uid=entry.source_uid,wake_player=previous,
                             replacement_wake_player=current_wake.name)
                    continue
                if previous!=current_wake.name:
                    entry.wake_player=current_wake.name
                    self.log('priority_object_pass_deadline_change',p.name,entry.source_name,
                             f'{entry.source_name} will now ask again at {current_wake.name}\'s end step because the living turn order changed',
                             uid=entry.source_uid,old_wake_player=previous,wake_player=current_wake.name)
            if deadline and self.turn_number>=entry.wake_not_before_turn:
                passes.pop(uid,None)
                self._clear_priority_holds_for_uid(p,uid)
                self.log('priority_object_pass_end',p.name,entry.source_name,
                         f'The end step before {p.name}\'s next turn has arrived; {entry.source_name} may open priority prompts again',
                         uid=entry.source_uid,wake_player=entry.wake_player)
                continue
            active.append(entry)
        if not passes:p.dungeon.pop('priority_object_passes',None)
        return active

    @staticmethod
    def priority_action_is_object_passed(action,entries):
        source=action[1]
        return any(entry.source is source for entry in entries)

    def execute_bridged_priority_action(self,p,action,context=None):
        """Execute an ordinary action selected from a specialized response list."""
        self.clear_specialized_priority_passes()
        source=action[1]
        if source is not None:
            self.clear_priority_object_pass(
                p,source,f'{self.priority_source_name(source)} was selected; its object pass is cancelled')
        if action[0]=='cast':p.dungeon['cast_priority_context']=context or {}
        started_at=self.seq
        try:ok=self.execute_refereed_action(p,action)
        finally:
            if action[0]=='cast':p.dungeon.pop('cast_priority_context',None)
        countered=any(event['seq']>started_at and event['type'] in {'ability_countered','counter_abilities'}
                      for event in self.events)
        if ok is False and not countered:
            raise UnrefereedDecisionError(
                'Advertised bridged priority action became illegal: '+self.priority_action_label(p,action))
        return ok

    def arm_priority_object_pass(self,p,source,timing,schedule=None):
        zone=self.priority_source_zone(p,source)
        wake=self.priority_deadline_player(p)
        if zone is None or wake is None:
            raise UnrefereedDecisionError('Cannot pass on an object without a live source and deadline')
        active=self.players[self.turn_order[self.active_idx]]
        # Any response nested inside the predecessor's end step is already at
        # this orbit's deadline, even when its local timing label is "spell
        # response" rather than the root "end step" window.
        already_at_deadline=(self.phase=='end_step' and active is wake)
        normalized=parse_pass_on_schedule(schedule) if schedule is not None else None
        if normalized:
            key=(normalized['edge'],normalized['phase'])
            current=self.priority_boundary_counts.get(key,0)
            entry=PriorityObjectPass(
                source=source,source_uid=source.uid,source_name=self.priority_source_name(source),
                source_zone=zone,armed_turn=self.turn_number,wake_not_before_turn=0,
                wake_player='',wake_edge=normalized['edge'],wake_phase=normalized['phase'],
                requested_occurrences=normalized['occurrences'],
                wake_ordinal=current+normalized['occurrences'])
            detail=(
                f'{entry.source_name} will not open priority prompts on its own until the '
                f'{normalized["occurrences"]} matching {normalized["edge"]} of '
                f'{normalized["phase"].replace("_"," ")} boundary from now; it remains available '
                'whenever another object opens a prompt')
            log_fields={
                'wake_edge':entry.wake_edge,'wake_phase':entry.wake_phase,
                'requested_occurrences':entry.requested_occurrences,
                'wake_ordinal':entry.wake_ordinal,
            }
        else:
            # Compatibility for callers and legacy tapes written before configurable schedules.
            entry=PriorityObjectPass(
                source=source,source_uid=source.uid,source_name=self.priority_source_name(source),
                source_zone=zone,armed_turn=self.turn_number,
                wake_not_before_turn=self.turn_number+(1 if already_at_deadline else 0),
                wake_player=wake.name)
            detail=(
                f'{entry.source_name} will not open priority prompts on its own until '
                f'{wake.name}\'s end step before {p.name}\'s next turn; it remains available '
                'whenever another object opens a prompt')
            log_fields={'wake_player':wake.name,'wake_not_before_turn':entry.wake_not_before_turn}
        self.priority_object_passes(p)[source.uid]=entry
        self._clear_priority_holds_for_uid(p,source.uid)
        self.log('priority_object_pass_start',p.name,entry.source_name,
                 detail,uid=entry.source_uid,source_zone=zone,**log_fields)
        return entry

    def priority_pass_on_option(self,p,actions):
        """Build the replay-compatible objectwise pass option for this surface."""
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:return None
        sources=[]
        for action in actions:
            source=self.priority_action_source(action)
            if source is None:
                if self.decision_surface_revision<PASSING_ACCELERATION_SURFACE_REVISION:
                    return None
                continue
            if not any(candidate is source for candidate in sources):sources.append(source)
        wake=self.priority_deadline_player(p)
        if wake is None:return None
        if self.decision_surface_revision>=PASSING_ACCELERATION_SURFACE_REVISION:
            if not sources:return None
            return ('pass_on_priority_objects',None,{'sources':sources})
        if len(sources)!=1:return None
        return ('pass_on_priority_object',sources[0],{'wake_player':wake.name})

    def priority_pass_on_request_metadata(self,p,pass_on,option_index):
        if (
            self.decision_surface_revision<PASSING_ACCELERATION_SURFACE_REVISION
            or not pass_on or pass_on[0]!='pass_on_priority_objects'
        ):return None
        return {'pass_on_batch':{
            'schema':1,'option_index':option_index,
            'sources':[
                {'uid':source.uid,'name':self.priority_source_name(source),
                 'zone':self.priority_source_zone(p,source)}
                for source in pass_on[2]['sources']
            ],
            'help':(
                'Choose PASS ON OBJECTS and attach one or more repeated --pass-on '
                '"OBJECT_UID=N beginning|end of PHASE" fields in the same answer. '
                'Each listed object gets its own wake schedule.'
            ),
        }}

    def arm_priority_object_pass_batch(self,p,pass_on,timing,payload):
        """Validate a batched choice completely before arming any object passes."""
        if pass_on[0]!='pass_on_priority_objects':
            raise UnrefereedDecisionError('Invalid batched PASS ON action')
        if (
            not isinstance(payload,dict) or set(payload)!={'schema','entries'}
            or payload.get('schema')!=1
        ):
            raise UnrefereedDecisionError('Batched PASS ON payload is missing or unsupported')
        raw_entries=payload.get('entries')
        if not isinstance(raw_entries,list) or not raw_entries:
            raise UnrefereedDecisionError('Batched PASS ON requires at least one object schedule')
        try:entries=[parse_pass_on_batch_entry(entry) for entry in raw_entries]
        except ValueError as exc:
            raise UnrefereedDecisionError(f'Invalid batched PASS ON: {exc}') from exc
        uids=[entry['source_uid'] for entry in entries]
        if len(uids)!=len(set(uids)):
            raise UnrefereedDecisionError('Batched PASS ON cannot schedule one object twice')
        allowed={source.uid:source for source in pass_on[2].get('sources',[])}
        if any(uid not in allowed for uid in uids):
            raise UnrefereedDecisionError('Batched PASS ON names an unavailable object UID')
        resolved=[(allowed[entry['source_uid']],entry['schedule']) for entry in entries]
        for source,schedule in resolved:
            if self.priority_source_zone(p,source) is None:
                raise UnrefereedDecisionError('Batched PASS ON source is no longer live')
        for source,schedule in resolved:
            self.arm_priority_object_pass(p,source,timing,schedule)
        return len(resolved)

    def priority_state_signature(self,p):
        hand=tuple(sorted(c.uid for c in p.hand))
        battlefield=tuple(sorted((q.uid,q.tapped,q.summoning_sick,tuple(sorted(q.counters.items()))) for q in p.battlefield))
        graveyard=tuple(sorted(c.uid for c in p.graveyard))
        return repr((p.life,p.treasures,hand,battlefield,graveyard))

    def priority_action_label(self,p,a):
        kind,c,kw=a
        if kind=='concede':return 'CONCEDE — leave this game immediately'
        if kind=='autopass_stack':return 'AUTOPASS current stack; wake if another spell is cast'
        if kind=='wake_priority_object':
            return (f'WAKE {self.priority_source_name(c)} [{c.uid}] — make it available '
                    'in this priority window')
        if kind=='pass_on_priority_object':
            return f'PASS ON {self.priority_source_name(c)} [{c.uid}] — then set a wake boundary'
        if kind=='pass_on_priority_objects':
            count=len(kw.get('sources') or [])
            return f'PASS ON OBJECTS — schedule one or more of {count} eligible source(s) in this answer'
        if kind=='propose_combo_loop':
            if kw.get('planner_proposal_id'):return 'REVIEW PLANNER COMBO — submit the supplied proof for adjudication if valid now'
            return 'PROPOSE COMBO LOOP FOR ADJUDICATION — put the loop/proof and claimed outcome in rationale'
        if kind=='cast':return f'CAST {c.d.name} {c.d.mana_cost}'
        if kw.get('ability_label'):return f'ACTIVATE {c.d.name if hasattr(c,"d") else c.name} — {kw["ability_label"]}'
        if kind=='priority_rules_checkpoint':return ('CAST ' if kw.get('zone')=='hand' else 'ACTIVATE ')+(c.d.name if hasattr(c,'d') else c.name)
        labels={
            'seer_activate':'ACTIVATE Viscera Seer - sacrifice a creature, scry 1',
            'devotion_activate':'ACTIVATE Fanatical Devotion - sacrifice a creature, regenerate target creature',
            'houseguard_sac':'ACTIVATE Dimir House Guard - sacrifice a creature, regenerate House Guard',
            'fallen_sac':'ACTIVATE Fallen Ideal - sacrifice a creature, +2/+1',
            'bauble_activate':"ACTIVATE Wayfarer's Bauble - {2}, sacrifice, fetch a basic tapped",
            'top_look':"ACTIVATE Sensei's Divining Top - {1}, reorder top three",
            'top_draw':"ACTIVATE Sensei's Divining Top - tap, draw, put Top on library",
            'stage_copy':"ACTIVATE Thespian's Stage - {2}, tap: copy a land",
            'liliana_activate':'ACTIVATE Liliana the Faultless - {1}, tap, discard: give another creature or planeswalker hexproof',
        }
        if kind=='wave_activate':return f'ACTIVATE Parallax Wave ({c.counters.get("fade",0)} fade counters)'
        if kind=='fetch_activate':return f'ACTIVATE {c.name} - pay 1 life, sacrifice, fetch'
        if kind=='dark_depths':return f'ACTIVATE Dark Depths - {{3}}, remove an ice counter ({c.counters.get("ice",0)} remaining)'
        return labels.get(kind,kind)

    def priority_prompt_action_label(self,p,action):
        label=self.priority_action_label(p,action)
        source=action[1]
        if source is None or action[0] in {
            'autopass_stack','pass_on_priority_object','pass_on_priority_objects'
        }:return label
        return self.priority_source_prompt_label(p,source,label)

    def priority_concede_action(self):
        """Return the revised universal control for an already-open priority prompt.

        It is deliberately not part of ``legal_priority_actions``: conceding may
        never be the reason a player with no modeled action receives an LLM call.
        """
        if self.decision_surface_revision<2:return None
        return ('concede',None,{})

    def concede_from_priority(self,p,timing):
        """Apply a replayable concession selected on a priority-like surface."""
        self.clear_specialized_priority_passes()
        self.eliminate(p,f'{p.name} conceded during {timing}')
        return True

    def priority_source_prompt_label(self,p,source,label):
        """Annotate a visible action whose source is currently passed on."""
        entry=p.dungeon.get('priority_object_passes',{}).get(getattr(source,'uid',None))
        if entry and entry.source is source:
            if entry.wake_edge:
                current=self.priority_boundary_counts.get((entry.wake_edge,entry.wake_phase),0)
                remaining=max(0,entry.wake_ordinal-current)
                label+=(f' [passed on {entry.source_uid}; wakes after {remaining} more '
                        f'{entry.wake_edge} of {entry.wake_phase.replace("_"," ")}]')
            else:label+=f' [passed on {entry.source_uid}]'
        return label

    def priority_autopasses_current_stack(self,p):
        """Honor a whole-stack pass, clearing it on empty stack or new spell."""
        if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
            return self.scheduler.stack_snoozed(self,p)
        autopass=p.dungeon.get('autopass_stack')
        if not autopass:return False
        if not self.stack:
            p.dungeon.pop('autopass_stack',None)
            self.log('autopass_stack_end',p.name,None,
                     'The current stack became empty; normal priority prompts resume')
            return False
        if autopass.get('spell_cast_epoch')!=self.spell_cast_epoch:
            p.dungeon.pop('autopass_stack',None)
            self.log('autopass_stack_end',p.name,None,
                     'A new spell was cast; normal priority prompts resume')
            return False
        return True

    def start_priority_stack_autopass(self,p,detail=None):
        p.dungeon['autopass_stack']={'spell_cast_epoch':self.spell_cast_epoch}
        self.log('autopass_stack_start',p.name,None,
                 detail or 'Autopassing the current stack; a new spell will restore normal priority prompts')

    def priority_stack_signature(self):
        """Stable-enough identity for one uninterrupted stack configuration."""
        return tuple(
            (item.get('uid'),item.get('actor'),item.get('card'),item.get('ability_kind'),
             item.get('trigger_event'),item.get('trigger_index'))
            for item in self.stack if isinstance(item,dict))

    def mark_specialized_priority_pass(self,p):
        p.dungeon['specialized_priority_pass']={
            'stack_signature':self.priority_stack_signature(),
            'spell_cast_epoch':self.spell_cast_epoch,
        }

    def specialized_priority_pass_is_current(self,p):
        marker=p.dungeon.get('specialized_priority_pass')
        return bool(marker and
                    marker.get('stack_signature')==self.priority_stack_signature() and
                    marker.get('spell_cast_epoch')==self.spell_cast_epoch)

    def consume_specialized_priority_pass(self,p):
        current=self.specialized_priority_pass_is_current(p)
        p.dungeon.pop('specialized_priority_pass',None)
        return current

    def clear_specialized_priority_passes(self):
        for player in self.players.values():player.dungeon.pop('specialized_priority_pass',None)

    def player_has_unsuppressed_general_priority(self,p,timing,context=None):
        """Whether ``p`` still needs the ordinary priority surface this round."""
        if p.eliminated or self.specialized_priority_pass_is_current(p):return False
        if self.active_priority_seat_snooze(p,timing):return False
        if self.priority_autopasses_current_stack(p):return False
        actions=self.legal_priority_actions(p,timing,context,include_held=True)
        object_passes=self.active_priority_object_passes(p,timing)
        return any(not self.priority_action_is_object_passed(action,object_passes)
                   for action in actions)

    def _combo_proposal_request(self,p,proposal_text,proposal_decision_id,consents):
        identity={
            'game':self.game_no,'seed':self.seed,'proposal_decision_id':proposal_decision_id,
            'actor':p.name,'proposal':proposal_text,
        }
        suffix=hashlib.sha256(
            json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
        ).hexdigest()[:16]
        proposal_id=f'G{self.game_no:02d}-P-{proposal_decision_id}-{suffix}'
        request={
            'schema':1,'proposal_id':proposal_id,'game':self.game_no,'seed':self.seed,
            'proposal_decision_id':proposal_decision_id,'actor':p.name,
            'proposal':proposal_text,'consents':consents,
            'consent_standard':(
                'Each YES means that pilot reports no disruption or interaction capable of '
                'stopping the demonstrated loop; consent is not a rules ruling.'),
            'adjudicator_task':(
                'Independently verify the demonstration against the rules and current public '
                'state. Approve only a consistent shortcut and encode only its resulting state '
                'changes with the closed operation schema.'),
            'public_state':self.redacted_snapshot(p.name),
            'operation_schema':{
                'damage_player':{'player':'pilot name','amount':'positive integer or infinite'},
                'set_life':{'player':'pilot name','value':'nonnegative integer or infinite'},
                'bounce_permanents':{
                    'players':'all, opponents, or pilot-name list',
                    'uids':'optional exact permanent UID list; omit for every permanent in scope',
                },
            },
        }
        request['request_sha256']=hashlib.sha256(
            json.dumps(request,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
        ).hexdigest()
        return request

    def _bounce_combo_permanents(self,p,operation,reason):
        players=operation['players']
        if players=='all':controllers=[owner for owner in self.players.values() if not owner.eliminated]
        elif players=='opponents':controllers=self.opponents(p)
        else:controllers=[self.players[name] for name in players if not self.players[name].eliminated]
        uid_filter=operation.get('uids')
        requested=set(uid_filter or []);targets=[]
        for controller in controllers:
            for permanent in list(controller.battlefield):
                if uid_filter is None or permanent.uid in requested:targets.append((controller,permanent))
        found={permanent.uid for _,permanent in targets}
        if requested-found:
            raise UnrefereedDecisionError(
                'Combo adjudication names a permanent outside its live bounce scope: '+
                ', '.join(sorted(requested-found)))
        commander_choices={}
        for controller,permanent in targets:
            owner=self.players[permanent.owner]
            if permanent.uid!=owner.dungeon.get('commander_uid'):continue
            commander_choices[permanent.uid]=self._request_decision(
                'combo_bounce_commander_zone',owner,
                f'The approved combo shortcut would return {permanent.name} to your hand. '
                'Put it in the command zone instead?',
                [False,True],lambda value:'return to hand' if not value else 'put in command zone')
        generated=[];frames=self.__dict__.setdefault('_ltb_trigger_frames',[]);existing=bool(frames)
        if not existing:frames.append(generated)
        moved=[];command_zone=[]
        try:
            for controller,permanent in targets:
                if permanent in controller.battlefield:
                    self.leave_battlefield(controller,permanent,'hand',reason)
                    moved.append(permanent.uid)
                    if commander_choices.get(permanent.uid):
                        owner=self.players[permanent.owner]
                        card=next((card for card in owner.hand if card.uid==permanent.uid),None)
                        if card:
                            owner.hand.remove(card);owner.commander=card
                            command_zone.append(permanent.uid)
                            self.log('commander_zone',owner.name,permanent.name,
                                     'Approved combo bounce: commander-zone replacement')
        finally:
            if not existing:frames.pop()
        if generated:
            self.resolve_simultaneous_triggers(
                'combo adjudication returns permanents to hand',generated,
                starter=self.players[self.turn_order[self.active_idx]])
        return moved,command_zone

    def apply_combo_adjudication(self,p,request,response):
        try:
            response=validate_combo_adjudication_response(
                response,expected_proposal_id=request['proposal_id'],
                expected_request_sha256=request['request_sha256'],
                known_pilots=tuple(self.players))
        except ComboAdjudicationValidationError as exc:
            raise UnrefereedDecisionError('Invalid combo adjudication: '+str(exc)) from exc
        verdict=response['verdict']
        if verdict!='approved':
            self.log('combo_adjudication_rejected',p.name,None,response['public_summary'],
                     proposal_id=request['proposal_id'],verdict=verdict)
            return True
        reason='approved combo shortcut: '+response['public_summary']
        applied=[]
        for operation in response['operations']:
            kind=operation['op']
            if kind=='damage_player':
                target=self.players[operation['player']]
                if target.eliminated:raise UnrefereedDecisionError('Combo damage target is already eliminated')
                amount=operation['amount']
                self.log('combo_adjudication_operation',p.name,None,
                         f'{target.name} is dealt {amount} damage by the approved combo shortcut',
                         proposal_id=request['proposal_id'],operation=kind,
                         target=target.name,amount=amount)
                if amount==COMBO_INFINITE:
                    target.dungeon.pop('adjudicated_infinite_life',None)
                    self.lose_life(target,max(1,target.life),reason)
                else:self.lose_life(target,amount,reason)
                applied.append({'op':kind,'player':target.name,'amount':amount})
            elif kind=='set_life':
                target=self.players[operation['player']]
                if target.eliminated:raise UnrefereedDecisionError('Combo life target is already eliminated')
                value=operation['value']
                if value==COMBO_INFINITE:
                    target.life=COMBO_MAX_INTEGER
                    target.dungeon['adjudicated_infinite_life']={
                        'proposal_id':request['proposal_id'],'rules_basis':response['rules_basis']}
                else:
                    target.dungeon.pop('adjudicated_infinite_life',None);target.life=value
                self.log('combo_adjudication_operation',p.name,None,
                         f'{target.name} life is set to {value}',proposal_id=request['proposal_id'],
                         operation=kind,target=target.name,value=value)
                if value!=COMBO_INFINITE and value<=0:self.eliminate(target,reason)
                applied.append({'op':kind,'player':target.name,'value':value})
            elif kind=='bounce_permanents':
                moved,command_zone=self._bounce_combo_permanents(p,operation,reason)
                self.log('combo_adjudication_operation',p.name,None,
                         f'Returned {len(moved)} permanent(s); {len(command_zone)} commander(s) '
                         'used the command-zone replacement',proposal_id=request['proposal_id'],
                         operation=kind,uids=moved,command_zone_uids=command_zone)
                applied.append({'op':kind,'uids':moved,'command_zone_uids':command_zone})
        self.check_sba();self.assert_invariants('combo_adjudication_'+request['proposal_id'])
        self.log('combo_adjudication_approved',p.name,None,response['public_summary'],
                 proposal_id=request['proposal_id'],operations=applied)
        return True

    def propose_combo_loop(self,p,proposal_text,proposal_decision_id):
        proposal_text=' '.join(str(proposal_text).split())
        if not proposal_text:
            raise UnrefereedDecisionError(
                'A combo proposal requires the loop/proof and claimed outcome in the decision rationale')
        self.log('combo_loop_proposed',p.name,None,proposal_text,
                 proposal_decision_id=proposal_decision_id)
        consents=[]
        for opponent in self.opponents(p):
            consent=self._request_decision(
                'combo_consent',opponent,
                f'{p.name} demonstrates this combo shortcut: {proposal_text}\n'
                'Consent only if you have no disruption or interaction capable of stopping it.',
                [True,False],
                lambda value:(
                    'YES — no disruption or interaction capable of stopping the demonstrated loop'
                    if value else
                    'NO — I can interact; cancel the shortcut and return to normal priority'),
                gameplan_access=True)
            consents.append({
                'pilot':opponent.name,'consent':bool(consent),
                'decision_id':getattr(self,'_last_decision_id',None),
                'rationale':getattr(self,'_last_decision_rationale',''),
            })
        if not all(row['consent'] for row in consents):
            declined=[row['pilot'] for row in consents if not row['consent']]
            self.log('combo_consent_declined',p.name,None,
                     'Combo shortcut cancelled; normal priority resumes',declined_by=declined)
            return True
        request=self._combo_proposal_request(
            p,proposal_text,proposal_decision_id,consents)
        response=self.combo_adjudications.get(request['proposal_id'])
        if response is None:raise NeedComboAdjudication(request)
        self.consumed_combo_adjudications.add(request['proposal_id'])
        return self.apply_combo_adjudication(p,request,response)

    def execute_refereed_action(self,p,action):
        kind,c,kwargs=action
        def activated(callback):
            prior=self.__dict__.get('_activated_ability_decision_root')
            root=getattr(self,'_last_decision_id',None)
            self._activated_ability_decision_root={
                'decision_id':root or (
                    prior.get('decision_id') if isinstance(prior,dict) else prior),
                'actor':p.name,
            }
            try:return callback()
            finally:
                if prior is None:self.__dict__.pop('_activated_ability_decision_root',None)
                else:self._activated_ability_decision_root=prior
        if kind=='concede':return self.concede_from_priority(p,self.phase)
        if kind=='propose_combo_loop':
            if kwargs.get('planner_proposal_id'):self.used_combo_proposals.add(kwargs['planner_proposal_id'])
            return self.propose_combo_loop(
                p,kwargs.get('proposal_text',''),kwargs.get('proposal_decision_id',''))
        if kind=='cast':return self.cast(p,c,**kwargs)
        if kind=='commander':return self.commander_cast(p)
        if kind=='transmute':return activated(lambda:self.transmute_house_guard(p,c))
        if kind=='nightmare':return activated(lambda:self.activate_nightmare(p))
        if kind=='escape_uro':return self.escape_uro(p,c)
        if kind=='wave_activate':return activated(lambda:self.activate_wave_refereed(p))
        if kind=='seer_activate':return activated(lambda:self.activate_seer_refereed(p))
        if kind=='devotion_activate':return activated(lambda:self.activate_devotion_refereed(p))
        if kind=='houseguard_sac':return activated(lambda:self.activate_houseguard_refereed(p))
        if kind=='fallen_sac':return activated(lambda:self.activate_fallen_refereed(p))
        if kind=='sage_animate':return activated(lambda:self.activate_sage_refereed(p))
        if kind=='fetch_activate':return activated(lambda:self.crack_fetch(p,c))
        if kind=='bauble_activate':return activated(lambda:self.activate_bauble_refereed(p,c))
        if kind=='top_look':return activated(lambda:self.activate_top_look_refereed(p,c))
        if kind=='top_draw':return activated(lambda:self.activate_top_draw_refereed(p,c))
        if kind=='domri_plus':return activated(lambda:self.activate_domri_plus(p,c))
        if kind=='domri_minus':return activated(lambda:self.activate_domri_minus(p,c))
        if kind=='dark_depths':return activated(lambda:self.activate_dark_depths(p,c))
        if kind=='stage_copy':return activated(lambda:self.activate_stage_refereed(p,c))
        if kind=='liliana_activate':return activated(lambda:self.activate_liliana_refereed(p,c))
        if kind in {registration.kind for rows in CARD_ABILITIES.values() for registration in rows}:
            return activated(lambda:self.activate_registered_ability(p,c,kind,**kwargs))
        if kind=='priority_rules_checkpoint':
            name=c.d.name if hasattr(c,'d') else c.name
            self.material_unsupported.append({'game':self.game_no,'seq':self.seq,'card':name,
                                              'text':c.d.text if hasattr(c,'d') else sim.CARDDEF[name].text,
                                              'context':'priority action selected'})
            raise UnrefereedDecisionError(f'Exact instant-speed referee handler required for {name}')
        raise UnrefereedDecisionError('Unknown refereed action '+kind)

    def scheduler_suppresses_priority(self,p,timing,actions):
        if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION:return False
        table=self.scheduler.table_snoozed(self,p)
        stack=self.scheduler.stack_snoozed(self,p)
        if not table and not stack:return False
        if actions:
            self.log('scheduler_suppressed',p.name,None,timing,
                     mode='snooze_table' if table else self.scheduler.current(self,p).directive['mode'],
                     legal_options=[self.priority_action_label(p,action) for action in actions],
                     whole_decision_suppressed=True)
        return True

    def priority_window(self,starter,timing,context=None):
        """Run APNAP priority; an action clears all passes and priority circles again."""
        if self.winner:return False
        # A cast-trigger can resolve while the spell that caused it is still
        # underneath that trigger on the stack.  Once the trigger is gone,
        # players must be offered the exact counterspell response surface
        # before the underlying spell can resolve.  The ordinary priority
        # projection intentionally excludes counterspells because their target
        # and alternate-cost handling live in ``react_to_spell``.
        if self.stack and ': after ' in timing and timing.endswith(' trigger resolves'):
            top=self.stack[-1]
            if (isinstance(top,dict) and top.get('uid') and top.get('card') and
                    not (top.get('ability_kind') or top.get('trigger_event')) and
                    top['uid'] not in self.__dict__.setdefault('_completed_counter_windows',set())):
                definition=sim.CARDDEF.get(top['card'])
                caster=self.players.get(top.get('actor'))
                if definition is not None and caster is not None:
                    if self.react_to_spell(caster,sim.CardObj(top['uid'],definition)):
                        self.__dict__.setdefault(
                            '_countered_during_cast_trigger',set()).add(top['uid'])
                        return True
                    self.__dict__.setdefault(
                        '_completed_counter_windows',set()).add(top['uid'])
        if not self.stack:
            for player in self.players.values():
                if player.dungeon.pop('autopass_stack',None) is not None:
                    self.log('autopass_stack_end',player.name,None,'Stack is empty; normal priority prompts resume')
        names=self.turn_order
        cursor=names.index(starter.name);passes=0;actions_taken=0;pending=[]
        alive=sum(1 for name in names if not self.players[name].eliminated)
        while alive>1:
            if passes>=alive:
                if not pending:break
                item=pending.pop()
                if item['controller'].eliminated or item['marker'] not in self.stack:
                    passes=0;cursor=self.active_idx
                    continue
                self.resolve_wave_activation(item)
                self.check_sba();self.check_ream_combo()
                passes=0;cursor=self.active_idx
                if self.winner:return True
                continue
            p=self.players[names[cursor]];cursor=(cursor+1)%len(names)
            if p.eliminated:continue
            # Object deadlines advance even while the stronger whole-stack pass
            # suppresses this particular prompt.
            object_passes=self.active_priority_object_passes(p,timing)
            modern_actions=None
            if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
                modern_actions=self.legal_priority_actions(p,timing,context,include_held=True)
                if self.scheduler_suppresses_priority(p,timing,modern_actions):
                    passes+=1;continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.active_priority_seat_snooze(p,timing):
                self.log('priority_seat_snooze_auto',p.name,None,
                         f'{timing}: automatically passes priority while SNOOZE ALL is active')
                passes+=1;continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.priority_autopasses_current_stack(p):
                self.log('autopass_priority',p.name,None,f'{timing}: automatically passes priority on the current stack')
                passes+=1;continue
            if self.consume_specialized_priority_pass(p):
                self.log('priority_specialized_pass',p.name,None,
                         f'{timing}: the player already passed this unchanged stack in its specialized response question')
                passes+=1;continue
            # Audit the complete legal surface, then fully suppress every
            # passed-on source until its scheduled wake boundary.
            visible_actions=(modern_actions if modern_actions is not None else
                             self.legal_priority_actions(p,timing,context,include_held=True))
            if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION:
                suppressed=[action for action in visible_actions if self.priority_action_is_object_passed(action,object_passes)]
                if suppressed:self.log('scheduler_suppressed',p.name,None,timing,
                    legal_options=[self.priority_action_label(p,action) for action in suppressed],
                    whole_decision_suppressed=len(suppressed)==len(visible_actions),mode='snooze_objects')
            visible_actions=[
                action for action in visible_actions
                if not self.priority_action_is_object_passed(action,object_passes)]
            if not visible_actions:
                passes+=1;continue
            if (self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION or
                    self.priority_window_is_responsive(timing,context)):
                short_unheld_actions=list(visible_actions)
            else:
                signature=self.priority_state_signature(p)
                held=p.dungeon.get('priority_holds',{})
                short_unheld_actions=[
                    action for action in visible_actions
                    if held.get(self.priority_action_key(action))!=signature]
            wake_actions=list(short_unheld_actions)
            if not wake_actions:
                if object_passes:
                    source_names=list(dict.fromkeys(entry.source_name for entry in object_passes))
                    self.log('priority_object_pass_auto',p.name,None,
                             f'{timing}: automatically passed; only passed-on object(s) could act',
                             sources=source_names)
                passes+=1;continue
            prompt_actions=list(visible_actions)
            for entry in ([] if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION else object_passes):
                if not any(action[0]=='wake_priority_object' and action[1] is entry.source
                           for action in prompt_actions):
                    prompt_actions.append(('wake_priority_object',entry.source,{}))
            pass_on=self.priority_pass_on_option(p,wake_actions)
            if pass_on:prompt_actions.append(pass_on)
            if self.stack and self.decision_surface_revision<SCHEDULER_SURFACE_REVISION:prompt_actions.append(('autopass_stack',None,{}))
            from .decision_roles import offer
            combo=offer(self,p)
            if combo:prompt_actions.append(combo)
            concede=self.priority_concede_action()
            if concede:prompt_actions.append(concede)
            if self.decision_surface_revision>=2:
                prompt=f'{timing}: {p.name} has priority. Choose an action or PASS.'
                if pass_on and self.decision_surface_revision>=PASSING_ACCELERATION_SURFACE_REVISION:
                    prompt+=' PASS ON OBJECTS can schedule multiple sources atomically.'
            else:
                prompt=(f'{timing}: {p.name} has priority. Take an instant-speed action, propose a '
                        'demonstrated combo loop for opponent consent and rules adjudication, or PASS this priority round')
                if pass_on:
                    prompt+=('; PASS ON the sole source to stop it opening prompts, then choose its '
                             'exact wake boundary in a follow-up')
                if object_passes:
                    prompt+='; WAKE a snoozed object to make it available in this priority window'
                if self.stack:prompt+='; or AUTOPASS the current stack unless another spell is cast'
                prompt+='.'
            pass_metadata=(self.priority_pass_on_request_metadata(
                p,pass_on,prompt_actions.index(pass_on)) or {}) if pass_on else {}
            if context and context.get('attackers'):
                pass_metadata={**pass_metadata,'combat_context':context}
            choice=self._request_decision(
                'priority_action',p,prompt,
                prompt_actions,lambda a:self.priority_prompt_action_label(p,a),allow_pass=True,
                gameplan_access=True,
                request_metadata=pass_metadata or None)
            if choice is None:
                signature=self.priority_state_signature(p);holds=p.dungeon.setdefault('priority_holds',{})
                for action in short_unheld_actions:
                    holds[self.priority_action_key(action)]=signature
                passes+=1;continue
            if choice[0]=='concede':
                self.concede_from_priority(p,timing)
                if self.winner or self.pilot_terminal:return True
                alive=sum(1 for name in names if not self.players[name].eliminated)
                passes=0;cursor=self.active_idx
                continue
            if choice[0]=='autopass_stack':
                self.start_priority_stack_autopass(p)
                passes+=1;continue
            if choice[0]=='pass_on_priority_object':
                schedule=self._request_pass_on_schedule(p,choice[1])
                self.arm_priority_object_pass(p,choice[1],timing,schedule)
                passes+=1;continue
            if choice[0]=='pass_on_priority_objects':
                payload=self._decision_auxiliary_payload(
                    getattr(self,'_last_decision_id','')).get('pass_on_batch') or {}
                self.arm_priority_object_pass_batch(p,choice,timing,payload)
                passes+=1;continue
            if choice[0]=='wake_priority_object':
                self.clear_priority_object_pass(
                    p,choice[1],
                    f'{self.priority_source_name(choice[1])} was explicitly woken in this priority window')
                cursor=(cursor-1)%len(names)
                continue
            self.clear_specialized_priority_passes()
            if choice[1] is not None:
                self.clear_priority_object_pass(
                    p,choice[1],
                    f'{self.priority_source_name(choice[1])} was selected; its object pass is cancelled')
            started_at=self.seq
            if choice[0]=='wave_activate':
                prior_root=self.__dict__.get('_activated_ability_decision_root')
                self._activated_ability_decision_root={
                    'decision_id':getattr(self,'_last_decision_id',None),
                    'actor':p.name,
                }
                try:item=self.queue_wave_activation(p);ok=bool(item)
                finally:
                    if prior_root is None:self.__dict__.pop('_activated_ability_decision_root',None)
                    else:self._activated_ability_decision_root=prior_root
                if item:
                    marker=item['marker'];self.resolve_ward_triggers(p,marker,[item['target']])
                    if marker in self.stack:self.react_to_abilities(p)
                    if marker in self.stack:pending.append(item)
                    else:self.resolve_wave_activation(item)
            else:
                if choice[0]=='cast':p.dungeon['cast_priority_context']=context or {}
                try:ok=self.execute_refereed_action(p,choice)
                finally:
                    if choice[0]=='cast':p.dungeon.pop('cast_priority_context',None)
            countered=any(event['seq']>started_at and event['type'] in {'ability_countered','counter_abilities'}
                          for event in self.events)
            if ok is False and not countered:
                raise UnrefereedDecisionError('Advertised priority action became illegal: '+self.priority_action_label(p,choice))
            actions_taken+=1;passes=0
            # The player who adds an object to the stack gets priority again.
            # Other actions currently resolve through their exact cast/ability
            # handler, after which the active player receives priority.
            cursor=names.index(p.name) if choice[0]=='wave_activate' else self.active_idx
            self.check_sba();self.check_ream_combo()
            if self.winner:return True
            if actions_taken>=60:
                raise UnrefereedDecisionError(f'Priority window {timing} exceeded 60 actions without all players passing')
            alive=sum(1 for name in names if not self.players[name].eliminated)
        self.log('priority_closed',starter.name,None,f'{timing}: all players passed in priority order',actions=actions_taken)
        return actions_taken>0

    @resolution_sequence
    def resolve_simultaneous_triggers(self,event,triggers,starter=None):
        """Order and resolve simultaneous triggers using APNAP stack placement.

        Each trigger is a dict with controller, source, label, and resolve.  A
        controller chooses bottom-to-top placement for their own bundle.  Player
        bundles are then placed in APNAP order, so the nonactive player's bundle
        naturally resolves first.
        """
        if not triggers:return
        generated_frames=self.__dict__.get('_generated_trigger_frames',[])
        if generated_frames:
            generated_frames[-1].extend(triggers)
            self.log('triggers_deferred',None,None,f'{event}: {len(triggers)} trigger(s) wait until the current object finishes resolving')
            return
        for trigger in triggers:
            prepare=trigger.pop('prepare',None)
            if prepare:prepare()
        active=starter or self.players[self.turn_order[self.active_idx]]
        apnap=self.turn_order[self.turn_order.index(active.name):]+self.turn_order[:self.turn_order.index(active.name)]
        ordered=[]
        batch_order=self.selection_batch_enabled()
        for name in apnap:
            controller=self.players[name]
            remaining=[t for t in triggers if t['controller'].name==name]
            if batch_order and len(remaining)>1:
                ordered.extend(self._request_selection('trigger_order_selection',controller,
                    f'{event}: order all your triggers bottom-to-top; the last selected resolves first.',remaining,
                    lambda t:f'{t["source"]}: {t["label"]}',minimum=len(remaining),maximum=len(remaining),ordered=True))
            else:
                while remaining:
                    if len(remaining)==1:chosen=remaining[0]
                    else:
                        chosen=self._request_decision(
                            'trigger_order',controller,
                            f'{event}: choose the next trigger you control to put on the stack (bottom to top; this choice resolves after triggers you place later).',
                            remaining,lambda t:f'{t["source"]}: {t["label"]}')
                    ordered.append(chosen);remaining.remove(chosen)
        for index,t in enumerate(ordered):
            marker={'actor':t['controller'].name,'card':t['source'],'trigger_event':event,
                    'trigger_index':index,'trigger_label':t['label']}
            t['_stack_marker']=marker;self.stack.append(marker)
            self.log('trigger_stack_add',t['controller'].name,t['source'],t['label'],event=event,stack_index=index)
        for t in ordered:
            marker=t['_stack_marker']
            if marker in self.stack and t.get('targets'):
                self.resolve_ward_triggers(t['controller'],marker,t['targets'])
        self.react_to_abilities(active)
        self.priority_window(active,f'{event}: triggers on stack')
        if self.winner or self.pilot_terminal:return
        for t in reversed(ordered):
            marker=t['_stack_marker']
            if marker not in self.stack:
                self.log('trigger_countered',t['controller'].name,t['source'],t['label'],event=event)
                continue
            self.stack.remove(marker)
            self.log('trigger_resolve',t['controller'].name,t['source'],t['label'],event=event)
            prior=t['controller'].dungeon.get('resolving_source_name')
            t['controller'].dungeon['resolving_source_name']=t['source']
            generated=[];departures=[]
            self.__dict__.setdefault('_generated_trigger_frames',[]).append(generated)
            self.__dict__.setdefault('_ltb_trigger_frames',[]).append(departures)
            try:
                t['resolve']()
                post_resolve_sba=t.get('post_resolve_sba')
                if post_resolve_sba:post_resolve_sba()
                self.check_sba()
            finally:
                self._ltb_trigger_frames.pop();self._generated_trigger_frames.pop()
                if prior is None:t['controller'].dungeon.pop('resolving_source_name',None)
                else:t['controller'].dungeon['resolving_source_name']=prior
            if departures or generated:self.resolve_simultaneous_triggers(
                f'after {t["source"]} trigger resolves',departures+generated,starter=active)
            self.check_ream_combo()
            if self.winner:break
            self.priority_window(active,f'{event}: after {t["source"]} trigger resolves')

    def _messageboard_window_id(self,p):
        return f'G{self.game_no:02d}-T{self.turn_number:04d}-{self.phase}-{p.name}'

    @staticmethod
    def _messageboard_address_label(address):
        kind=address.get('kind')
        if kind=='all':return 'all opponents'
        if kind=='pilot':return ', '.join(address.get('pilots') or []) or 'specific pilot'
        return 'the table (generic)'

    def _messageboard_recipients(self,p,address):
        requested=set(address.get('pilots') or [])
        if address.get('kind')=='generic':return []
        ordered=[];start=self.turn_order.index(p.name)
        for offset in range(1,len(self.turn_order)):
            name=self.turn_order[(start+offset)%len(self.turn_order)]
            candidate=self.players[name]
            if candidate.eliminated:continue
            if address.get('kind')=='all' or name in requested:ordered.append(candidate)
        return ordered

    def _append_messageboard_message(self,author,text,address,window_id,message_id,reply_to=None):
        entry={
            'schema':1,'message_id':message_id,'window_id':window_id,
            'author':author.name,'address':dict(address),'text':text,
            'reply_to':reply_to,'round':self.round,'turn':self.turn_number,'phase':self.phase,
        }
        self.public_messageboard.append(entry)
        self.log(
            'messageboard_message',author.name,None,text,
            message_id=message_id,window_id=window_id,address=dict(address),
            reply_to=reply_to,message_kind='reply' if reply_to else 'post')
        return entry

    def open_messageboard(self,p,window_id,*,message_text=None,address=None,
                          message_decision_id=None):
        """Resolve one public, non-recursive political message chain."""
        self.closed_messageboard_windows.add(window_id)
        living=self._messageboard_recipients(p,{'kind':'all','pilots':[]})
        addresses=[('messageboard_address',None,{'address':{'kind':'generic','pilots':[]}})]
        if living:
            addresses.append(('messageboard_address',None,{
                'address':{'kind':'all','pilots':[opponent.name for opponent in living]}}))
            addresses.extend(
                ('messageboard_address',None,{
                    'address':{'kind':'pilot','pilots':[opponent.name]}})
                for opponent in living)
        def label(action):
            address=action[2]['address'];kind=address['kind']
            if kind=='generic':return 'POST GENERICALLY — no responses prompted'
            if self.async_diplomacy:
                return 'ADDRESS '+('ALL OPPONENTS' if kind=='all' else address['pilots'][0])+' — optional asynchronous diplomacy'
            if kind=='all':return 'ADDRESS ALL OPPONENTS — each may make one public response'
            return f'ADDRESS {address["pilots"][0]} — that pilot may make one public response'
        if self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION:
            if not isinstance(address,dict):
                raise UnrefereedDecisionError('Batched table talk requires an address object')
            kind=address.get('kind');pilots=address.get('pilots')
            if (
                self.decision_surface_revision>=OPENING_REGIME_SURFACE_REVISION
                and self.round==1
                and self.turn_order[self.active_idx]==p.name
                and self.phase=='precombat_main'
                and kind!='generic'
            ):
                raise UnrefereedDecisionError(
                    'The required first-own-turn salutation must be generic')
            legal={
                json.dumps(row[2]['address'],sort_keys=True)
                for row in addresses
            }
            if json.dumps(address,sort_keys=True) not in legal:
                raise UnrefereedDecisionError('Batched table-talk address is not legal')
            kwargs={
                'address':dict(address),'message_text':message_text,
                'message_decision_id':message_decision_id,
            }
        else:
            choice=self._request_decision(
                'messageboard_compose',p,
                f'Compose one public table-talk message of at most {MESSAGEBOARD_MAX_CHARS} characters '
                'in the rationale, and choose its address. Addressed replies are optional, public, '
                'generic, and cannot prompt another response. PASS cancels this main-phase message window.',
                addresses,label,allow_pass=True)
            if not choice:return True
            _,_,kwargs=choice
        try:text=normalize_messageboard_text(kwargs.get('message_text',''))
        except ValueError as exc:raise UnrefereedDecisionError(str(exc)) from exc
        root_id=kwargs.get('message_decision_id') or f'{window_id}-message'
        address=kwargs['address']
        root_entry=self._append_messageboard_message(p,text,address,window_id,root_id)
        if self.async_diplomacy:return True
        prior_replies=[]
        for recipient in self._messageboard_recipients(p,address):
            transcript='\n'.join(
                f'{entry["author"]}: {json.dumps(entry["text"],ensure_ascii=False)}'
                for entry in [root_entry,*prior_replies])
            response_prompt=(
                f'{MESSAGEBOARD_UNTRUSTED_HELP}\n'
                f'{p.name} addressed you in this public message chain:\n{transcript}\n'
                f'Optionally respond once in at most {MESSAGEBOARD_MAX_CHARS} characters. '
                'Your response is generic public table talk and will not prompt further replies.'
            )
            if self.decision_surface_revision<DRAW_PLANNING_SURFACE_REVISION:
                response_prompt=response_prompt.replace(
                    'characters. Your response',
                    'characters by putting the response in the rationale. Your response')
            response=self._request_decision(
                'messageboard_response',recipient,
                response_prompt,
                [True],lambda _:'RESPOND PUBLICLY — one generic response; no further replies',
                allow_pass=True)
            if not response:continue
            try:response_text=normalize_messageboard_text(
                getattr(
                    self,
                    '_last_messageboard_text'
                    if self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION
                    else '_last_decision_rationale',
                    '',
                ))
            except ValueError as exc:raise UnrefereedDecisionError(str(exc)) from exc
            response_id=getattr(self,'_last_decision_id',None) or f'{root_id}-reply-{len(prior_replies)+1}'
            entry=self._append_messageboard_message(
                recipient,response_text,{'kind':'generic','pilots':[]},window_id,
                response_id,reply_to=root_id)
            prior_replies.append(entry)
        return True

    def request_main_action(self,p):
        acts=self.legal_main_actions(p)
        from .decision_roles import offer
        combo=offer(self,p)
        if combo:acts.append(combo)
        if self.decision_roles:
            if not acts:return None
            concede=self.priority_concede_action()
            if concede:acts.append(concede)
        window_id=self._messageboard_window_id(p)
        messageboard_available=(not self.decision_roles and
            window_id not in self.closed_messageboard_windows and
            (
                self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION
                or window_id not in self.offered_messageboard_windows
            ))
        opening_salutation_required=(
            self.decision_surface_revision>=OPENING_REGIME_SURFACE_REVISION
            and self.round==1
            and self.turn_order[self.active_idx]==p.name
            and self.phase=='precombat_main'
            and messageboard_available
        )
        if messageboard_available:
            action=('messageboard_open',None,{'window_id':window_id})
            if self.decision_surface_revision>=2:
                # One salient, non-material side-action opportunity replaces a
                # low-salience option repeated after every main-phase action.
                acts.insert(0,action)
                if self.decision_surface_revision<DRAW_PLANNING_SURFACE_REVISION:
                    self.offered_messageboard_windows.add(window_id)
            else:acts.append(action)
        def lab(a):
            kind,c,kw=a
            if kind in {'propose_combo_loop','concede'}:return self.priority_action_label(p,a)
            if kind=='messageboard_open':
                if self.decision_surface_revision<2:
                    return 'OPEN PUBLIC MESSAGEBOARD — once this main phase'
                return ('TABLE TALK (NON-MATERIAL) — post once, resolve optional replies, '
                        'then return to this main phase')
            if kind=='cast':return f'CAST {c.d.name} {c.d.mana_cost}'+(f' [miracle]' if kw.get('miracle') else '')+(f' X={kw.get("x_value")}' if '{X}' in c.d.mana_cost else '')+(' [kicked]' if kw.get('kicked') else '')+(' [overload]' if kw.get('overload') else '')+(' [evoke]' if kw.get('evoke') else '')
            if kw.get('ability_label'):return f'ACTIVATE {c.d.name if hasattr(c,"d") else c.name} — {kw["ability_label"]}'
            if kind=='commander':return f'CAST COMMANDER {c.d.name} (tax {p.command_tax})'
            if kind=='transmute':return 'TRANSMUTE Dimir House Guard'
            if kind=='nightmare':return 'ACTIVATE Chthonian Nightmare'
            if kind=='escape_uro':return 'ESCAPE Uro'
            if kind=='wave_activate':return f'ACTIVATE Parallax Wave ({c.counters.get("fade",0)} fade counters)'
            if kind=='seer_activate':return 'ACTIVATE Viscera Seer — sacrifice a creature, scry 1'
            if kind=='devotion_activate':return 'ACTIVATE Fanatical Devotion — sacrifice a creature, regenerate target creature'
            if kind=='houseguard_sac':return 'ACTIVATE Dimir House Guard — sacrifice a creature, regenerate House Guard'
            if kind=='fallen_sac':return 'ACTIVATE Fallen Ideal granted ability — sacrifice a creature, +2/+1'
            if kind=='sage_animate':return 'ACTIVATE Sage of the Maze — animate a land until EOT'
            if kind=='fetch_activate':return f'ACTIVATE {c.name} — pay 1 life, sacrifice, search legal land type'
            if kind=='domri_plus':return 'ACTIVATE Domri +1 — add R or G; creature spells uncounterable this turn'
            if kind=='domri_minus':return 'ACTIVATE Domri -2 — choose creatures to fight'
            if kind=='bauble_activate':return "ACTIVATE Wayfarer's Bauble - {2}, sacrifice, search a basic tapped"
            if kind=='top_look':return "ACTIVATE Sensei's Divining Top - {1}, reorder top three"
            if kind=='top_draw':return "ACTIVATE Sensei's Divining Top - tap, draw a card, put Top on library"
            if kind=='dark_depths':return f'ACTIVATE Dark Depths - {{3}}, remove an ice counter ({c.counters.get("ice",0)} remaining)'
            if kind=='stage_copy':return "ACTIVATE Thespian's Stage - {2}, tap: copy target land"
            return kind
        prompt='Choose the next material main-phase action, or pass.'
        metadata=None
        if self.decision_surface_revision>=2 and messageboard_available:
            if opening_salutation_required:
                prompt=(
                    'Before the next material main-phase action or pass, choose TABLE TALK '
                    'and post a characteristic but strategically unrevealing generic '
                    'salutation. It prompts no responses and then returns here.'
                )
            else:
                prompt=('Choose the next material main-phase action, or pass. TABLE TALK is an '
                        'optional non-material side action available until used in this main phase.'
                        if self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION else
                        'Choose the next material main-phase action, or pass. TABLE TALK is an '
                        'optional non-material side action available on this first main-phase decision.')
            metadata={'messageboard':{
                'schema':1,'available':True,'non_material':True,'window_id':window_id,
                'option_index':0,
                'valid_recipients':[opponent.name for opponent in self._messageboard_recipients(
                    p,{'kind':'all','pilots':[]})],
                'help':(
                    'Your first-turn salutation is mandatory. Submit a characteristic but '
                    'strategically unrevealing generic greeting in this same answer. Generic '
                    'addressing prompts no responses.'
                    if opening_salutation_required else
                    'Consider whether a concise political message could change attacks, '
                    'threat allocation, cooperation, or a deal. Silence is valid. When '
                    'choosing TABLE TALK, submit its address and complete message in this '
                    'same answer; no separate compose decision follows.'
                    if self.decision_surface_revision>=DRAW_PLANNING_SURFACE_REVISION else
                    'Consider whether a concise political message could change attacks, '
                    'threat allocation, cooperation, or a deal. Silence is valid.'),
            }}
            if opening_salutation_required:
                metadata['messageboard'].update({
                    'opening_salutation_required':True,
                    'required_address':'generic',
                    'salutation_guidance':(
                        'Use the private personality card to sound characteristic but '
                        'strategically unrevealing: disclose no hand contents, intentions, '
                        'threat assessment, alliance, or strategic plan.'
                    ),
                })
        if (
            PASSING_ACCELERATION_SURFACE_REVISION<=self.decision_surface_revision<SCHEDULER_SURFACE_REVISION
            and self.phase=='postcombat_main'
        ):
            metadata=dict(metadata or {})
            metadata['seat_snooze']={
                'schema':1,'available':True,'trigger':'pass_to_end_step',
                'help':(
                    'When passing this postcombat main phase, --snooze-all suppresses '
                    'optional decision points. Add --until "N beginning|end of PHASE" '
                    'for an explicit boundary; without it, prompts resume after the turn '
                    'immediately before your next turn. Being attacked wakes you for blockers.'
                ),
            }
            prompt+=(
                ' You may attach --snooze-all to PASS to continue passing optional '
                'decision points until its deadline.')
        choice=self._request_decision(
            'main_action',p,prompt,acts,lab,allow_pass=True,gameplan_access=True,
            request_metadata=metadata)
        if (
            opening_salutation_required
            and not (
                isinstance(choice,tuple) and len(choice)==3
                and choice[0]=='messageboard_open'
            )
        ):
            raise UnrefereedDecisionError(
                'TABLE TALK is required before first-own-turn main-phase play')
        return choice

    def death_grasp_target(self,p):
        targets=self.death_grasp_targets(p)
        def label(row):
            kind,owner,obj=row
            if kind=='player':return f'PLAYER {obj.name} (life {obj.life})'
            if kind=='planeswalker':return f'PLANESWALKER {obj.name} controlled by {owner.name} (loyalty {obj.counters.get("loyalty",0)})'
            return f'CREATURE {obj.name} controlled by {owner.name} ({self.effective_power(obj)}/{self.effective_toughness(obj)})'
        return self._request_decision('death_grasp_target',p,'Death Grasp: choose one target.',targets,label)


    def activate_wave_refereed(self,p):
        pending=self.queue_wave_activation(p)
        if not pending:return False
        self.__dict__.pop('_activated_ability_decision_root',None)
        marker=pending['marker']
        self.resolve_ward_triggers(p,marker,[pending['target']])
        if marker in self.stack:self.react_to_abilities(p)
        if marker in self.stack:self.priority_window(p,'Parallax Wave activated ability response',{'ability':'exile target creature','targets':[pending['target'].uid]})
        self.resolve_wave_activation(pending)
        return True

    def queue_wave_activation(self,p):
        """Pay/target a Wave activation without prematurely resolving it."""
        wave=self.perm(p,'Parallax Wave')
        if not wave or wave.counters.get('fade',0)<=0:return False
        targets=[]
        for pp in self.players.values():
            for q in pp.battlefield:
                if self.is_creature_perm(q) and self.target_still_legal(p,pp,q,True,wave.name):targets.append((pp,q))
        if not targets:return False
        z=self._request_decision('parallax_wave_target',p,'Parallax Wave: remove a fade counter to exile target creature.',targets,
                    lambda z:f'{z[0].name}: {z[1].name} {self.effective_power(z[1])}/{self.effective_toughness(z[1])}')
        if not z:return False
        pp,q=z;wave.counters['fade']-=1
        marker={'actor':p.name,'uid':wave.uid,'card':'Parallax Wave','ability_kind':'activated',
                'ability_label':'remove a fade counter: exile target creature','target_uid':q.uid,'target_uids':[q.uid]}
        item={'kind':'parallax_wave','controller':p,'wave':wave,'target_owner':pp,'target':q,'marker':marker}
        self.stack.append(marker)
        self.log('stack_add',p.name,'Parallax Wave',
                 f'Activation targeting {q.name} added to stack; {wave.counters.get("fade",0)} fade counter(s) remain',
                 target=q.name,target_uid=q.uid)
        return item

    @resolution_sequence
    def resolve_wave_activation(self,item):
        p=item['controller'];wave=item['wave'];pp=item['target_owner'];q=item['target']
        marker=item['marker']
        if marker not in self.stack:
            self.log('ability_countered',p.name,'Parallax Wave','Activation was countered');return False
        self.stack.remove(marker)
        if not self.target_still_legal(p,pp,q,True,wave.name):
            self.log('ability_fizzle',p.name,'Parallax Wave',f'Target {q.name} is no longer legal')
            return False
        uid=q.uid;self.leave_battlefield(pp,q,'exile','Parallax Wave activation')
        # If this exact Wave object has already left, its leaves trigger has
        # resolved and cannot return a card exiled by the later ability.
        linked=wave in p.battlefield
        if linked:wave.metadata.setdefault('wave_exiled_uids',[]).append(uid)
        self.log('activated_ability',p.name,'Parallax Wave',f'Exiles {q.name}'+(' (linked)' if linked else ' after Wave left; no linked return'),target=q.name,target_uid=uid)
        return True

    def request_own_sacrifice(self,p,reason):
        cs=[q for q in p.battlefield if self.is_creature_perm(q)]
        return self._request_decision('sacrifice_choice',p,reason,cs,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')

    def activate_bauble_refereed(self,p,bauble):
        if not bauble or bauble not in p.battlefield:return False
        def pay_cost():
            if bauble.tapped or not self.pay(p,sim.CardDef("Wayfarer's Bauble activation",'{2}','Ability','',1,p.name,2)):return False
            bauble.tapped=True;self.leave_battlefield(p,bauble,'graveyard',"Wayfarer's Bauble activation cost");return True
        paid,cost_triggers=self.pay_legacy_activation_cost(pay_cost)
        if not paid:return False
        def resolve_bauble():
            basics=[c for c in p.library if c.d.type_line.startswith('Basic Land')]
            if basics:
                choice=self._request_decision('bauble_basic',p,"Wayfarer's Bauble: choose a basic land to put onto the battlefield tapped.",basics,lambda c:c.d.name)
                p.library.remove(choice);land=self._put_card_bf(p,choice,"Wayfarer's Bauble search");land.tapped=True
            self.rng.shuffle(p.library);self.log('shuffle',p.name,None,"Shuffle after Wayfarer's Bauble")
        return self.put_registered_stack_item(p,bauble,"search for a basic land tapped",resolve_bauble,cost_triggers=cost_triggers)

    def activate_top_look_refereed(self,p,top):
        if not top or top not in p.battlefield:return False
        cost=sim.CardDef("Sensei's Divining Top look",'{1}','Ability','',1,p.name,1)
        if self.can_pay(p,cost) is None:return False
        if not self.pay(p,cost):return False
        def resolve_look():
            if self.selection_batch_enabled():
                seen=list(p.library[-min(3,len(p.library)):])
                ordered=self._request_selection('top_order_selection',p,
                    "Sensei's Divining Top: select all inspected cards in bottom-to-top order; the last selected card will be drawn first.",seen,
                    lambda card:f'{card.d.name} [{card.uid}]',minimum=len(seen),maximum=len(seen),ordered=True)
            else:
                seen=list(p.library[-min(3,len(p.library)):]);ordered=[]
                for slot in range(len(seen)):
                    card=self._request_decision('top_order',p,
                        f"Sensei's Divining Top: choose card {slot+1} from bottom to top of the inspected group"+(' (this will be drawn first).' if slot==len(seen)-1 else '.'),
                        [card for card in seen if card not in ordered],lambda card:f'{card.d.name} {card.d.mana_cost}')
                    ordered.append(card)
            for card in seen:p.library.remove(card)
            p.library.extend(ordered);self.log('top_reorder',p.name,top.name,'Reordered top three cards')
        return self.put_registered_stack_item(p,top,'look at and reorder the top three cards',resolve_look)

    def activate_top_draw_refereed(self,p,top):
        if not top or top not in p.battlefield or top.tapped or not p.library:return False
        top.tapped=True
        def resolve_draw():
            self.draw(p,1,"Sensei's Divining Top draw ability")
            if top in p.battlefield:self.leave_battlefield(p,top,'library',"Sensei's Divining Top ability")
        return self.put_registered_stack_item(p,top,'draw a card, then put Top on its owner\'s library',resolve_draw)

    def activate_liliana_refereed(self,p,liliana):
        if not liliana or liliana not in p.battlefield or liliana.tapped or liliana.summoning_sick or not p.hand:return False
        targets=[q for q in p.battlefield if q.uid!=liliana.uid and
                 (self.is_creature_perm(q) or self.is_planeswalker_perm(q))]
        cost=sim.CardDef('Liliana the Faultless activation','{1}','Ability','',1,p.name,1)
        if not targets or self.can_pay(p,cost) is None:return False
        target=self._request_decision('liliana_hexproof_target',p,'Liliana the Faultless: choose another creature or planeswalker you control.',targets,
                                      lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')
        discard=self._request_decision('liliana_discard',p,'Liliana the Faultless: choose a card to discard as an activation cost.',list(p.hand),
                                       lambda card:f'{card.d.name} {card.d.mana_cost}')
        self.pay(p,cost);liliana.tapped=True;p.hand.remove(discard);p.graveyard.append(discard)
        def resolve_liliana():
            if self.target_still_legal(p,p,target,source_name=liliana.name):
                target.metadata['liliana_hexproof_turn']=self.turn_number
                self.log('activated_ability',p.name,liliana.name,f'{target.name} gains hexproof until end of turn',target_uid=target.uid)
        return self.put_registered_stack_item(p,liliana,'another target creature or planeswalker gains hexproof',resolve_liliana,[target])

    def activate_seer_refereed(self,p):
        seer=self.perm(p,'Viscera Seer')
        if not seer:return False
        q=self.request_own_sacrifice(p,'Viscera Seer: choose creature to sacrifice.')
        if not q:return False
        paid,cost_triggers=self.pay_legacy_activation_cost(lambda:(self.leave_battlefield(p,q,'graveyard','Viscera Seer activation sacrifice') or True))
        if not paid:return False
        return self.put_registered_stack_item(p,seer,'scry 1',lambda:self.scry(p,1,'Viscera Seer'),cost_triggers=cost_triggers)

    def activate_devotion_refereed(self,p):
        devo=self.perm(p,'Fanatical Devotion')
        if not devo:return False
        targets=[q for q in p.battlefield if self.is_creature_perm(q)]
        if not targets:return False
        target=self._request_decision('regenerate_target',p,'Fanatical Devotion: choose target creature to regenerate.',targets,lambda q:q.name)
        sac=self.request_own_sacrifice(p,'Fanatical Devotion: choose creature to sacrifice as the cost.')
        paid,cost_triggers=self.pay_legacy_activation_cost(lambda:(self.leave_battlefield(p,sac,'graveyard','Fanatical Devotion activation sacrifice') or True))
        if not paid:return False
        def resolve_devotion():
            if self.target_still_legal(p,self.players[target.controller],target,True,devo.name):target.metadata['regen_shields']=target.metadata.get('regen_shields',0)+1
        return self.put_registered_stack_item(p,devo,'regenerate target creature',resolve_devotion,[target],cost_triggers)

    def activate_houseguard_refereed(self,p):
        hg=self.perm(p,'Dimir House Guard')
        if not hg:return False
        sac=self.request_own_sacrifice(p,'Dimir House Guard: choose a creature to sacrifice to regenerate House Guard.')
        if not sac:return False
        paid,cost_triggers=self.pay_legacy_activation_cost(lambda:(self.leave_battlefield(p,sac,'graveyard','Dimir House Guard activation sacrifice') or True))
        if not paid:return False
        def resolve_guard():
            if hg in p.battlefield:hg.metadata['regen_shields']=hg.metadata.get('regen_shields',0)+1
        return self.put_registered_stack_item(p,hg,'regenerate Dimir House Guard',resolve_guard,cost_triggers=cost_triggers)

    def activate_fallen_refereed(self,p):
        ideal=self.perm(p,'Fallen Ideal')
        if not ideal or not ideal.attached_to:return False
        enchanted=self.find_card_obj_on_bf(p,ideal.attached_to)
        if not enchanted:return False
        sac=self.request_own_sacrifice(p,'Fallen Ideal: choose creature to sacrifice for +2/+1.')
        if not sac:return False
        paid,cost_triggers=self.pay_legacy_activation_cost(lambda:(self.leave_battlefield(p,sac,'graveyard','Fallen Ideal granted ability sacrifice') or True))
        if not paid:return False
        def resolve_ideal():
            if enchanted in p.battlefield:
                enchanted.metadata['fallen_power_bonus']=enchanted.metadata.get('fallen_power_bonus',0)+2
                enchanted.metadata['fallen_toughness_bonus']=enchanted.metadata.get('fallen_toughness_bonus',0)+1
        return self.put_registered_stack_item(p,ideal,'enchanted creature gets +2/+1 until end of turn',resolve_ideal,cost_triggers=cost_triggers)

    def transmute_house_guard(self,p,card):
        if card not in p.hand:return False
        cost=sim.CardDef('Dimir House Guard transmute','{1}{B}{B}','Ability','',1,p.name,3)
        if not self.pay(p,cost):return False
        p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Transmute activation cost')
        def resolve_transmute():
            name=self.request_ream_tutor(p,mv=4)
            if name:self.search_to_zone(p,name,'hand','Dimir House Guard transmute',reveal=True)
        return self.put_registered_stack_item(p,card,'transmute for a card with mana value 4',resolve_transmute)

    def activate_nightmare(self,p):
        nightmare=self.perm(p,'Chthonian Nightmare')
        targets=[card for card in p.graveyard if card.d.is_creature and card.d.mv<=p.energy]
        sacrifices=[q for q in p.battlefield if self.is_creature_perm(q)]
        if not nightmare or not targets or not sacrifices:return False
        target=self._request_decision('nightmare_target',p,'Chthonian Nightmare: choose target creature card in your graveyard.',targets,
            lambda card:f'{card.d.name} (mana value {card.d.mv}; pay {card.d.mv} energy)')
        sacrifice=self._request_decision('nightmare_sacrifice',p,'Chthonian Nightmare: choose a creature to sacrifice as a cost.',sacrifices,
            lambda permanent:f'{permanent.name} {self.effective_power(permanent)}/{self.effective_toughness(permanent)}')
        amount=target.d.mv
        def pay_cost():
            if p.energy<amount or nightmare not in p.battlefield or sacrifice not in p.battlefield:return False
            p.energy-=amount
            self.leave_battlefield(p,sacrifice,'graveyard','Chthonian Nightmare activation sacrifice cost')
            if nightmare in p.battlefield:self.leave_battlefield(p,nightmare,'hand','Chthonian Nightmare activation return cost')
            return True
        paid,cost_triggers=self.pay_legacy_activation_cost(pay_cost)
        if not paid:return False
        def resolve_nightmare():
            if target in p.graveyard:
                p.graveyard.remove(target);self._put_card_bf(p,target,'Chthonian Nightmare ability')
        return self.put_registered_stack_item(p,nightmare,f'return target {target.d.name}',resolve_nightmare,cost_triggers=cost_triggers)

    def escape_uro(self,p,card):
        if card not in p.graveyard:return False
        others=[candidate for candidate in p.graveyard if candidate.uid!=card.uid]
        cost=sim.CardDef('Uro escape','{G}{G}{U}{U}','Ability','',1,p.name,4)
        if len(others)<5 or self.can_pay(p,cost) is None:return False
        if self.selection_batch_enabled():
            chosen=self._request_selection('escape_exile_selection',p,'Uro escape: choose exactly five other graveyard cards to exile.',others,
                lambda card:f'{card.d.name} [{card.uid}]',minimum=5,maximum=5)
        else:
            remaining=list(others);chosen=[]
            for slot in range(5):
                exile=self._request_decision('escape_exile',p,f'Uro escape: choose graveyard card {slot+1} of 5 to exile as an additional cost.',remaining,
                    lambda candidate:f'{candidate.d.name} {candidate.d.mana_cost}')
                chosen.append(exile);remaining.remove(exile)
        if not self.pay(p,cost):return False
        for exile in chosen:
            p.graveyard.remove(exile);p.exile.append(exile);self.log('exile',p.name,exile.d.name,'Uro escape additional cost')
        p.graveyard.remove(card);p.hand.append(card);p.dungeon['escaping_uro_uid']=card.uid
        result=self.cast(p,card,free=True)
        if p.dungeon.get('escaping_uro_uid')==card.uid:p.dungeon.pop('escaping_uro_uid',None)
        return result

    def main_phase(self,p,post=False):
        self.phase='postcombat_main' if post else 'precombat_main'
        if post:
            sorin=self.perm(p,'Sorin of House Markov')
            if sorin and not sorin.metadata.get('transformed_sorin') and p.life_gained_this_turn>=3:
                self.resolve_simultaneous_triggers('beginning of postcombat main phase',[{
                    'controller':p,'source':sorin.name,'label':'exile Sorin and return it transformed',
                    'resolve':lambda sorin=sorin:self.transform_sorin_of_house_markov(p,sorin),
                }],starter=p)
        if not post:self.saga_step(p)
        p.land_play_limit=self.max_land_plays(p)
        if not post:
            # The opening salutation is required before *any* material
            # first-main-phase choice.  Land selection (and follow-up choices
            # such as shock-land payment) used to run before the ordinary main
            # action surface, making the requirement impossible to satisfy.
            # Open the non-material window first on revision 4+; the guarded
            # request accepts only TABLE TALK at this point and closes the
            # window before land play proceeds.
            opening_messageboard_required=(not self.decision_roles and
                self.decision_surface_revision>=OPENING_REGIME_SURFACE_REVISION
                and self.round==1
                and self.turn_order[self.active_idx]==p.name
                and self.phase=='precombat_main'
                and self._messageboard_window_id(p) not in self.closed_messageboard_windows
            )
            if opening_messageboard_required:
                opening_action=self.request_main_action(p)
                kind,_,kwargs=opening_action
                self.open_messageboard(
                    p,kwargs['window_id'],message_text=kwargs.get('text'),
                    address=kwargs.get('address'),
                    message_decision_id=kwargs.get('message_decision_id'))
        # An unused normal land play remains available in either main phase.
        # Keep the offer optional: a player may deliberately hold a land (most
        # notably an MDFC) in order to sequence spells or preserve its other face.
        while p.land_plays_used<p.land_play_limit:
            c=self.request_land_play(p,allow_pass=True)
            if not c:break
            self.play_land(p,c)
        material_actions=0;material_action_limit=20 if not post else 4
        while material_actions<material_action_limit:
            if p.eliminated or self.winner:break
            action=self.request_main_action(p)
            if not action:break
            prior_land_limit=p.land_play_limit
            prior_had_land=any(card.d.is_land for card in p.hand)
            kind,c,kwargs=action
            if kind=='snooze_all_priority':
                self.arm_priority_seat_snooze(p,kwargs.get('schedule'))
                break
            if kind=='messageboard_open':
                self.open_messageboard(
                    p,kwargs['window_id'],message_text=kwargs.get('text'),
                    address=kwargs.get('address'),
                    message_decision_id=kwargs.get('message_decision_id'))
                continue
            material_actions+=1
            if c is not None:
                self.clear_priority_object_pass(
                    p,c,f'{self.priority_source_name(c)} was selected; its object pass is cancelled')
            ok=self.execute_refereed_action(p,action)
            if ok is False:break
            self.check_ream_combo()
            p.land_play_limit=self.max_land_plays(p)
            gained_land_access=(not prior_had_land and any(card.d.is_land for card in p.hand) and p.land_plays_used<p.land_play_limit)
            unused_land_access=(any(card.d.is_land for card in p.hand) and
                                p.land_plays_used<p.land_play_limit)
            if p.land_play_limit>prior_land_limit or gained_land_access or unused_land_access:
                while p.land_plays_used<p.land_play_limit:
                    land=self.request_land_play(p,allow_pass=True)
                    if not land:break
                    self.play_land(p,land)
        # Mana empties only after the active player has passed the end-of-main
        # priority window; turn() closes that window and then clears it.

    def transform_sorin_of_house_markov(self,p,sorin):
        if sorin not in p.battlefield:return
        uid=sorin.uid;physical_owner=self.players[sorin.owner]
        self.leave_battlefield(p,sorin,'exile','Sorin postcombat transform trigger')
        card=next((card for card in physical_owner.exile if card.uid==uid),None)
        if not card:return
        physical_owner.exile.remove(card)
        starting_loyalty=sim.catalog_starting_loyalty(sorin.name,face_name='Sorin, Ravenous Neonate')
        returned=sim.Perm(uid,sorin.name,sorin.owner,p.name,False,False,{'loyalty':starting_loyalty},None,None,False,0,0,set(),self.turn_number,
                          {'transformed_sorin':True})
        p.battlefield.append(returned)
        self.log('transform',p.name,sorin.name,f'Returned transformed as Sorin, Ravenous Neonate with {starting_loyalty} loyalty',uid=uid)
        liliana=self.perm(p,'Liliana the Faultless')
        if liliana:self.resolve_simultaneous_triggers('Sorin transformed enters',[{
            'controller':p,'source':liliana.name,'label':'gain 1 life for a planeswalker entering','resolve':lambda:self.gain_life(p,1,'Liliana planeswalker ETB'),
        }],starter=p)

    def activate_domri_plus(self,p,domri):
        if not domri or domri.metadata.get('activated_turn')==self.turn_number:return False
        color=self._request_decision('domri_mana_color',p,'Domri +1: choose mana color.',['R','G'],lambda value:value)
        domri.counters['loyalty']=domri.counters.get('loyalty',3)+1;domri.metadata['activated_turn']=self.turn_number
        p.dungeon.setdefault('domri_floating',[]).append(color);p.dungeon['domri_uncounterable_turn']=self.turn_number
        self.log('planeswalker_activation',p.name,domri.name,f'+1 adds {color}; creature spells this turn cannot be countered')
        return True

    def activate_domri_minus(self,p,domri):
        if not domri or domri.counters.get('loyalty',0)<2 or domri.metadata.get('activated_turn')==self.turn_number:return False
        own=[q for q in p.battlefield if self.is_creature_perm(q) and self.target_still_legal(p,p,q,True,domri.name)]
        attacker=self._request_decision('domri_fight_own',p,'Domri -2: choose target creature you control.',own,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}')
        enemies=[(owner,q) for owner in self.opponents(p) for q in owner.battlefield
                 if self.is_creature_perm(q) and self.target_still_legal(p,owner,q,True,domri.name)]
        owner,defender=self._request_decision('domri_fight_enemy',p,'Domri -2: choose target creature you do not control.',enemies,lambda row:f'{row[0].name}: {row[1].name} {self.effective_power(row[1])}/{self.effective_toughness(row[1])}')
        domri.counters['loyalty']-=2;domri.metadata['activated_turn']=self.turn_number
        def resolve_fight():
            if not (self.target_still_legal(p,p,attacker,True,domri.name) and
                    self.target_still_legal(p,owner,defender,True,domri.name)):return
            attack_damage=self.effective_power(attacker);defend_damage=self.effective_power(defender)
            if not self.protection_prevents_damage(attacker,defender):defender.metadata['damage_marked']=defender.metadata.get('damage_marked',0)+attack_damage
            if not self.protection_prevents_damage(defender,attacker):attacker.metadata['damage_marked']=attacker.metadata.get('damage_marked',0)+defend_damage
            self.log('fight_damage',p.name,domri.name,f'{attacker.name} and {defender.name} fight',own_damage=attack_damage,enemy_damage=defend_damage)
            damaged=[(p,attacker,defend_damage),(owner,defender,attack_damage)]
            death_triggers=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(death_triggers)
            self.check_sba();self._ltb_trigger_frames.pop()
            damage_triggers=[]
            for controller,permanent,amount in damaged:
                if permanent.name=='High Priest of Penance' and amount>0:
                    trigger=self._high_priest_damage_trigger(self.players[permanent.controller],permanent)
                    if trigger:damage_triggers.append(trigger)
            if death_triggers or damage_triggers:self.resolve_simultaneous_triggers('Domri fight triggers',death_triggers+damage_triggers,starter=p)
        return self.put_registered_stack_item(p,domri,'two target creatures fight',resolve_fight,[attacker,defender])


    def activate_sage_refereed(self,p):
        sage=self.perm(p,'Sage of the Maze')
        if not sage or sage.tapped or sage.summoning_sick:return False
        gates=sum(1 for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land and ('Gate' in sim.CARDDEF[q.name].type_line.split(' // ')[0] or q.counters.get('everything',0)>0))
        lands=[q for q in p.battlefield if sim.is_land_permanent(q)]
        land=self._request_decision('sage_land_target',p,f'Sage of the Maze: animate target land as {2*gates}/{2*gates} Citizen with haste.',lands,lambda q:q.name)
        if not land:return False
        sage.tapped=True
        def resolve_sage():
            if self.target_still_legal(p,p,land,source_name=sage.name):
                land.metadata['sage_animated']=True;land.metadata['sage_power']=2*gates
                self.log('land_animation',p.name,'Sage of the Maze',f'{land.name} becomes {2*gates}/{2*gates} Citizen with haste until EOT',target=land.name)
        return self.put_registered_stack_item(p,sage,f'target land becomes {2*gates}/{2*gates}',resolve_sage,[land])

    def activate_stage_refereed(self,p,stage):
        lands=[(owner,q) for owner in self.players.values() for q in owner.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land]
        target=self._request_decision('stage_copy_target',p,"Thespian's Stage: choose target land to copy.",lands,
            lambda row:f'{row[0].name}: {row[1].name}'+(f' (copying {row[1].copy_of})' if row[1].copy_of else ''))
        return self.activate_stage(p,stage,target[1],target[0])

    def activate_stage(self,p,stage,land=None,owner=None):
        if land is None:return self.activate_stage_refereed(p,stage)
        if not self.can_activate_stage(p,stage):return False
        stage.tapped=True
        if not self.pay(p,sim.CardDef("Thespian's Stage activation",'{2}','Ability','',1,p.name,2)):
            stage.tapped=False;return False
        owner=owner or self.players[land.controller]
        def resolve_stage(chosen=land):
            chosen_owner=self.players[chosen.controller]
            if chosen not in chosen_owner.battlefield or not sim.is_land_permanent(chosen):return
            stage.copy_of=chosen.copy_of or chosen.name
            self.log('land_copy',p.name,stage.name,f"Thespian's Stage becomes a copy of {stage.copy_of}",target_uid=chosen.uid)
            if stage.copy_of=='Dark Depths':
                others=[q for q in p.battlefield if q.uid!=stage.uid and (q.copy_of or q.name)=='Dark Depths']
                if others:
                    keep=self.stage_depths_legend_choice(p,stage,others)
                    for permanent in [stage]+others:
                        if permanent is not keep and permanent in p.battlefield:self.leave_battlefield(p,permanent,'graveyard','legend rule: Dark Depths')
                if stage in p.battlefield:self.queue_dark_depths_state_trigger(p,stage,"Thespian's Stage copied Dark Depths")
        return self.put_registered_stack_item(p,stage,'become a copy of target land',resolve_stage,[land],
            copy_factory=lambda new_targets:lambda:resolve_stage(new_targets[0]))

    def can_activate_stage(self,p,stage):
        # The copy effect explicitly retains this printed ability.
        return super().can_activate_stage(p,stage)

    def queue_dark_depths_state_trigger(self,p,depths,event='Dark Depths has no ice counters'):
        if depths not in p.battlefield or (depths.copy_of or depths.name)!='Dark Depths' or depths.counters.get('ice',0)>0:return False
        self.resolve_simultaneous_triggers(event,[{
            'controller':p,'source':'Dark Depths','label':'sacrifice it; if you do, create Marit Lage',
            'resolve':lambda:self.resolve_dark_depths_zero(p,depths),
        }],starter=self.players[self.turn_order[self.active_idx]])
        return True

    def activate_dark_depths(self,p,depths):
        if depths not in p.battlefield or (depths.copy_of or depths.name)!='Dark Depths' or depths.counters.get('ice',0)<=0:return False
        if not self.pay(p,sim.CardDef('Dark Depths activation','{3}','Ability','',1,p.name,3)):return False
        def resolve_remove():
            if depths not in p.battlefield or (depths.copy_of or depths.name)!='Dark Depths' or depths.counters.get('ice',0)<=0:return
            depths.counters['ice']-=1
            self.log('counter_removed',p.name,depths.name,f'Removed an ice counter from {depths.name}',remaining=depths.counters['ice'])
            if depths.counters['ice']==0:self.queue_dark_depths_state_trigger(p,depths)
        return self.put_registered_stack_item(p,depths,'remove an ice counter',resolve_remove)

    def stage_depths_legend_choice(self,p,stage,others):
        candidates=[stage]+list(others)
        return self._request_decision(
            'legend_rule',p,
            f"Legend rule: choose which Dark Depths to keep. Keeping the counterless {stage.name} copy allows its trigger to make Marit Lage.",
            candidates,
            lambda land:(f"{stage.name} copying Dark Depths (0 ice counters)" if land.uid==stage.uid else f'{land.name} ({land.counters.get("ice",0)} ice counters)'))

    def omo_counter_trigger(self,p,source,reason):
        selections=[]
        for kind,predicate in (('land',sim.is_land_permanent),('creature',self.is_creature_perm)):
            choices=[q for owner,q in self.all_permanents() if predicate(q) and
                     self.target_still_legal(p,owner,q,source_name=source)]
            chosen=self._request_decision(
                f'omo_{kind}_counter',p,f'Omo {reason}: choose up to one target {kind} for an everything counter.',
                choices,lambda q:f'{q.controller}: {q.name} (everything={q.counters.get("everything",0)})',
                allow_pass=True) if choices else None
            if chosen:selections.append((chosen,predicate))
        targets=[q for q,_ in selections]
        def resolve_omo():
            # Recheck each target independently, using its current controller.
            # The same land creature can occupy both target slots.
            legal=[q for q,predicate in selections if predicate(q) and
                   self.target_still_legal(p,self.players[q.controller],q,source_name=source)]
            for q in legal:self.add_counters(p,q,'everything',1,f'Omo {reason}')
        return {'controller':p,'source':'Omo, Queen of Vesuva',
                'label':'put everything counters on '+(', '.join(q.name for q in targets) if targets else 'no targets'),
                'targets':targets,'resolve':resolve_omo}

    def omo_everything(self,p,source=None):
        source=source or next(q for q in p.battlefield if (q.copy_of or q.name)=='Omo, Queen of Vesuva')
        self._dispatch_etb_triggers(p,source,[self.omo_counter_trigger(p,source,'ETB')])

    def xolatoyac_counter(self,p,reason):
        lands=[]
        for pp in self.players.values():
            for q in pp.battlefield:
                if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land:lands.append((pp,q))
        z=self._request_decision('xolatoyac_land_target',p,f'Xolatoyac {reason}: choose target land for a flood counter.',lands,lambda z:f'{z[0].name}: {z[1].name}')
        if z:
            owner,target=z
            source=self.perm(p,'Xolatoyac, the Smiling Flood')
            trigger={'controller':p,'source':'Xolatoyac, the Smiling Flood','label':f'put a flood counter on target {target.name}','targets':[target],
                     'resolve':lambda:self.add_counters(p,target,'flood',1,f'Xolatoyac {reason}') if self.target_still_legal(p,owner,target) else None}
            if reason=='ETB' and source:self._dispatch_etb_triggers(p,source,[trigger])
            else:self.resolve_simultaneous_triggers(f'Xolatoyac {reason}',[trigger],starter=p)

    # ---------- interactive spell responses ----------
    def resolve_counterspell_effect(self,p,c,target_caster,target_card):
        marker=next((item for item in self.stack if isinstance(item,dict)
                     and item.get('uid')==target_card.uid),None)
        if marker is None:
            self.log('spell_fizzle',p.name,c.d.name,
                     f'{c.d.name} has no legal spell target and does not counter {target_card.d.name}')
            return False
        self.stack.remove(marker)
        self.log('counterspell',p.name,c.d.name,
                 f'{c.d.name} counters {target_card.d.name}',target=target_card.d.name)
        if c.d.name=='Remand':
            commander=target_card.uid==target_caster.dungeon.get('commander_uid')
            to_command=self._request_decision('remand_commander_destination',target_caster,
                f'Remand: put {target_card.d.name} in the command zone instead of returning it to hand?',
                [True,False],lambda value:'command zone' if value else 'hand') if commander else False
            if to_command:
                target_caster.commander=target_card
                self.log('commander_zone',target_caster.name,target_card.d.name,'Remand: command zone instead of hand',uid=target_card.uid)
            else:target_caster.hand.append(target_card)
            self.draw(p,1,'Remand')
        elif c.d.name=='Summary Dismissal':
            target_caster.exile.append(target_card)
            self.log('exile',target_caster.name,target_card.d.name,
                     'Summary Dismissal exiles the spell from the stack')
        elif c.d.name=='Arcane Denial':self.schedule_arcane_denial(target_caster,p)
        return True

    def react_to_spell(self,caster,c):
        # A response nested inside a cast trigger can already have countered
        # this spell before the original cast frame resumes.
        countered_during_trigger=self.__dict__.setdefault(
            '_countered_during_cast_trigger',set())
        if c.uid in countered_during_trigger:
            countered_during_trigger.remove(c.uid)
            return True
        completed=self.__dict__.setdefault('_completed_counter_windows',set())
        if c.uid in completed:return False
        if c.d.is_creature and caster.dungeon.get('domri_uncounterable_turn')==self.turn_number:
            self.log('uncounterable',caster.name,c.d.name,'Domri +1 prevents the creature spell from being countered')
            return False
        # Every opponent with a legal counter gets an explicit strategic choice. First successful counter ends window.
        caster_index=self.turn_order.index(caster.name)
        responders=[self.players[self.turn_order[(caster_index+offset)%len(self.turn_order)]]
                    for offset in range(1,len(self.turn_order))]
        priority_order=[caster]+responders
        for responder_index,op in enumerate(responders,1):
            if op.eliminated:continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.active_priority_seat_snooze(op,'spell response'):
                self.log('priority_seat_snooze_auto',op.name,None,
                         'spell response: automatically passes while SNOOZE ALL is active')
                continue
            if self.decision_surface_revision<SCHEDULER_SURFACE_REVISION and self.priority_autopasses_current_stack(op):continue
            available=[]
            for nm in ['Swan Song','Fierce Guardianship','Remand','Counterspell','Arcane Denial','Summary Dismissal']:
                cc=self.card_in_hand(op,nm)
                if not cc:continue
                legal=True
                if nm=='Swan Song' and not (c.d.is_instant or c.d.is_sorcery or c.d.is_enchantment):legal=False
                if nm=='Fierce Guardianship' and c.d.is_creature:legal=False
                free=(nm=='Fierce Guardianship' and self.controls_commander(op))
                if legal and (free or self.can_pay(op,cc.d) is not None):available.append(('spell',cc,free))
            glen=self.perm(op,'Glen Elendra Archmage')
            glen_cost=sim.CardDef('Glen Elendra Archmage activation','{U}','Ability','',1,op.name,1)
            if glen and not c.d.is_creature and self.can_pay(op,glen_cost) is not None:available.append(('glen',glen,False))
            if not available:continue
            if self.scheduler_suppresses_priority(op,'spell response',[('counter_response',row[1],{}) for row in available]):continue
            context={'spell_uid':c.uid,'spell_name':c.d.name}
            counter_sources=[row[1] for row in available]
            object_passes=self.active_priority_object_passes(op,'spell response')
            general_actions=[
                action for action in self.legal_priority_actions(
                    op,'spell response',context,include_held=True)
                if (not any(action[1] is source for source in counter_sources) and
                    not self.priority_action_is_object_passed(action,object_passes))]
            earlier_general=any(
                self.player_has_unsuppressed_general_priority(
                    earlier,'spell response',context)
                for earlier in priority_order[:responder_index])
            wake_available=[
                row for row in available
                if not any(entry.source is row[1] for entry in object_passes)]
            all_wake_general=list(general_actions)
            visible_general=[] if earlier_general else general_actions
            wake_general=[] if earlier_general else all_wake_general
            if not wake_available and not wake_general:continue
            wake_actions=[('counter_response',row[1],{}) for row in wake_available]+all_wake_general
            pass_on=self.priority_pass_on_option(op,wake_actions)
            response_options=[('counter',row) for row in wake_available]+[
                ('priority_action',action) for action in visible_general]
            for entry in ([] if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION else object_passes):
                if not any(row[0]=='wake' and row[1] is entry.source for row in response_options):
                    response_options.append(('wake',entry.source))
            if pass_on:response_options.append(('pass_on',pass_on))
            if self.stack and self.decision_surface_revision<SCHEDULER_SURFACE_REVISION:response_options.append(('autopass_stack',('autopass_stack',None,{})))
            concede=self.priority_concede_action()
            if concede:response_options.append(('concede',concede))
            def response_label(row):
                if row[0] in {'priority_action','pass_on','autopass_stack','concede'}:
                    return self.priority_prompt_action_label(op,row[1])
                if row[0]=='wake':
                    return self.priority_action_label(op,('wake_priority_object',row[1],{}))
                return self.priority_source_prompt_label(
                    op,row[1][1],
                    ('Glen Elendra Archmage ability {U}, sacrifice' if row[1][0]=='glen' else
                     f'{row[1][1].d.name}'+(' [free]' if row[1][2] else '')))
            z=self._request_decision(
                'counterspell_response',op,
                (f'{caster.name} casts {c.d.name}. Choose a response or PASS.'
                 if self.decision_surface_revision>=SCHEDULER_SURFACE_REVISION else
                 f'{caster.name} casts {c.d.name}. Take an instant-speed action, wake a snoozed object, PASS ON the sole unsuppressed source, AUTOPASS this stack, or pass.'),
                response_options,
                response_label,
                allow_pass=True,gameplan_access=True,
                request_metadata=self.priority_pass_on_request_metadata(
                    op,pass_on,response_options.index(('pass_on',pass_on)))
                    if pass_on else None)
            if not z:
                if not earlier_general:self.mark_specialized_priority_pass(op)
                continue
            if z[0]=='concede':
                self.concede_from_priority(op,'spell response')
                if self.winner or self.pilot_terminal:return True
                continue
            if z[0]=='priority_action':
                self.execute_bridged_priority_action(op,z[1],context)
                return self.react_to_spell(caster,c)
            if z[0]=='pass_on':
                if z[1][0]=='pass_on_priority_objects':
                    payload=self._decision_auxiliary_payload(
                        getattr(self,'_last_decision_id','')).get('pass_on_batch') or {}
                    self.arm_priority_object_pass_batch(
                        op,z[1],'spell response',payload)
                else:
                    schedule=self._request_pass_on_schedule(op,z[1][1])
                    self.arm_priority_object_pass(op,z[1][1],'spell response',schedule)
                continue
            if z[0]=='wake':
                self.clear_priority_object_pass(
                    op,z[1],
                    f'{self.priority_source_name(z[1])} was explicitly woken in a spell response')
                return self.react_to_spell(caster,c)
            if z[0]=='autopass_stack':
                self.start_priority_stack_autopass(op);continue
            kind,cc,free=z[1]
            self.clear_specialized_priority_passes()
            self.clear_priority_object_pass(
                op,cc,f'{self.priority_source_name(cc)} was selected; its object pass is cancelled')
            if kind=='glen':
                self.pay(op,glen_cost);self.leave_battlefield(op,cc,'graveyard','Glen Elendra Archmage activation cost')
                self.log('counterspell',op.name,'Glen Elendra Archmage',f'Activated ability counters {c.d.name}',target=c.d.name)
                return True
            target_marker=next((item for item in self.stack if isinstance(item,dict)
                                and item.get('uid')==c.uid),None)
            if target_marker is None:return False
            if not self.cast(op,cc,free=free,counter_target=(caster,c)):return False
            return target_marker not in self.stack
        return False

    # ---------- exact LRW / Felidar target choices ----------
    def lrw_etb(self,p,q):
        candidates=[]
        for pp in self.players.values():
            for x in pp.battlefield:
                if x.uid==q.uid:continue
                d=sim.CARDDEF.get(x.name)
                if d and (d.is_artifact or d.is_enchantment):candidates.append((pp,x))
        z=self._request_decision('lrw_target',p,'Leonin Relic-Warder ETB: choose artifact/enchantment to exile, or decline.',candidates,
                    lambda z:f'{z[0].name}: {z[1].name}',allow_pass=True)
        if not z:return
        pp,x=z
        def resolve_lrw():
            # An ETB trigger exists independently of its source.  In particular,
            # if Relic-Warder leaves before this trigger resolves, its leaves
            # trigger returns nothing and this trigger must still exile the
            # announced target indefinitely.
            if self.target_still_legal(p,pp,x):
                uid=x.uid;self.leave_battlefield(pp,x,'exile','Leonin Relic-Warder ETB');q.metadata['exiled_uid']=uid
        self._dispatch_etb_triggers(p,q,[{'controller':p,'source':q.name,'label':f'exile target {x.name}','targets':[x],'resolve':resolve_lrw}])

    def felidar_etb(self,p,q):
        trigger={'controller':p,'source':q.name,'label':'choose another permanent to blink',
                 'targets':[],'resolve':lambda:None}
        def prepare_felidar():
            # A trigger created while another spell or ability is resolving is
            # put on the stack only after that object finishes and SBAs run.
            # Choose its target at that point so, for example, a completed Saga
            # is not advertised after its final chapter resolves.
            candidates=[t for t in p.battlefield if t.uid!=q.uid]
            target=self._request_decision(
                'felidar_blink',p,
                'Felidar Guardian ETB: choose another permanent to blink, or decline.',
                candidates,
                lambda permanent:permanent.name+(f' (attached to {permanent.attached_to})' if permanent.attached_to else ''),
                allow_pass=True)
            if not target:
                trigger['label']='blink no target';return
            def resolve_felidar():
                if target not in p.battlefield:return
                # A linked reanimation Aura alone does not establish a loop:
                # its sacrifice trigger resolves after this entire blink.
                # Resolve the actual objects; broader shortcuts require proof.
                self.blink_own_permanent(p,target,'Felidar Guardian ETB');self.check_ream_combo()
            trigger['label']=f'exile and return target {target.name}'
            trigger['targets']=[target]
            trigger['resolve']=resolve_felidar
        trigger['prepare']=prepare_felidar
        self._dispatch_etb_triggers(p,q,[trigger])

    # ---------- Gifts ----------
    def resolve_gifts(self,p):
        # Choose 1-4 distinct cards manually. Then the opponent who is strategically best placed
        # to make the choice selects the two cards going to graveyard (or all if <=2).
        if self.selection_batch_enabled():
            available=list(p.library)
            pile=self._request_selection('gifts_selection',p,'Gifts Ungiven: choose up to four cards with different names (choosing none is legal).',available,
                lambda card:f'{card.d.name} [{card.uid}]',maximum=4,groups=[card.d.name for card in available])
        else:
            available=list(p.library);pile=[]
            for slot in range(4):
                c=self._request_decision('gifts_select',p,f'Gifts Ungiven: choose search card {slot+1} (or stop).',
                            [x for x in available if x not in pile],lambda c:f'{c.d.name} [{c.d.mana_cost}]',allow_pass=(slot>0))
                if c is None:break
                pile.append(c)
        if len(pile)<=2:
            grave=list(pile);hand=[]
        else:
            # Table chooses which opponent makes the Gifts choice; default rules don't care who, strategy does.
            chooser=self._request_decision('gifts_opponent',p,'Choose the opponent who makes the Gifts split.',self.opponents(p),lambda x:x.name)
            pairs=[]
            for i in range(len(pile)):
                for j in range(i+1,len(pile)):
                    g=[pile[i],pile[j]];h=[x for x in pile if x not in g];pairs.append((g,h))
            z=self._request_decision('gifts_split',chooser,'Gifts Ungiven: choose two cards to put into Reaminatour graveyard.',pairs,
                        lambda z:'GY: '+', '.join(c.d.name for c in z[0])+' | HAND: '+', '.join(c.d.name for c in z[1]))
            grave,hand=z
        for c in grave:
            p.library.remove(c);p.graveyard.append(c);self.mark_appearance(c.d.name);self.log('gifts_split',p.name,c.d.name,'Gifts → graveyard')
        for c in hand:
            p.library.remove(c);p.hand.append(c);self.mark_appearance(c.d.name);self.log('gifts_split',p.name,c.d.name,'Gifts → hand')
        self.rng.shuffle(p.library);self.log('shuffle',p.name,None,'Shuffle after Gifts Ungiven')

    # ---------- combat ----------
    @staticmethod
    def is_battle_perm(q):
        definition=sim.CARDDEF.get(q.copy_of or q.name)
        return bool(definition and 'Battle' in definition.type_line.split(' // ')[0]
                    and not q.metadata.get('transformed_invasion'))

    def request_combat_target(self,p):
        opts=[]
        goaders={q.metadata.get('goaded_by') for q in p.battlefield if self.can_attack(q) and q.metadata.get('goaded_by')}
        alternatives=[op for op in self.opponents(p) if op.name not in goaders]
        for op in self.opponents(p):
            if alternatives and op.name in goaders:continue
            opts.append((op,None))
            for q in op.battlefield:
                if self.is_planeswalker_perm(q):opts.append((op,q))
            for owner,battle in self.all_permanents():
                if (self.is_battle_perm(battle) and
                    battle.metadata.get('battle_protector')==op.name and
                    p.name!=op.name):
                    opts.append((op,battle))
        return self._request_decision('combat_target',p,'Choose combat defender / planeswalker target.',opts,
                         lambda z:(
                             f'{z[0].name}' if z[1] is None else
                             (f'{z[1].name} ({z[1].counters.get("defense",0)} defense; protected by {z[0].name})'
                              if self.is_battle_perm(z[1]) else
                              f'{z[0].name} — {z[1].name} ({z[1].counters.get("loyalty",0)} loyalty)')))

    def _request_attackers(self,p,target_spec):
        if isinstance(target_spec,tuple):defender,defended_object=target_spec
        else:defender,defended_object=target_spec,None
        defended_label=(
            f'{defended_object.name} protected by {defender.name}'
            if defended_object is not None and self.is_battle_perm(defended_object)
            else (f'{defended_object.name} controlled by {defender.name}' if defended_object is not None else defender.name))
        attackers=[q for q in p.battlefield if self.can_attack(q)]
        required=[q for q in attackers if q.metadata.get('goaded_by') and
                  (defender.name!=q.metadata.get('goaded_by') or len(self.opponents(p))<=1)]
        for q in required:self.log('goad_attack_requirement',p.name,q.name,f'{q.name} must attack {defended_label} if able')
        return self._request_multi_decision(
            'declare_attackers',p,
            f'Declare every attacker into {defended_label} as one batch. Select all attackers now.',
            attackers,
            lambda q:(f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}'+
                      (' [REQUIRED: goaded]' if q in required else '')),
            allow_pass=not required,required=required)

    def combat_response_window(self,active):
        """Beginning-of-combat APNAP window after start-of-combat triggers."""
        return self.priority_window(active,'beginning of combat')

    def offer_evacuation_response(self,active,reason):
        responded=False
        for responder in self.opponents(active):
            card=self.card_in_hand(responder,'Evacuation')
            if not card or self.can_pay(responder,card.d) is None:continue
            choices=[True,False]
            if self.decision_surface_revision>=2:choices.append('concede')
            cast_it=self._request_decision(
                'evacuation_response',responder,
                f'{reason}. Cast Evacuation now?',
                choices,lambda value:(
                    'CONCEDE — leave this game immediately' if value=='concede' else
                    ('cast Evacuation' if value else 'hold Evacuation')),
                gameplan_access=True)
            if cast_it=='concede':
                self.concede_from_priority(responder,'Evacuation response')
                if self.winner or self.pilot_terminal:return responded
                continue
            if cast_it:
                self.cast(responder,card);responded=True
        return responded

    def resolve_beginning_of_combat_triggers(self,p):
        """Collect every beginning-of-combat trigger before any one resolves."""
        triggers=[]
        def add(source,label,resolver,targets=None):
            triggers.append({'controller':p,'source':source,'label':label,'targets':targets or [],'resolve':resolver})
        ozolith=self.perm(p,'The Ozolith')
        if ozolith and ozolith.counters:
            choices=[q for q in p.battlefield if self.is_creature_perm(q)]
            target=self._request_decision('ozolith_move_target',p,'The Ozolith: choose target creature for all stored counters, or decline.',choices,lambda q:q.name,allow_pass=True) if choices else None
            if target:
                def resolve_ozolith(ozolith=ozolith,target=target):
                    if ozolith not in p.battlefield or target not in p.battlefield:return
                    stored=dict(ozolith.counters);ozolith.counters.clear()
                    for kind,count in stored.items():self.add_counters(p,target,kind,count,'The Ozolith beginning of combat')
                add(ozolith.name,f'move all counters to {target.name}',resolve_ozolith,[target])
        talent=self.perm(p,"Innkeeper's Talent")
        if talent:
            choices=[q for q in p.battlefield if self.is_creature_perm(q)]
            target=self._request_decision('innkeeper_combat_target',p,"Innkeeper's Talent: choose target creature you control.",choices,lambda q:q.name) if choices else None
            if target:add(talent.name,f'put a +1/+1 counter on {target.name}',lambda target=target:self.add_counters(p,target,'+1/+1',1,talent.name) if target in p.battlefield else None,[target])
        partners=self.perm(p,'Halana and Alena, Partners')
        if partners:
            choices=[q for q in p.battlefield if self.is_creature_perm(q) and q.uid!=partners.uid]
            target=self._request_decision('halana_target',p,'Halana and Alena: choose another target creature you control.',choices,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}') if choices else None
            amount=self.effective_power(partners)
            def resolve_partners(target=target,amount=amount):
                if target not in p.battlefield:return
                self.add_counters(p,target,'+1/+1',amount,partners.name)
                target.metadata.setdefault('temporary_keywords',[]).append('haste');target.keywords.add('haste')
            if target:add(partners.name,f'put {amount} counters on {target.name}; it gains haste',resolve_partners,[target])
        xenagos=self.perm(p,'Xenagos, God of Revels')
        if xenagos:
            choices=[q for q in p.battlefield if self.is_creature_perm(q) and q.uid!=xenagos.uid]
            target=self._request_decision('xenagos_target',p,'Xenagos: choose another target creature you control.',choices,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}') if choices else None
            def resolve_xenagos(target=target):
                if target not in p.battlefield:return
                amount=self.effective_power(target);target.metadata['xenagos_bonus']=target.metadata.get('xenagos_bonus',0)+amount
                target.metadata.setdefault('temporary_keywords',[]).append('haste');target.keywords.add('haste')
            if target:add(xenagos.name,f'{target.name} gets +X/+X and haste',resolve_xenagos,[target])
        helm=self.perm(p,'Helm of the Host')
        if helm and helm.attached_to:
            equipped=next((q for q in p.battlefield if q.uid==helm.attached_to),None)
            if equipped:add(helm.name,f'create a nonlegendary token copy of {equipped.name}',lambda equipped=equipped:self.create_copiable_token(p,equipped,haste=True,nonlegendary=True) if equipped in p.battlefield else None)
        growth=self.perm(p,'Unnatural Growth')
        if growth:
            def resolve_growth():
                for creature in [permanent for permanent in p.battlefield if self.is_creature_perm(permanent)]:
                    creature.metadata['unnatural_growth_power_bonus']=creature.metadata.get('unnatural_growth_power_bonus',0)+self.effective_power(creature)
                    creature.metadata['unnatural_growth_toughness_bonus']=creature.metadata.get('unnatural_growth_toughness_bonus',0)+self.effective_toughness(creature)
            add(growth.name,'double the power and toughness of each creature you control',resolve_growth)
        warfare=self.perm(p,'Desert Warfare')
        if warfare:
            def resolve_warfare():
                deserts=[q for q in p.battlefield if sim.is_land_permanent(q) and sim.land_has_type(q,'Desert',p)]
                if len(deserts)>=5:
                    for _ in range(min(len(deserts),30)):self.token(p,'Sand Warrior',1,1,{'haste'})
            deserts=[q for q in p.battlefield if sim.is_land_permanent(q) and sim.land_has_type(q,'Desert',p)]
            if len(deserts)>=5:add(warfare.name,'create a Sand Warrior for each Desert you control',resolve_warfare)
        hakbal=self.perm(p,'Hakbal of the Surging Soul')
        if hakbal:
            def resolve_hakbal_explores():
                remaining=[q for q in p.battlefield if self.is_creature_perm(q) and self.has_creature_type(q,'Merfolk')]
                while remaining and p.library:
                    creature=self._request_decision('hakbal_explore_order',p,'Hakbal: choose the next Merfolk to explore.',remaining,lambda q:q.name)
                    remaining.remove(creature);top=p.library[-1];self.log('explore_reveal',p.name,creature.name,f'Hakbal explore reveals {top.d.name}')
                    if top.d.is_land:p.library.pop();p.hand.append(top);self.log('explore_land',p.name,creature.name,f'{top.d.name} to hand')
                    else:
                        self.add_counters(p,creature,'+1/+1',1,'Hakbal explore')
                        bury=self._request_decision('explore_nonland',p,f'{creature.name} explores {top.d.name}: keep it on top or put it in graveyard?',[False,True],lambda value:'put in graveyard' if value else 'keep on top')
                        if bury:p.library.pop();p.graveyard.append(top);self.log('explore_grave',p.name,creature.name,f'{top.d.name} to graveyard')
            add(hakbal.name,'each Merfolk you control explores',resolve_hakbal_explores)
        jyoti=self.perm(p,'Jyoti, Moag Ancient')
        if jyoti:
            def resolve_jyoti():
                bonus=self.effective_power(jyoti)
                for permanent in p.battlefield:
                    if sim.is_land_permanent(permanent) and self.is_creature_perm(permanent):permanent.metadata['jyoti_bonus']=bonus
            add(jyoti.name,'land creatures get +X/+X until end of turn',resolve_jyoti)
        self.resolve_simultaneous_triggers('beginning of combat',triggers,starter=p)

    def combat(self,p):
        # Keep deterministic trigger *resolution* but referee the strategic trigger choices.
        self.phase='combat'
        if p.eliminated:return
        spirit_turn=p.dungeon.get('infinite_spirits_turn')
        if spirit_turn is not None and self.turn_number>spirit_turn:
            for opponent in list(self.opponents(p)):
                if not opponent.eliminated:self.lose_life(opponent,max(1,opponent.life),'combat damage from arbitrarily large flying Spirit army')
            if not self.winner:
                self.winner=p.name;self.win_turn=self.turn_number;self.win_reason='combat damage from arbitrarily large Ghostly Dancers Spirit army'
                self.log('winner',p.name,'Ghostly Dancers',self.win_reason)
            return
        self.resolve_beginning_of_combat_triggers(p)
        # Minsc loyalty choice is material.
        if False and p.name=='Minsc & Boo':
            cmd=self.perm(p,'Minsc & Boo, Timeless Heroes');boo=self.perm(p,'Boo')
            opts=[]
            if cmd:
                opts.append('plus')
                if boo and cmd.counters.get('loyalty',0)>=2:opts.append('minus')
            if opts:
                mode=self._request_decision('minsc_loyalty',p,'Choose Minsc & Boo loyalty ability.',opts,lambda x:'+1 counters' if x=='plus' else '-2 sacrifice Boo / damage / draw')
                if mode=='minus':
                    opp=self._request_decision('minsc_minus_target',p,'Choose opponent for Minsc -2 damage.',self.opponents(p),lambda x:f'{x.name} life={x.life}')
                    power=self.power(boo);cmd.counters['loyalty']-=2;self.leave_battlefield(p,boo,'graveyard','Minsc & Boo -2 sacrifice');self.lose_life(opp,power,'Minsc & Boo -2 damage');self.draw(p,min(power,40),'Minsc & Boo -2 draw')
                    self.log('planeswalker_activation',p.name,cmd.name,f'-2 sacrifices Boo for {power} damage and {power} cards',target=opp.name)
                else:self.activate_minsc_plus_refereed(p,cmd)
        # All beginning-of-combat objects are collected above into one APNAP batch.
        # Handle the remaining non-choice combat-start effects using base logic fragments where safe.
        if False and p.name=='Minsc & Boo':
            inn=self.perm(p,"Innkeeper's Talent")
            if inn:
                q=self.strongest_creature(p)
                if q:self.add_counters(p,q,'+1/+1',1,"Innkeeper's Talent")
            ha=self.perm(p,'Halana and Alena, Partners')
            if ha:
                candidates=[z for z in p.battlefield if self.is_creature_perm(z) and z.uid!=ha.uid]
                q=self._request_decision('halana_target',p,'Halana and Alena: choose creature for counters/haste.',candidates,lambda q:f'{q.name} {self.power(q)}/{self.toughness(q)}') if candidates else None
                if q:
                    n=max(1,self.power(ha));self.add_counters(p,q,'+1/+1',n,'Halana and Alena');q.keywords.add('haste')
        if False and p.name=='Minsc & Boo' and self.perm(p,'Xenagos, God of Revels'):
            q=self.strongest_creature(p)
            if q:q.metadata['xenagos_bonus']=self.power(q);q.keywords.add('haste');self.log('combat_buff',p.name,'Xenagos, God of Revels',f'Xenagos buffs {q.name}')
        if False and p.name=='Minsc & Boo' and self.perm(p,'Unnatural Growth'):
            for q in p.battlefield:
                if self.is_creature_perm(q):q.metadata['unnatural_growth']=True
        if False and p.name=='Omo' and self.perm(p,'Desert Warfare'):
            deserts=[q for q in p.battlefield if sim.CARDDEF.get(q.name) and sim.CARDDEF[q.name].is_land and ('Desert' in sim.CARDDEF[q.name].type_line or q.counters.get('everything',0)>0)]
            if len(deserts)>=5:
                for _ in range(min(len(deserts),30)):self.token(p,'Sand Warrior',1,1,{'haste'})
                self.log('desert_warfare',p.name,'Desert Warfare',f'Created {len(deserts)} Sand Warriors')
        if False and p.name=='Omo' and self.perm(p,'Hakbal of the Surging Soul'):
            merfolk=[q for q in list(p.battlefield) if self.is_creature_perm(q) and ((sim.CARDDEF.get(q.name) and 'Merfolk' in sim.CARDDEF[q.name].type_line) or q.counters.get('everything',0)>0)]
            for q in merfolk:
                if not p.library:break
                top=p.library[-1];self.log('explore_reveal',p.name,q.name,f'Hakbal explore reveals {top.d.name}')
                if top.d.is_land:
                    p.library.pop();p.hand.append(top);self.log('explore_land',p.name,q.name,f'{top.d.name} to hand')
                else:
                    self.add_counters(p,q,'+1/+1',1,'Hakbal explore')
                    bury=self._request_decision('explore_nonland',p,f'{q.name} explores {top.d.name}: keep it on top or put it in graveyard?',[False,True],lambda x:'put in graveyard' if x else 'keep on top')
                    if bury:
                        p.library.pop();p.graveyard.append(top);self.log('explore_grave',p.name,q.name,f'{top.d.name} → graveyard')
        if False and p.name=='Omo':
            jy=self.perm(p,'Jyoti, Moag Ancient')
            if jy:
                bonus=self.power(jy)
                for q in p.battlefield:
                    d=sim.CARDDEF.get(q.name)
                    if q.metadata.get('sage_animated') or q.metadata.get('march_animated') or q.name=='Forest Dryad' or (d and d.is_land and self.is_creature_perm(q)):
                        q.metadata['jyoti_bonus']=bonus
                self.log('combat_buff',p.name,'Jyoti, Moag Ancient',f'Land creatures get +{bonus}/+{bonus} this combat')
        self.combat_response_window(p)
        if p.eliminated or self.winner or self.pilot_terminal:return
        attackers=[q for q in p.battlefield if self.can_attack(q)]
        if not attackers:return
        target=self.request_combat_target(p);defender=target[0]
        chosen=self._request_attackers(p,target)
        if not chosen:return
        # Propaganda payment is a per-attacker strategic choice.
        if target[1] is None and self.perm(defender,'Propaganda'):
            paid=[]
            for a in chosen:
                tax=sim.CardDef('Propaganda attack tax','{2}','Ability','',1,p.name,2)
                if self.can_pay(p,tax) is None:continue
                yn=self._request_decision('propaganda_pay',p,f'Pay {{2}} for {a.name} to attack {defender.name}?',[True,False],lambda x:'pay' if x else 'do not pay')
                if yn:self.pay(p,tax);paid.append(a)
            chosen=paid
        if chosen:
            p.dungeon['attacked_turn']=self.turn_number
            self.resolve_combat(p,target,chosen)

    def activate_minsc_plus_refereed(self,p,cmd):
        legal=[q for q in p.battlefield if self.is_creature_perm(q) and ({'trample','haste'} & self.keywords_for(q))]
        target=self._request_decision('minsc_plus_target',p,'Minsc & Boo +1: choose a creature with trample or haste for three +1/+1 counters, or choose none.',legal,
                    lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}',allow_pass=True) if legal else None
        if target:self.add_counters(p,target,'+1/+1',3,'Minsc +1')
        cmd.counters['loyalty']=cmd.counters.get('loyalty',3)+1
        self.log('planeswalker_activation',p.name,cmd.name,f'+1 puts counters on {target.name if target else "no target"}')
        return True

    def ozolith_move_target(self,p,ozolith,targets):
        return self._request_decision(
            'ozolith_move_target',p,
            'The Ozolith: move all stored counters onto target creature, or decline.',
            targets,lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}',allow_pass=True)

    def resolve_combat(self,attacker,target_spec,atk):
        target,defended_object=target_spec
        battle=defended_object if defended_object is not None and self.is_battle_perm(defended_object) else None
        pw=defended_object if defended_object is not None and self.is_planeswalker_perm(defended_object) else None
        for a in atk:
            if 'vigilance' not in self.keywords_for(a):a.tapped=True
        defended=(f'{battle.name} protected by {target.name}' if battle is not None else
                  (f'{pw.name} controlled by {target.name}' if pw is not None else target.name))
        combat_context={'attackers':[a.uid for a in atk],'defender':target.name,
                        'defended_object':defended_object.uid if defended_object is not None else None,
                        'destination_kind':'battle' if battle else ('planeswalker' if pw else 'player'),
                        'destination_name':defended,
                        'attacker_destinations':{
                            a.uid:{'kind':'battle' if battle else ('planeswalker' if pw else 'player'),
                                   'name':defended_object.name if defended_object is not None else target.name,
                                   'display_name':defended,
                                   'uid':defended_object.uid if defended_object is not None else None,
                                   'defending_player':target.name}
                            for a in atk}}
        self.wake_priority_object_passes(
            target,
            f'{attacker.name} attacked {defended}; {target.name} receives priority to respond')
        self.clear_priority_seat_snooze(
            target,
            f'{attacker.name} attacked {defended}; {target.name} wakes to respond and declare blockers')
        triggers=[]
        def add(source,label,resolver,targets=None,controller=attacker):
            triggers.append({'controller':controller,'source':source,'label':label,'targets':targets or [],'resolve':resolver})
        if any(q.name=='Kalonian Hydra' for q in atk):
            def resolve_hydra():
                for t in [z for z in attacker.battlefield if self.is_creature_perm(z) and z.counters.get('+1/+1',0)>0]:
                    self.add_counters(attacker,t,'+1/+1',t.counters.get('+1/+1',0),'Kalonian Hydra attack double')
            add('Kalonian Hydra','double the +1/+1 counters on each creature you control',resolve_hydra)
        if self.perm(attacker,'Sun Titan') and any(a.name=='Sun Titan' for a in atk):
            choices=[card for card in attacker.graveyard if card.d.is_permanent and card.d.mv<=3]
            card=self._request_decision('sun_titan_target',attacker,'Sun Titan attack trigger: choose target permanent card with mana value 3 or less.',choices,lambda card:card.d.name) if choices else None
            if card:add('Sun Titan',f'return {card.d.name}',lambda card=card:self.put_grave_creature_bf(attacker,card,'Sun Titan attack') if card in attacker.graveyard and card.d.is_creature else (attacker.graveyard.remove(card),self._put_card_bf(attacker,card,'Sun Titan attack')) if card in attacker.graveyard else None)
        for attacking_omo in [a for a in atk if (a.copy_of or a.name)=='Omo, Queen of Vesuva']:
            triggers.append(self.omo_counter_trigger(attacker,attacking_omo,'attack'))
        if any(a.name=='Xolatoyac, the Smiling Flood' for a in atk):
            choices=[(owner,q) for owner,q in self.all_permanents() if sim.is_land_permanent(q) and (owner is attacker or not self.has_hexproof(q))]
            chosen=self._request_decision('xolatoyac_land_target',attacker,'Xolatoyac attack: choose target land.',choices,lambda row:f'{row[0].name}: {row[1].name}') if choices else None
            if chosen:
                owner,land=chosen
                add('Xolatoyac, the Smiling Flood',f'put a flood counter on {land.name}',lambda land=land:self.add_counters(attacker,land,'flood',1,'Xolatoyac attack') if land in owner.battlefield else None,[land])
        if any(a.name=='Aven Courier' for a in atk):
            choices=[q for q in attacker.battlefield]
            target_perm=self._request_decision('aven_courier_target',attacker,'Aven Courier: choose target permanent you control.',choices,lambda q:q.name) if choices else None
            if target_perm:
                def resolve_courier(target_perm=target_perm):
                    counter_types=sorted({kind for permanent in attacker.battlefield for kind,count in permanent.counters.items() if count>0})
                    if target_perm not in attacker.battlefield or not counter_types:return
                    kind=self._request_decision('aven_counter_kind',attacker,'Aven Courier: choose a kind of counter on a permanent you control.',counter_types,lambda value:value)
                    if target_perm.counters.get(kind,0)==0:self.add_counters(attacker,target_perm,kind,1,'Aven Courier')
                add('Aven Courier',f'put a chosen kind of counter on {target_perm.name} if absent',resolve_courier,[target_perm])
        if any(a.name=='Restless Fortress' for a in atk):
            add('Restless Fortress',f'{target.name} loses 2 life and you gain 2 life',lambda:(self.lose_life(target,2,'Restless Fortress'),self.gain_life(attacker,2,'Restless Fortress')))
        if any(a.name=='The Restoration of Eiganjo' and a.metadata.get('transformed_restoration') for a in atk):
            add('Architect of Restoration','create a 1/1 Spirit token',lambda:self.token(attacker,'Spirit',1,1))
        for aura_owner in self.players.values():
            for aura in [q for q in aura_owner.battlefield if q.name=='Parasitic Impetus' and q.attached_to in {a.uid for a in atk}]:
                add(aura.name,f'{attacker.name} loses 2 life and {aura_owner.name} gains 2 life',lambda aura_owner=aura_owner:(self.lose_life(attacker,2,'Parasitic Impetus'),self.gain_life(aura_owner,2,'Parasitic Impetus')),controller=aura_owner)
        if attacker.name=='Omo' and any(a.name=='Hakbal of the Surging Soul' for a in atk):
            def resolve_hakbal():
                lands=[c for c in attacker.hand if c.d.is_land]
                opts=[('draw',None)]+[('land',c) for c in lands]
                z=self._request_decision('hakbal_attack',attacker,'Hakbal attack trigger: put a land from hand onto battlefield, or decline and draw a card.',opts,lambda z:'decline - draw' if z[0]=='draw' else 'put '+z[1].d.name+' onto battlefield')
                if z[0]=='draw':self.draw(attacker,1,'Hakbal attack')
                else:
                    c=z[1];attacker.hand.remove(c);q=self._put_card_bf(attacker,c,'Hakbal attack land');q.summoning_sick=False
            add('Hakbal of the Surging Soul','put a land from hand onto battlefield or draw',resolve_hakbal)
        self.resolve_simultaneous_triggers('attack triggers',triggers,starter=attacker)
        self.priority_window(attacker,'after attackers are declared',
                             combat_context)
        if attacker.eliminated or target.eliminated or self.winner or self.pilot_terminal:return
        atk=[a for a in atk if a in attacker.battlefield and self.is_creature_perm(a)
             and a.metadata.get('removed_from_combat_turn')!=self.turn_number]
        if not atk:return
        # CR 506.4: the blocker packet describes creatures still in combat,
        # not the declaration before responses removed attackers.
        combat_context={**combat_context,'attackers':[a.uid for a in atk],
                        'attacker_destinations':{a.uid:combat_context['attacker_destinations'][a.uid]
                                                 for a in atk}}
        blockers=[q for q in target.battlefield if self.is_creature_perm(q) and not q.tapped and self.effective_toughness(q)>0]
        assignments={a.uid:[] for a in atk}
        unused=list(blockers)
        if self.combat_blocker_batch==2:
            from .block_declaration import specification,HELP
            spec=specification(self,atk,blockers)
            if any(spec['eligibility_groups'].values()):
                assignments=self._request_multi_decision('blockers_declaration',target,
                    f'Declare all blockers for the attack on {defended} in ONE response.',
                    blockers,lambda q:f'{q.name} [{q.uid}] {self.effective_power(q)}/{self.effective_toughness(q)}',
                    scheduler_passable=False,request_metadata={'response_type':'block_declaration',
                        'response_help':HELP,'block_declaration':spec,'combat_context':combat_context})
        # Defender assigns blockers attacker by attacker. This supports multi-block for menace.
        for a in ([] if self.combat_blocker_batch==2 else sorted(atk,key=self.effective_power,reverse=True)):
            if a.metadata.get('unblockable_turn')==self.turn_number:continue
            legal=[b for b in unused if self.can_block(b,a)]
            need=2 if 'menace' in self.keywords_for(a) else 1
            if len(legal)<need:continue
            if self.combat_blocker_batch:
                picked=self._request_multi_decision('blockers_assignment',target,
                    f'Choose all blockers for {a.name} [{a.uid}] {self.effective_power(a)}/{self.effective_toughness(a)} attacking {defended}. '
                    f'Select comma-separated options in one response, or 0 for no block. A block requires at least {need} creature(s).',
                    legal,lambda q:f'{q.name} [{q.uid}] {self.effective_power(q)}/{self.effective_toughness(q)}',
                    allow_pass=True,scheduler_passable=False,request_metadata={
                        'combat_context':combat_context,'blocking_attacker_uid':a.uid,'min_selected_if_any':need})
                assignments[a.uid]=picked
                for b in picked:unused.remove(b)
                continue
            requirement=f' (requires {need} blockers)' if need>1 else ''
            decision=self._request_decision('block_decision',target,f'Block {a.name} {self.effective_power(a)}/{self.effective_toughness(a)} attacking {defended}?{requirement}', [True,False],lambda x:'block' if x else 'do not block',request_metadata={'combat_context':combat_context})
            if not decision:continue
            picked=[]
            while [x for x in legal if x not in picked]:
                b=self._request_decision('blocker_assignment',target,f'Choose a blocker for {a.name} attacking {defended}'+(' (minimum not yet met).' if len(picked)<need else ', or stop adding blockers.'),
                    [x for x in legal if x not in picked],lambda q:f'{q.name} {self.effective_power(q)}/{self.effective_toughness(q)}',allow_pass=len(picked)>=need,request_metadata={'combat_context':combat_context})
                if b is None:break
                picked.append(b)
                if len(picked)<need:continue
            assignments[a.uid]=picked
            for b in picked:
                if b in unused:unused.remove(b)
        block_triggers=[]
        for blockers_for_attacker in assignments.values():
            for blocker in blockers_for_attacker:
                if blocker.name=='The Restoration of Eiganjo' and blocker.metadata.get('transformed_restoration'):
                    block_triggers.append({'controller':target,'source':'Architect of Restoration','label':'create a 1/1 Spirit token','resolve':lambda target=target:self.token(target,'Spirit',1,1)})
        self.resolve_simultaneous_triggers('block triggers',block_triggers,starter=attacker)
        blocked_attackers={uid for uid,blockers_for_attacker in assignments.items() if blockers_for_attacker}
        self.priority_window(attacker,'after blockers are declared',
                             {**combat_context,'attackers':[a.uid for a in atk],
                              'blocks':{uid:[b.uid for b in bs] for uid,bs in assignments.items()}})
        if attacker.eliminated or target.eliminated or self.winner or self.pilot_terminal:return
        atk=[a for a in atk if a in attacker.battlefield and self.is_creature_perm(a)
             and a.metadata.get('removed_from_combat_turn')!=self.turn_number]
        if not atk:return
        assignments={a.uid:[b for b in assignments.get(a.uid,[])
                            if b in target.battlefield and self.is_creature_perm(b)] for a in atk}
        return self.resolve_combat_damage_steps(attacker,target,defended_object,atk,assignments,blocked_attackers)

    def defeat_battle(self,battle):
        controller=self.players[battle.controller]
        if battle not in controller.battlefield:return False
        uid=battle.uid;physical_owner=self.players[battle.owner]
        self.leave_battlefield(controller,battle,'exile','last defense counter removed')
        card=next((card for card in physical_owner.exile if card.uid==uid),None)
        if card is None:return False
        cast_back=self._request_decision(
            'battle_defeat_cast',controller,
            'Invasion of Theros was defeated. Cast it transformed as Ephara, Ever-Sheltering without paying its mana cost?',
            [True,False],lambda value:'cast Ephara transformed' if value else 'leave Invasion exiled')
        if not cast_back:return False
        physical_owner.exile.remove(card)
        returned=sim.Perm(
            uid,battle.name,battle.owner,controller.name,False,True,{},None,None,False,4,4,set(),self.turn_number,
            {'transformed_invasion':True,'additional_enchantment':True})
        controller.battlefield.append(returned);controller.enchantments_entered_this_turn+=1
        self.mark_appearance(battle.name,cast=True,realized=True)
        self.log('cast_transformed',controller.name,battle.name,
                 'Cast transformed without paying its mana cost; Ephara, Ever-Sheltering entered the battlefield',uid=uid,
                 **({'cast_decision_id':next((row['decision_id'] for row in reversed(self.decisions)
                      if row['actor']==controller.name),None)} if self.planning_contract>=3 else {}))
        self.on_enchantment_etb(controller,returned)
        return True

    def _assign_combat_damage(self,controller,source,blockers,amount,trample):
        """Return ({blocker: damage}, defending-object damage) under current rules.

        Since the 2024 combat update there is no damage-assignment order.  The
        pilot may divide damage among all blockers; trample damage can reach the
        defended object only after lethal has been assigned to every blocker.
        """
        if not blockers:return {},amount
        assigned=[[blocker,0] for blocker in blockers]
        face=0
        minimums=[0 for _ in blockers]
        if trample:
            lethal=[(1 if 'deathtouch' in self.keywords_for(source) else max(0,self.effective_toughness(blocker)-blocker.metadata.get('damage_marked',0))) for blocker in blockers]
            maximum=max(0,amount-sum(lethal))
            face=self._request_decision('trample_assignment',controller,
                f'{source.name}: choose damage to the defended object (0-{maximum}); lethal must be assigned to every blocker first.',
                list(range(maximum+1)),lambda value:str(value)) if maximum else 0
            if face:minimums=list(lethal)
        remaining=amount-face
        for index,blocker in enumerate(blockers):
            minimum=minimums[index]
            if index==len(blockers)-1:
                assigned[index][1]=remaining;break
            later_min=sum(minimums[index+1:])
            maximum=remaining-later_min
            choices=list(range(minimum,maximum+1))
            value=self._request_decision('combat_damage_assignment',controller,
                f'{source.name}: assign damage to {blocker.name}; {remaining} remains for this and later blockers.',
                choices,lambda amount:str(amount))
            assigned[index][1]=value;remaining-=value
        return assigned,face

    def _high_priest_damage_trigger(self,controller,priest):
        choices=[(owner,target) for owner,target in self.all_permanents() if not sim.is_land_permanent(target) and
                 self.target_still_legal(controller,owner,target,source_name='High Priest of Penance')]
        chosen=self._request_decision('high_priest_target',controller,
            'High Priest of Penance was dealt damage: choose up to one target nonland permanent to destroy.',
            choices,lambda row:f'{row[0].name}: {row[1].name}',allow_pass=True) if choices else None
        if not chosen:return None
        owner,target=chosen
        return {'controller':controller,'source':'High Priest of Penance','label':f'destroy target {target.name}','targets':[target],
                'resolve':lambda:self.destroy(owner,target,'High Priest of Penance') if self.target_still_legal(controller,owner,target) and not sim.is_land_permanent(target) else None}

    def resolve_combat_damage_steps(self,attacker,defender,defended_object,attackers,assignments,blocked_attackers=None):
        battle=defended_object if defended_object is not None and self.is_battle_perm(defended_object) else None
        planeswalker=defended_object if defended_object is not None and self.is_planeswalker_perm(defended_object) else None
        blocked_attackers=set(blocked_attackers or ())
        had_first_step=any({'first_strike','double_strike'} & self.keywords_for(creature)
                           for creature in attackers+[blocker for rows in assignments.values() for blocker in rows])
        steps=['first_strike','regular'] if had_first_step else ['regular']
        for step in steps:
            attackers=[creature for creature in attackers if creature in attacker.battlefield and
                       not creature.metadata.get('removed_from_combat_turn')==self.turn_number]
            if not attackers:break
            damage_to_creatures={};damage_sources={};defending_damage=[];lifelink={}
            batched={}
            if self.combat_damage_batch:
                from .combat_damage import specification,HELP
                sources=[]
                for source in attackers:
                    keywords=self.keywords_for(source)
                    deals=bool({'first_strike','double_strike'} & keywords) if step=='first_strike' else ('first_strike' not in keywords or 'double_strike' in keywords)
                    blockers=[b for b in assignments.get(source.uid,[]) if b in defender.battlefield and b.metadata.get('removed_from_combat_turn')!=self.turn_number]
                    if not deals or not blockers:continue
                    trample=('trample' in keywords or self.perm(attacker,"Garruk's Uprising") is not None or
                             (self.perm(attacker,'Kodama of the West Tree') is not None and source.counters.get('+1/+1',0)>0))
                    sources.append((source,blockers,self.effective_power(source),trample))
                spec,batched=specification(self,sources,step,defender,defended_object)
                if spec['sources']:
                    selected=self._request_multi_decision('combat_damage_batch',attacker,
                        'Assign all discretionary combat damage in this '+step+' step in ONE response.',
                        [s for s,_,_,_ in sources if s.uid in {row['uid'] for row in spec['sources']}],
                        lambda s:f'{s.name} [{s.uid}]',scheduler_passable=False,
                        request_metadata={'response_type':'combat_damage','response_help':HELP,'combat_damage':spec})
                    batched.update(selected)
            for source in attackers:
                keywords=self.keywords_for(source)
                source_dealt=0
                deals=(bool({'first_strike','double_strike'} & keywords) if step=='first_strike'
                       else ('first_strike' not in keywords or 'double_strike' in keywords))
                if not deals:continue
                blockers=[blocker for blocker in assignments.get(source.uid,[]) if blocker in defender.battlefield and
                          not blocker.metadata.get('removed_from_combat_turn')==self.turn_number]
                was_blocked=bool(assignments.get(source.uid,[]))
                trample=('trample' in keywords or self.perm(attacker,"Garruk's Uprising") is not None or
                         (self.perm(attacker,'Kodama of the West Tree') is not None and source.counters.get('+1/+1',0)>0))
                if blockers:
                    if self.combat_damage_batch:
                        row=batched[source.uid];distribution=[(b,row['blockers'][b.uid]) for b in blockers];face=row['defender']
                    else:distribution,face=self._assign_combat_damage(attacker,source,blockers,self.effective_power(source),trample)
                    for blocker,amount in distribution:
                        if amount<=0:continue
                        if self.protection_prevents_damage(source,blocker):
                            self.log('damage_prevented',blocker.controller,source.name,f'Protection prevents {amount} combat damage to {blocker.name}',target_uid=blocker.uid,amount=amount,step=step)
                            continue
                        row=damage_to_creatures.setdefault(blocker.uid,[blocker,0]);row[1]+=amount
                        damage_sources.setdefault(blocker.uid,[]).append((source,amount))
                        source_dealt+=amount
                    if face:defending_damage.append((source,face));source_dealt+=face
                elif source.uid not in blocked_attackers or trample:
                    amount=self.effective_power(source);defending_damage.append((source,amount));source_dealt+=amount
                if 'lifelink' in keywords or source.metadata.get('lifelink_turn')==self.turn_number or self.perm(attacker,'Sorin, Vengeful Bloodlord'):
                    row=lifelink.setdefault(attacker.name,[attacker,0]);row[1]+=source_dealt

            # Blocking creatures assign their full power to the creature they block.
            for source in attackers:
                for blocker in [blocker for blocker in assignments.get(source.uid,[]) if blocker in defender.battlefield and
                                blocker.metadata.get('removed_from_combat_turn')!=self.turn_number]:
                    keywords=self.keywords_for(blocker)
                    deals=(bool({'first_strike','double_strike'} & keywords) if step=='first_strike'
                           else ('first_strike' not in keywords or 'double_strike' in keywords))
                    if not deals:continue
                    amount=self.effective_power(blocker)
                    if amount and not self.protection_prevents_damage(blocker,source):
                        row=damage_to_creatures.setdefault(source.uid,[source,0]);row[1]+=amount
                        damage_sources.setdefault(source.uid,[]).append((blocker,amount))
                    elif amount:
                        self.log('damage_prevented',source.controller,blocker.name,f'Protection prevents {amount} combat damage to {source.name}',target_uid=source.uid,amount=amount,step=step)
                    if 'lifelink' in keywords and not self.protection_prevents_damage(blocker,source):
                        row=lifelink.setdefault(defender.name,[defender,0]);row[1]+=amount

            damaged_priests=[]
            for uid,(creature,amount) in damage_to_creatures.items():
                if amount<=0:continue
                creature.metadata['damage_marked']=creature.metadata.get('damage_marked',0)+amount
                sources=damage_sources.get(uid,[])
                if any('deathtouch' in self.keywords_for(source) and dealt>0 for source,dealt in sources):creature.metadata['deathtouch_damage_turn']=self.turn_number
                self.log('combat_damage_creature',attacker.name,None,f'{creature.name} is dealt {amount} combat damage',target_uid=creature.uid,amount=amount,step=step)
                if creature.name=='High Priest of Penance':damaged_priests.append((self.players[creature.controller],creature))

            if battle is not None:
                total=sum(amount for _,amount in defending_damage if amount>0)
                if total and any(battle in owner.battlefield for owner in self.players.values()):
                    battle.counters['defense']=battle.counters.get('defense',0)-total
                    self.log('combat_damage_battle',attacker.name,None,
                             f'Attackers deal {total} damage to {battle.name}; {max(0,battle.counters["defense"])} defense remains',
                             amount=total,target_uid=battle.uid,step=step)
                    if battle.counters.get('defense',0)<=0:self.defeat_battle(battle)
            for source,amount in defending_damage:
                if amount<=0 or battle is not None:continue
                if planeswalker and planeswalker in defender.battlefield:
                    planeswalker.counters['loyalty']=planeswalker.counters.get('loyalty',0)-amount
                    self.log('combat_damage_planeswalker',attacker.name,source.name,f'{source.name} deals {amount} to {planeswalker.name}',amount=amount,target_uid=planeswalker.uid,step=step)
                else:
                    self.lose_life(defender,amount,'combat damage')
                    if source.name==sim.COMMANDERS.get(attacker.name):
                        defender.commander_damage[attacker.name]=defender.commander_damage.get(attacker.name,0)+amount
                        self.log('commander_damage',attacker.name,source.name,f'{defender.name} has taken {defender.commander_damage[attacker.name]} commander damage from {attacker.name}',amount=amount)
                        if defender.commander_damage[attacker.name]>=21:
                            self.eliminate(defender,'21 commander damage')
            for player,amount in lifelink.values():
                if amount:self.gain_life(player,amount,f'{step} combat lifelink')

            # State-based actions precede placement of the damage and death
            # triggers generated by this simultaneous damage event.
            death_triggers=[];self.__dict__.setdefault('_ltb_trigger_frames',[]).append(death_triggers)
            self.check_sba();self._ltb_trigger_frames.pop()
            damage_triggers=[]
            for controller,priest in damaged_priests:
                trigger=self._high_priest_damage_trigger(controller,priest)
                if trigger:damage_triggers.append(trigger)
            combined=death_triggers+damage_triggers
            if combined:self.resolve_simultaneous_triggers(f'{step} combat damage triggers',combined,starter=attacker)
            self.priority_window(attacker,f'after {step.replace("_"," ")} combat damage')
            if self.winner or self.pilot_terminal or attacker.eliminated or defender.eliminated:break
        defended_name=(battle.name if battle is not None else (planeswalker.name if planeswalker else defender.name))
        self.log('combat_damage',attacker.name,None,f'Combat damage steps completed against {defended_name}')
        return True
    def attachments_to(self,uid):
        return [attachment for owner in self.players.values() for attachment in owner.battlefield if attachment.attached_to==uid]

    def destroy(self,p,q,reason='destroy'):
        if 'indestructible' in self.keywords_for(q):
            self.log('destroy_prevented',p.name,q.name,f'{reason}: indestructible prevents destruction',uid=q.uid);return False
        if q.metadata.get('regen_shields',0)>0:
            q.metadata['regen_shields']-=1;q.tapped=True;q.metadata.pop('damage_marked',None);q.metadata.pop('deathtouch_damage_turn',None)
            q.metadata['removed_from_combat_turn']=self.turn_number
            self.log('regenerate',p.name,q.name,f'{reason}: regeneration replaces destruction; tap, remove damage, remove from combat',uid=q.uid)
            return False
        return super().destroy(p,q,reason)

    def check_sba(self):
        outer_commander_batch='_deferred_commander_sba_choices' not in self.__dict__
        if outer_commander_batch:self.__dict__['_deferred_commander_sba_choices']=[]
        existing=bool(self.__dict__.get('_ltb_trigger_frames',[]));generated=[]
        if not existing:self.__dict__.setdefault('_ltb_trigger_frames',[]).append(generated)
        # Back faces and type-changing effects can make a permanent a
        # planeswalker even when its front-face CardDef is not one.  Loyalty
        # SBAs therefore consume the continuous view rather than printed type.
        for owner in self.players.values():
            self.check_boo_legend_rule(owner)
            for permanent in list(owner.battlefield):
                if self.is_planeswalker_perm(permanent) and permanent.counters.get('loyalty',0)<=0:
                    self.leave_battlefield(owner,permanent,'graveyard','state-based loyalty <= 0')
        # Protection can make an Aura attachment illegal.  Equipment stays on
        # the battlefield but becomes unattached; the fixed pod has no colored
        # Equipment, while every Aura here follows the ordinary Aura SBA.
        for aura_owner in self.players.values():
            for aura in list(aura_owner.battlefield):
                definition=sim.CARDDEF.get(aura.copy_of or aura.name)
                is_aura=bool(definition and 'Aura' in definition.type_line) or aura.name in {
                    'Animate Dead','Dance of the Dead','Necromancy','Fallen Ideal','Changing Loyalty'}
                if not is_aura or not aura.attached_to:continue
                attached=next((target for owner in self.players.values() for target in owner.battlefield if target.uid==aura.attached_to),None)
                if attached and self.source_colors(aura) & self.continuous_view(attached).rules.get('protection_colors',set()):
                    self.leave_battlefield(aura_owner,aura,'graveyard','state-based Aura attachment illegal due to protection')
        for owner in self.players.values():
            for creature in list(owner.battlefield):
                if (self.is_creature_perm(creature) and creature.metadata.get('damage_marked',0)>0 and
                        creature.metadata.get('deathtouch_damage_turn')==self.turn_number):
                    self.destroy(owner,creature,'state-based lethal deathtouch damage')
        try:
            result=super().check_sba()
        finally:
            pending_commander_choices=(
                self.__dict__.pop('_deferred_commander_sba_choices',[])
                if outer_commander_batch else []
            )
        if outer_commander_batch:
            # All state-based moves in this pass happen before any command-zone
            # choice is surfaced.  This keeps a simultaneous lethal-damage
            # event from showing later victims as though they survived merely
            # because the first commander move required pilot input.
            for owner,commander,dst,reason in pending_commander_choices:
                zone=getattr(owner,dst)
                card=next((candidate for candidate in zone if candidate.uid==commander.uid),None)
                if card and self.commander_grave_exile_choice(owner,commander,dst,reason):
                    zone.remove(card);owner.commander=card
                    self.log('commander_zone',owner.name,commander.name,
                             f'{commander.name} moved from {dst} to command zone')
        if not existing:
            self._ltb_trigger_frames.pop()
            if generated:self.resolve_simultaneous_triggers('state-based action triggers',generated,starter=self.players[self.turn_order[self.active_idx]])
        return result

    def continuous_view(self,q):
        cache=getattr(self,'_continuous_view_cache',None)
        if cache is not None and q.uid in cache:return cache[q.uid]
        effective=q.copy_of or q.name;definition=sim.CARDDEF.get(effective) or sim.CARDDEF.get(q.name)
        line=(definition.type_line.split(' // ')[0] if definition else '')
        type_parts=__import__('re').split(r'\s+(?:—|�|â€” )\s*',line,maxsplit=1)
        main=type_parts[0];subtypes=type_parts[1] if len(type_parts)>1 else ''
        types=set(main.strip().split());subtype_set=set(subtypes.strip().split())
        if sim.is_land_permanent(q):types.add('Land')
        if (q.token or (definition is None and (q.base_power or q.base_toughness))) and not q.metadata.get('noncreature_token'):types.add('Creature')
        if q.metadata.get('artifact'):types.add('Artifact')
        if effective=='Boo':types.add('Legendary');subtype_set.add('Hamster')
        if q.metadata.get('nonlegendary'):types.discard('Legendary')
        base_power,base_toughness=q.base_power,q.base_toughness
        if q.copy_of and definition and not sim.is_land_permanent(q) and not q.metadata.get('zombie_copy'):
            base_power,base_toughness=sim.base_stats(effective,definition)
        printed_colors=set(__import__('re').findall(r'[WUBRG]',definition.mana_cost.split(' // ')[0])) if definition else set()
        token_colors={
            'Boo':{'R'},'Beast':{'G'},'Ape':{'G'},'Elephant':{'G'},'Plant':{'G'},
            'Forest Dryad':{'G'},'Insect':{'G'},'Hydra':{'G'},'Frog Lizard':{'G'},
            'Spirit':{'W'},'Soldier':{'W'},'Goat':{'W'},'Vampire':{'W','B'},
            'Zombie':{'B'},'Marit Lage':{'B'},'Sand Warrior':{'R','G'},
        }
        metadata_colors=q.metadata.get('colors',q.metadata.get('color'))
        if isinstance(metadata_colors,str):metadata_colors={metadata_colors}
        colors=set(metadata_colors or token_colors.get(q.name,printed_colors))
        view=ContinuousView(q.uid,effective,q.controller,types,subtype_set,colors,set(q.keywords),base_power,base_toughness,
                            {'phased_out':bool(q.metadata.get('phased_out'))})
        effects=[];stamp=max(0,q.entered_turn)
        def effect(name,layer,fn,depends=()):effects.append(ContinuousEffect(name,layer,fn,stamp,tuple(depends)))

        # Layer 4: type-changing effects.
        if q.metadata.get('mutated'):
            effect('Darksteel Mutation types',Layer.TYPE,lambda state:(state.types.add('Artifact'),state.types.add('Creature'),state.subtypes.clear(),state.subtypes.add('Insect')))
        if q.name=='Sorin of House Markov' and q.metadata.get('transformed_sorin'):
            effect('Sorin back-face types',Layer.TYPE,lambda state:(state.types.discard('Creature'),state.types.add('Planeswalker')))
        if q.name=='The Restoration of Eiganjo' and q.metadata.get('transformed_restoration'):
            effect('Architect back-face types',Layer.TYPE,lambda state:(state.types.add('Creature'),state.subtypes.update({'Human','Monk'})))
        if q.name=='Invasion of Theros' and q.metadata.get('transformed_invasion'):
            effect('Ephara back-face types',Layer.TYPE,lambda state:(
                state.types.discard('Battle'),state.types.update({'Legendary','Enchantment','Creature'}),
                state.subtypes.discard('Siege'),state.subtypes.add('God')))
        animated=any(q.metadata.get(key)==self.turn_number for key in ('nissa_animated_turn','lumbering_animated_turn','fortress_animated_turn')) or q.metadata.get('sage_animated') or q.metadata.get('march_animated')
        if animated:effect('land animation types',Layer.TYPE,lambda state:state.types.add('Creature'))
        owner=self.players[q.controller]
        enchantment_count=sum(1 for permanent in owner.battlefield if
            ((sim.CARDDEF.get(permanent.copy_of or permanent.name) and sim.CARDDEF[permanent.copy_of or permanent.name].is_enchantment) or permanent.metadata.get('additional_enchantment')))
        starfield=self.perm(owner,'Starfield of Nyx')
        if starfield and q.uid!=starfield.uid and 'Enchantment' in view.types and 'Aura' not in view.subtypes and enchantment_count>=5:
            effect('Starfield animation type',Layer.TYPE,lambda state:state.types.add('Creature'))
        if q.name=='Xenagos, God of Revels':
            devotion=sum((sim.CARDDEF.get(permanent.copy_of or permanent.name).mana_cost.split(' // ')[0].count('{R}')+
                          sim.CARDDEF.get(permanent.copy_of or permanent.name).mana_cost.split(' // ')[0].count('{G}'))
                         for permanent in owner.battlefield if sim.CARDDEF.get(permanent.copy_of or permanent.name))
            if devotion<7:effect('Xenagos devotion',Layer.TYPE,lambda state:state.types.discard('Creature'))
        omo_types_active=bool(q.counters.get('everything',0)>0 and sim.omo_everything_active(owner))
        if omo_types_active:
            type_dependencies=tuple(row.name for row in effects if row.layer==Layer.TYPE)
            effect('Omo all creature types',Layer.TYPE,lambda state:state.rules.__setitem__('all_creature_types','Creature' in state.types and 'Land' not in state.types),type_dependencies)
            effect('Omo all land types',Layer.TYPE,lambda state:state.rules.__setitem__('all_land_types','Land' in state.types),type_dependencies)
        if q.counters.get('flood',0)>0 and 'Land' in view.types:
            effect('Xolatoyac flood type',Layer.TYPE,lambda state:state.subtypes.add('Island'))

        # Layer 6: intrinsic, removed, granted, and duration-bound abilities.
        if q.metadata.get('mutated'):
            effect('Darksteel Mutation removes abilities',Layer.ABILITY,lambda state:state.abilities.clear())
            effect('Darksteel Mutation grants indestructible',Layer.ABILITY,lambda state:state.abilities.add('indestructible'),('Darksteel Mutation removes abilities',))
        attachments=self.attachments_to(q.uid)
        attachment_abilities={
            'Swiftfoot Boots':{'hexproof','haste'},'Celestial Armor':{'flying'},
            'Glasswing Grace // Age-Graced Chapel':{'flying','lifelink'},
            'Angelic Destiny':{'flying','first_strike'},'Fallen Ideal':{'flying'},
        }
        for attachment in attachments:
            granted=attachment_abilities.get(attachment.name,set())
            if granted:effect(f'{attachment.name} granted abilities',Layer.ABILITY,lambda state,granted=granted:state.abilities.update(granted))
        if q.name=='Essence Channeler' and owner.dungeon.get('life_lost_turn')==self.turn_number:
            effect('Essence Channeler life-lost abilities',Layer.ABILITY,lambda state:state.abilities.update({'flying','vigilance'}))
        if q.name=='Elenda, Saint of Dusk' and owner.life>40:effect('Elenda menace',Layer.ABILITY,lambda state:state.abilities.add('menace'))
        if q.name=='Twinblade Paladin' and owner.life>=25:effect('Twinblade double strike',Layer.ABILITY,lambda state:state.abilities.add('double_strike'))
        if q.name=='Invasion of Theros' and q.metadata.get('transformed_invasion') and enchantment_count>=4:
            effect('Ephara enchantment threshold',Layer.ABILITY,lambda state:state.abilities.update({'lifelink','indestructible'}))
        if q.name!='Lord of the Unreal' and self.perm(owner,'Lord of the Unreal'):
            effect('Lord of the Unreal hexproof',Layer.ABILITY,lambda state:state.abilities.add('hexproof') if 'Creature' in state.types and ('Illusion' in state.subtypes or state.rules.get('all_creature_types')) else None)
        if q.metadata.get('lumbering_animated_turn')==self.turn_number:effect('Lumbering Falls hexproof',Layer.ABILITY,lambda state:state.abilities.add('hexproof'))
        if any(q.metadata.get(key)==self.turn_number for key in ('heroic_protected_turn','celestial_hexproof_turn','liliana_hexproof_turn')):
            effect('turn hexproof',Layer.ABILITY,lambda state:state.abilities.add('hexproof'))
        if any(q.metadata.get(key)==self.turn_number for key in ('heroic_protected_turn','celestial_indestructible_turn')):
            effect('turn indestructible',Layer.ABILITY,lambda state:state.abilities.add('indestructible'))

        # Layer 7b: effects that set base P/T.
        def set_pt(power,toughness):return lambda state:(setattr(state,'power',power),setattr(state,'toughness',toughness))
        if q.metadata.get('mutated'):effect('Darksteel Mutation base PT',Layer.PT_SET,set_pt(0,1))
        if q.name=='The Restoration of Eiganjo' and q.metadata.get('transformed_restoration'):effect('Architect base PT',Layer.PT_SET,set_pt(3,4))
        if q.name=='Invasion of Theros' and q.metadata.get('transformed_invasion'):effect('Ephara base PT',Layer.PT_SET,set_pt(4,4))
        if q.metadata.get('march_animated'):effect('March animation PT',Layer.PT_SET,set_pt(q.metadata.get('march_power',0),q.metadata.get('march_toughness',0)))
        if q.metadata.get('sage_animated'):effect('Sage animation PT',Layer.PT_SET,set_pt(q.metadata.get('sage_power',0),q.metadata.get('sage_power',0)))
        if q.metadata.get('nissa_animated_turn')==self.turn_number:effect('Nissa animation PT',Layer.PT_SET,set_pt(5,5))
        if q.metadata.get('lumbering_animated_turn')==self.turn_number:effect('Lumbering animation PT',Layer.PT_SET,set_pt(3,3))
        if q.metadata.get('fortress_animated_turn')==self.turn_number:effect('Fortress animation PT',Layer.PT_SET,set_pt(1,4))
        if starfield and q.uid!=starfield.uid and 'Enchantment' in view.types and 'Aura' not in view.subtypes and enchantment_count>=5 and definition:
            mana_value=definition.mv
            if q.name=='Funeral Room // Awakening Hall':
                mana_value=(3 if q.metadata.get('funeral_unlocked') else 0)+(8 if q.metadata.get('awakening_unlocked') else 0)
            effect('Starfield base PT',Layer.PT_SET,set_pt(mana_value,mana_value),('Starfield animation type',))
        if q.metadata.get('construct_token'):
            artifacts=sum(1 for permanent in owner.battlefield if permanent.metadata.get('artifact') or
                          (sim.CARDDEF.get(permanent.copy_of or permanent.name) and sim.CARDDEF[permanent.copy_of or permanent.name].is_artifact))
            effect('Construct characteristic PT',Layer.PT_SET,set_pt(artifacts,artifacts))

        # Layer 7c: ordinary P/T modifications and doubling.
        power_bonus=toughness_bonus=0
        if q.name=='Rampant Frogantua':power_bonus+=10*sum(player.eliminated for player in self.players.values());toughness_bonus+=10*sum(player.eliminated for player in self.players.values())
        if q.name=='Ulvenwald Hydra':
            lands=sum(1 for permanent in owner.battlefield if sim.is_land_permanent(permanent));power_bonus+=max(0,lands-view.power);toughness_bonus+=max(0,lands-view.toughness)
        if q.name=='Elenda, Saint of Dusk':
            if owner.life>40:power_bonus+=1;toughness_bonus+=1
            if owner.life>=50:power_bonus+=5;toughness_bonus+=5
        if q.name=='Angel of Vitality' and owner.life>=25:power_bonus+=2;toughness_bonus+=2
        if self.perm(owner,'Leyline of Hope') and owner.life>=47 and 'Creature' in view.types:power_bonus+=2;toughness_bonus+=2
        if self.perm(owner,'Arvad the Cursed') and q.name!='Arvad the Cursed' and 'Legendary' in view.types:power_bonus+=2;toughness_bonus+=2
        if self.perm(owner,'Lord of the Unreal') and q.name!='Lord of the Unreal':
            effect('Lord of the Unreal bonus',Layer.PT_MODIFY,lambda state:(setattr(state,'power',state.power+1),setattr(state,'toughness',state.toughness+1)) if 'Creature' in state.types and ('Illusion' in state.subtypes or state.rules.get('all_creature_types')) else None)
        linked=next((a for a in owner.battlefield if a.uid==q.metadata.get('reanimated_by')),None)
        if linked:
            if linked.name=='Animate Dead':power_bonus-=1
            elif linked.name=='Dance of the Dead':power_bonus+=1;toughness_bonus+=1
        if self.perm(owner,'Domri, Anarch of Bolas'):power_bonus+=1
        if self.perm(owner,'Angel of Invention') and q.name!='Angel of Invention':power_bonus+=1;toughness_bonus+=1
        for attachment in attachments:
            if attachment.name=='Angelic Destiny':power_bonus+=4;toughness_bonus+=4
            elif attachment.name=='Celestial Armor':power_bonus+=2;toughness_bonus+=2
            elif attachment.name in {'Glasswing Grace // Age-Graced Chapel','Parasitic Impetus'}:power_bonus+=2;toughness_bonus+=2
        power_bonus+=sum(q.metadata.get(key,0) for key in ('wolf_run_power','basilisk_bonus','hashep_bonus','fixed_power_bonus','wildspeaker_bonus','ruby_attack_bonus','jyoti_bonus','xenagos_bonus','fallen_power_bonus','unnatural_growth_power_bonus'))
        toughness_bonus+=sum(q.metadata.get(key,0) for key in ('basilisk_bonus','hashep_bonus','fixed_toughness_bonus','wildspeaker_bonus','jyoti_bonus','xenagos_bonus','fallen_toughness_bonus','unnatural_growth_toughness_bonus'))
        penalty=q.metadata.get('eot_pt_penalty',0);power_bonus-=penalty;toughness_bonus-=penalty
        if power_bonus or toughness_bonus:
            effect('aggregate PT modifiers',Layer.PT_MODIFY,lambda state,power_bonus=power_bonus,toughness_bonus=toughness_bonus:(setattr(state,'power',state.power+power_bonus),setattr(state,'toughness',state.toughness+toughness_bonus)))
        plus=q.counters.get('+1/+1',0);minus=q.counters.get('-1/-1',0)
        if plus or minus:effect('PT counters',Layer.PT_COUNTERS,lambda state,delta=plus-minus:(setattr(state,'power',state.power+delta),setattr(state,'toughness',state.toughness+delta)))

        # Rule-changing information consumed by targeting/combat/action menus.
        talent=self.perm(owner,"Innkeeper's Talent")
        if talent and talent.metadata.get('level',1)>=2 and any(value>0 for value in q.counters.values()):effect('Innkeeper ward',Layer.RULE,lambda state:state.rules.__setitem__('ward_cost',1))
        if q.metadata.get('goaded_by'):effect('goad',Layer.RULE,lambda state:state.rules.__setitem__('goaded_by',q.metadata['goaded_by']))
        if q.metadata.get('unblockable_turn')==self.turn_number:effect('unblockable',Layer.RULE,lambda state:state.rules.__setitem__('unblockable',True))
        protection={color for color,turn in q.metadata.get('protection_colors_turn',{}).items() if turn==self.turn_number}
        # Printed protection is represented in the catalog keyword set (for
        # example, Karmic Guide has ``protection_black``).  Fold it into the
        # same rule projection used by temporary Alseid protection so
        # targeting, blocking, damage prevention, and Aura legality all see
        # the card's intrinsic protection.
        protection_keyword_colors={'white':'W','blue':'U','black':'B','red':'R','green':'G',
                                   'w':'W','u':'U','b':'B','r':'R','g':'G'}
        printed_protection={
            protection_keyword_colors[suffix]
            for keyword in view.abilities
            if keyword.startswith('protection_')
            for suffix in [keyword.removeprefix('protection_')]
            if suffix in protection_keyword_colors
        }
        protection.update(printed_protection)
        if protection:effect('protection',Layer.RULE,lambda state:state.rules.__setitem__('protection_colors',protection))
        result=evaluate_continuous(view,effects)
        if cache is not None:cache[q.uid]=result
        return result

    def keywords_for(self,q):return set(self.continuous_view(q).abilities)

    def has_hexproof(self,q):
        return 'hexproof' in self.continuous_view(q).abilities

    def has_ward_one(self,q):
        return self.continuous_view(q).rules.get('ward_cost')==1

    def is_planeswalker_perm(self,q):
        return 'Planeswalker' in self.continuous_view(q).types

    def death_grasp_targets(self,p):
        targets=[('player',player,player) for player in self.players.values() if not player.eliminated]
        for owner,permanent in self.all_permanents():
            if self.is_creature_perm(permanent):targets.append(('creature',owner,permanent))
            elif self.is_planeswalker_perm(permanent):targets.append(('planeswalker',owner,permanent))
        return targets

    def is_creature_perm(self,q):
        view=self.continuous_view(q)
        return not view.rules.get('phased_out') and 'Creature' in view.types

    def has_creature_type(self,q,creature_type):
        view=self.continuous_view(q)
        return bool(view.rules.get('all_creature_types') or creature_type in view.subtypes)

    def power(self,q):
        return max(0,self.continuous_view(q).power)

    def toughness(self,q):
        return max(0,self.continuous_view(q).toughness)

    def can_attack(self,q):
        if not self.is_creature_perm(q) or q.tapped:return False
        if q.summoning_sick and 'haste' not in self.keywords_for(q):return False
        return self.effective_power(q)>0

    def can_block(self,blocker,attacker):
        if not self.is_creature_perm(blocker) or blocker.tapped or self.effective_toughness(blocker)<=0:return False
        attacker_keywords=self.keywords_for(attacker);blocker_keywords=self.keywords_for(blocker)
        if 'flying' in attacker_keywords and not ({'flying','reach'} & blocker_keywords):return False
        if self.source_colors(blocker) & self.continuous_view(attacker).rules.get('protection_colors',set()):return False
        attack_controller=self.players.get(attacker.controller)
        if attack_controller:
            champion=self.perm(attack_controller,'Champion of Lambholt')
            if champion and self.effective_power(blocker)<self.effective_power(champion):return False
        return True

    def effective_power(self,q):
        return self.power(q)

    def effective_toughness(self,q):
        return self.toughness(q)

    def reset_eot_modifiers(self):
        super().reset_eot_modifiers()
        for pp in self.players.values():
            for q in pp.battlefield:
                q.metadata.pop('fallen_power_bonus',None);q.metadata.pop('fallen_toughness_bonus',None)
                for key in ('wolf_run_power','basilisk_bonus','hashep_bonus','nissa_animated_turn','nissa_power',
                            'lumbering_animated_turn','lumbering_power','fortress_animated_turn','fortress_power','fortress_toughness',
                            'unblockable_turn','unnatural_growth_power_bonus','unnatural_growth_toughness_bonus'):
                    q.metadata.pop(key,None)
                for keyword in q.metadata.pop('temporary_keywords',[]):q.keywords.discard(keyword)
                original=q.metadata.pop('temporary_copy_original',None)
                if original:
                    q.copy_of=original['copy_of'];q.base_power=original['base_power'];q.base_toughness=original['base_toughness'];q.keywords=set(original['keywords'])

    def end_step_triggers(self,p):
        triggers=[]
        elixir=self.perm(p,'Cosmos Elixir')
        if elixir:
            def resolve_elixir():
                if p.life>40:self.draw(p,1,'Cosmos Elixir end step')
                else:self.gain_life(p,2,'Cosmos Elixir end step')
            triggers.append({'controller':p,'source':elixir.name,'label':'draw a card or gain 2 life','resolve':resolve_elixir})
        xolatoyac=self.perm(p,'Xolatoyac, the Smiling Flood')
        if xolatoyac:
            def resolve_xolatoyac():
                count=0
                for q in p.battlefield:
                    if any(v>0 for v in q.counters.values()):q.tapped=False;count+=1
                self.log('untap_effect',p.name,xolatoyac.name,f'Untapped {count} permanent(s) with counters at end step')
            triggers.append({'controller':p,'source':xolatoyac.name,'label':'untap each permanent you control with a counter','resolve':resolve_xolatoyac})
        snack=self.perm(p,'Midnight Snack')
        if snack and p.dungeon.get('attacked_turn')==self.turn_number:
            def resolve_snack():
                p.dungeon['food']=p.dungeon.get('food',0)+1
                self.log('food',p.name,snack.name,'Raid creates a Food token',food=p.dungeon['food'])
            triggers.append({'controller':p,'source':snack.name,'label':'raid creates a Food token','resolve':resolve_snack})
        due=[row for row in self.pending_delayed_returns if row['due_turn']<=self.turn_number]
        self.pending_delayed_returns=[row for row in self.pending_delayed_returns if row not in due]
        for row in due:
            controller=self.players[row['controller']]
            def resolve_return(row=row):
                for owner in self.players.values():
                    card=next((card for card in owner.exile if card.uid==row['uid']),None)
                    if card:
                        owner.exile.remove(card);self._put_card_bf(owner,card,f'{row["source"]} delayed return');break
            triggers.append({'controller':controller,'source':row['source'],'label':'return the exiled card to the battlefield','resolve':resolve_return})
        self.resolve_simultaneous_triggers('beginning of end step',triggers,starter=p)

    def cleanup(self,p):
        self.phase='end_step';self.end_step_triggers(p)
        self.observe_priority_boundary('end','end_step',p)
        self.priority_window(p,'end step')
        if p.eliminated or self.winner or self.pilot_terminal:return
        if self.turn_batches:
            from .turn_batches import boundaries
            self.planning_boundaries.extend(boundaries(self,p))
        # Cleanup follows the end step without another exposed PASS ON
        # boundary, but it is still a new step and therefore empties mana.
        self.empty_mana_pools('beginning of cleanup')
        self.phase='cleanup';self.reset_eot_modifiers()
        if not self.has_no_maximum_hand_size(p):
            if self.selection_batch_enabled():
                count=max(0,len(p.hand)-7)
                if count:
                    selected=self._request_selection('cleanup_discard_selection',p,f'Cleanup: choose exactly {count} cards to discard to seven.',p.hand,
                        lambda card:f'{card.d.name} [{card.uid}]',minimum=count,maximum=count)
                    for card in selected:
                        p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Cleanup maximum hand size')
            else:
                while len(p.hand)>7:
                    card=self._request_decision('cleanup_discard',p,f'Cleanup: choose a card to discard ({len(p.hand)} cards; maximum 7).',list(p.hand),
                               lambda card:f'{card.d.name} {card.d.mana_cost}')
                    p.hand.remove(card);p.graveyard.append(card);self.log('discard',p.name,card.d.name,'Cleanup maximum hand size')
        for owner in self.players.values():
            for necromancy in list(owner.battlefield):
                if necromancy.name=='Necromancy' and necromancy.metadata.get('flash_cleanup_due',10**9)<=self.turn_number:
                    self.leave_battlefield(owner,necromancy,'graveyard','Necromancy delayed cleanup sacrifice')
        self.log('cleanup',p.name,None,'Cleanup step')

    def untap(self,p):
        for permanent in p.battlefield:
            if permanent.metadata.pop('phased_out',False):self.log('phase_in',p.name,permanent.name,f'{permanent.name} phases in',uid=permanent.uid)
        dance_locked=[]
        for creature in p.battlefield:
            aura=next((q for owner in self.players.values() for q in owner.battlefield if q.uid==creature.metadata.get('reanimated_by') and q.name=='Dance of the Dead'),None)
            if aura and creature.tapped:dance_locked.append(creature)
        super().untap(p)
        for creature in dance_locked:
            if creature in p.battlefield:creature.tapped=True

    def offer_upkeep_concession(self,p):
        if self.decision_surface_revision>=2:return False
        if p.eliminated:return False
        choice=self._request_decision(
            'upkeep_action',p,
            'Upkeep after triggers: choose CONCEDE, or pass to continue to upkeep priority.',
            [True],lambda _:'CONCEDE',allow_pass=True,gameplan_access=True)
        if not choice:return False
        self.eliminate(p,f'{p.name} conceded during upkeep')
        return True

    def turn(self,p):
        """Manual turn structure with explicit priority at every material boundary."""
        if p.eliminated:return
        self.turn_number+=1
        self.expire_turn_start_effects(p)
        if self.planning_contract>=3:self.planning_turns[p.name]=self.planning_turns.get(p.name,0)+1
        self.round=(self.turn_number-1)//4+1
        for player in self.players.values():player.cards_drawn_this_turn=0
        p.land_plays_used=0
        self.untap(p)
        self.observe_priority_boundary('beginning','upkeep',p)
        self.upkeep(p)
        self.observe_priority_boundary('end','upkeep',p)
        if p.eliminated or self.winner:return
        if self.offer_upkeep_concession(p):return
        self.priority_window(p,'upkeep after triggers')
        if p.eliminated or self.winner or self.pilot_terminal:return
        self.observe_priority_boundary('beginning','draw',p)
        self.draw_step(p)
        self.observe_priority_boundary('end','draw',p)
        self.priority_window(p,'end of draw step')
        if p.eliminated or self.winner or self.pilot_terminal:return
        p.land_play_limit=self.max_land_plays(p)
        self.observe_priority_boundary('beginning','precombat_main',p)
        self.main_phase(p,False)
        self.observe_priority_boundary('end','precombat_main',p)
        self.priority_window(p,'end of precombat main phase')
        p.dungeon.pop('domri_floating',None)
        if p.eliminated or self.winner or self.pilot_terminal:return
        self.observe_priority_boundary('beginning','combat',p)
        self.combat(p)
        self.observe_priority_boundary('end','combat',p)
        self.priority_window(p,'end of combat phase')
        if p.eliminated or self.winner or self.pilot_terminal:return
        self.observe_priority_boundary('beginning','postcombat_main',p)
        self.main_phase(p,True)
        self.observe_priority_boundary('end','postcombat_main',p)
        self.priority_window(p,'end of postcombat main phase')
        p.dungeon.pop('domri_floating',None)
        if p.eliminated or self.winner or self.pilot_terminal:return
        self.observe_priority_boundary('beginning','end_step',p)
        self.cleanup(p)
        self.assert_invariants(f'end_turn_{self.turn_number}')
        if self.planning_contract>=3 and not (p.eliminated or self.winner or self.pilot_terminal):
            self.planning_boundary(p,'own_turn_completed')

    def on_ltb(self,p,q,died=False):
        """Collect every trigger caused by one leave/death event into one APNAP batch.

        The base engine historically resolved these listeners inline.  That made
        targets invisible until resolution and made simultaneous triggers neither
        orderable nor counterable.  Continuous attachment cleanup and the ending of
        an ``until source leaves`` duration remain immediate; actual triggered
        abilities are announced here and resolved through the common trigger stack.
        """
        source_name=q.copy_of or q.name
        triggers=[]
        active=self.players[self.turn_order[self.active_idx]]
        lki_power=self.power(q)
        lki_counters=dict(q.counters)

        def add(controller,source,label,resolver,targets=None):
            triggers.append({'controller':controller,'source':source,'label':label,
                             'targets':targets or [],'resolve':resolver})

        def battlefield_object(uid):
            return next(((owner,permanent) for owner,permanent in self.all_permanents()
                         if permanent.uid==uid),None)

        def return_exiled(uid,reason):
            for owner in self.players.values():
                card=next((card for card in owner.exile if card.uid==uid),None)
                if card:
                    owner.exile.remove(card);self._put_card_bf(owner,card,reason);return True
            return False

        # Effects worded "until this leaves" end immediately, without using the
        # stack.  Oblivion Ring/LRW/Wave use separate leaves triggers below.
        if source_name in {'Touch the Spirit Realm','Prayer of Binding','Grasp of Fate'}:
            for uid in list(q.metadata.get('linked_exiled_uids',[])):
                return_exiled(uid,f'{q.name} leaves linked return')

        # Removing an Aura/equipment-derived continuous effect is immediate.
        if source_name=='Parasitic Impetus' and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found:found[1].metadata.pop('goaded_by',None)
        if source_name=='Angelic Destiny' and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found:found[1].metadata.pop('angelic_destiny_uid',None)
        if source_name=='Celestial Armor' and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found:found[1].metadata.pop('celestial_armor_uid',None)
        if source_name=='Darksteel Mutation' and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found:
                controller,target=found;original=target.metadata.pop('darksteel_original',None)
                if original:
                    target.base_power=original['base_power'];target.base_toughness=original['base_toughness']
                    target.keywords=set(original['keywords'])
                else:
                    copied=target.copy_of or target.name;definition=sim.CARDDEF.get(copied)
                    target.base_power,target.base_toughness=sim.base_stats(copied,definition)
                    target.keywords=set(sim.KEYWORDS.get(copied,set()))
                target.metadata.pop('mutated',None)
                self.log('aura_restore',controller.name,q.name,
                         f'{target.name} regains its printed characteristics',target_uid=target.uid)
        if source_name=='Fallen Ideal' and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found and found[1].metadata.pop('fallen_granted_flying',False):found[1].keywords.discard('flying')

        # When a controller leaves the game, continuous/linked cleanup above is
        # immediate, but that departed player cannot put new triggered abilities
        # on the stack or be asked to make their target choices.
        if p.eliminated:return

        ozolith=self.perm(p,'The Ozolith')
        if ozolith and q.uid!=ozolith.uid and self.is_creature_perm(q) and lki_counters:
            def resolve_ozolith(counters=lki_counters,ozolith=ozolith):
                if ozolith not in p.battlefield:return
                for kind,count in counters.items():self.add_counters(p,ozolith,kind,count,'The Ozolith leave trigger')
            add(p,'The Ozolith',f'put {lki_counters} on The Ozolith',resolve_ozolith)

        if died:
            if source_name=='Essence Channeler' and lki_counters:
                choices=[creature for creature in p.battlefield if self.is_creature_perm(creature)]
                target=self._request_decision('essence_channeler_target',p,
                    'Essence Channeler died: choose target creature you control.',choices,
                    lambda creature:f'{creature.name} {self.power(creature)}/{self.toughness(creature)}') if choices else None
                if target:
                    def resolve_channeler(target=target,counters=lki_counters):
                        if target in p.battlefield:
                            for kind,count in counters.items():self.add_counters(p,target,kind,count,'Essence Channeler death trigger')
                    add(p,q.name,f'put its counters on target {target.name}',resolve_channeler,[target])
            room=self.perm(p,'Funeral Room // Awakening Hall')
            if room and room.metadata.get('funeral_unlocked',True):
                add(p,room.name,'each opponent loses 1 life and you gain 1 life',
                    lambda:([self.lose_life(op,1,'Funeral Room death trigger') for op in self.opponents(p)],self.gain_life(p,1,'Funeral Room')))
            meathook=self.perm(p,'The Meathook Massacre')
            if meathook:
                add(p,meathook.name,'each opponent loses 1 life',
                    lambda:[self.lose_life(op,1,'Meathook own-creature death') for op in self.opponents(p)])
            for opponent in self.opponents(p):
                hook=self.perm(opponent,'The Meathook Massacre')
                if hook:add(opponent,hook.name,'gain 1 life',lambda opponent=opponent:self.gain_life(opponent,1,'Meathook opponent creature death'))
            if source_name=='Solemn Simulacrum':add(p,q.name,'draw a card',lambda:self.draw(p,1,'Solemn death'))
            if source_name=="Elenda's Hierophant":
                add(p,q.name,f'create {lki_power} Vampire tokens',
                    lambda amount=min(lki_power,40):[self.token(p,'Vampire',1,1,{'lifelink'}) for _ in range(amount)])
            if source_name=='Fiendish Panda':
                legal=[card for card in p.graveyard if card.d.is_creature and 'Bear' not in card.d.type_line
                       and card.d.mv<=lki_power and card.uid!=q.uid]
                target=self._request_decision('fiendish_panda_target',p,
                    f'Fiendish Panda died: choose target non-Bear creature card with mana value {lki_power} or less.',
                    legal,lambda card:f'{card.d.name} MV {card.d.mv}',allow_pass=True) if legal else None
                if target:
                    add(p,q.name,f'return target {target.d.name}',
                        lambda target=target:self.put_grave_creature_bf(p,target,'Fiendish Panda death trigger') if target in p.graveyard else None)

            # These Auras can be controlled by a player other than the dead
            # creature's controller, so search the whole battlefield using LKI.
            for aura_controller,aura in list(self.all_permanents()):
                if aura.attached_to!=q.uid:continue
                if aura.name=='Angelic Destiny':
                    def resolve_destiny(aura=aura,aura_controller=aura_controller):
                        owner=self.players[aura.owner]
                        if aura in aura_controller.battlefield:
                            aura_controller.battlefield.remove(aura);owner.hand.append(sim.CardObj(aura.uid,sim.CARDDEF[aura.name]))
                            self.log('return_to_hand',owner.name,aura.name,'Angelic Destiny death trigger')
                        else:
                            card=next((card for card in owner.graveyard if card.uid==aura.uid),None)
                            if card:owner.graveyard.remove(card);owner.hand.append(card);self.log('return_to_hand',owner.name,aura.name,'Angelic Destiny death trigger')
                    add(aura_controller,aura.name,'return this Aura to its owner\'s hand',resolve_destiny)
                elif aura.name=='Changing Loyalty':
                    creature_owner=self.players[q.owner]
                    def resolve_loyalty(aura_controller=aura_controller,creature_owner=creature_owner):
                        card=next((card for card in creature_owner.graveyard if card.uid==q.uid),None)
                        if card:creature_owner.graveyard.remove(card);self._put_card_bf(aura_controller,card,'Changing Loyalty death trigger')
                    add(aura_controller,aura.name,f'return {q.name} under your control',resolve_loyalty)

        if (q.copy_of or q.name) in {'Vesperlark','Reveillark'}:
            trigger=self.build_lark_ltb_trigger(p,q)
            if trigger:triggers.append(trigger)
        if died and source_name=='Glen Elendra Archmage' and lki_counters.get('-1/-1',0)==0:
            owner=self.players[q.owner]
            def resolve_persist(owner=owner):
                card=next((card for card in owner.graveyard if card.uid==q.uid),None)
                if not card:return
                owner.graveyard.remove(card);returned=self._put_card_bf(owner,card,'Glen Elendra Archmage persist')
                returned.counters['-1/-1']=1;self.log('persist',owner.name,q.name,'Returned with a -1/-1 counter',uid=q.uid)
            add(p,q.name,'persist: return it with a -1/-1 counter',resolve_persist)
        if source_name=='Fallen Ideal' and died:
            owner=self.players[q.owner]
            def resolve_fallen(owner=owner):
                card=next((card for card in owner.graveyard if card.uid==q.uid),None)
                if card:owner.graveyard.remove(card);owner.hand.append(card);self.log('return_to_hand',owner.name,q.name,'Fallen Ideal graveyard trigger')
            add(p,q.name,'return it to its owner\'s hand',resolve_fallen)
        if source_name in {'Animate Dead','Dance of the Dead','Necromancy'} and q.attached_to:
            found=battlefield_object(q.attached_to)
            if found:
                enchanted_controller,enchanted=found
                add(p,q.name,f'{enchanted_controller.name} sacrifices {enchanted.name}',
                    lambda enchanted_controller=enchanted_controller,enchanted=enchanted:self.leave_battlefield(enchanted_controller,enchanted,'graveyard',f'{q.name} left battlefield') if enchanted in enchanted_controller.battlefield else None)
        if source_name=='Leonin Relic-Warder' and q.metadata.get('exiled_uid'):
            add(p,q.name,'return the exiled card',lambda uid=q.metadata['exiled_uid']:return_exiled(uid,'Leonin Relic-Warder leaves'))
        if source_name=='Oblivion Ring':
            for uid in list(q.metadata.get('linked_exiled_uids',[])):
                add(p,q.name,'return the exiled card',lambda uid=uid:return_exiled(uid,'Oblivion Ring leaves'))
        if source_name=='Parallax Wave':
            uids=list(q.metadata.get('wave_exiled_uids',[]))
            if uids:add(p,q.name,'each player returns all cards exiled with Parallax Wave',
                        lambda uids=uids:[return_exiled(uid,'Parallax Wave leaves linked return') for uid in uids])

        frames=self.__dict__.get('_ltb_trigger_frames',[])
        if frames:
            frames[-1].extend(triggers)
            return
        self.resolve_simultaneous_triggers(f'{q.name} leaves the battlefield',triggers,starter=active)

    def build_lark_ltb_trigger(self,p,q):
        source_name=q.copy_of or q.name
        power_limit=1 if source_name=='Vesperlark' else 2
        maximum=1 if source_name=='Vesperlark' else 2
        legal=[card for card in p.graveyard if card.d.is_creature and self.card_base_power(card.d.name)<=power_limit]
        if self.selection_batch_enabled():
            selected=self._request_selection('lark_targets',p,f'{source_name} left the battlefield: choose up to {maximum} target creature cards.',legal,
                lambda card:f'{card.d.name} [{card.uid}] power={self.card_base_power(card.d.name)}',maximum=maximum)
        else:
            selected=[]
            for slot in range(maximum):
                remaining=[card for card in legal if card not in selected]
                if not remaining:break
                card=self._request_decision('lark_target',p,
                    f'{source_name} left the battlefield: choose target creature card {slot+1} of up to {maximum}.',
                    remaining,lambda card:f'{card.d.name} power={self.card_base_power(card.d.name)}',allow_pass=True)
                if not card:break
                selected.append(card)
        if not selected:return None
        def resolve_lark():
            for card in selected:
                if card in p.graveyard:self.put_grave_creature_bf(p,card,source_name+' LTB')
        return {
            'controller':p,'source':source_name,'label':'return '+', '.join(card.d.name for card in selected),
            'resolve':resolve_lark,
        }

    def lark_ltb(self,p,q):
        # Compatibility entry point for callers outside leave_battlefield().
        trigger=self.build_lark_ltb_trigger(p,q)
        if trigger:self.resolve_simultaneous_triggers(f'{q.name} leaves the battlefield',[trigger],starter=self.players[self.turn_order[self.active_idx]])

    # ---------- prevent silent old policy in remaining high-impact modules ----------
    def activate_value_abilities(self,p):
        # This routine contains many optional activations/targets; until each is externally refereed,
        # official play halts rather than silently using the old scores.
        material=[n for n in ['Sorin, Vengeful Bloodlord','Aminatou, the Fateshifter','Expedition Map','Hydra Broodmaster','Funeral Room // Awakening Hall','Midnight Snack'] if self.perm(p,n)]
        if material:
            raise UnrefereedDecisionError('Optional value-ability path needs referee conversion: '+', '.join(material))

    def attempt_combo_win(self,p,reason):
        # Combo declaration is a referee decision; responses likewise must not use old threat ranking.
        do=self._request_decision('combo_attempt',p,f'Potential deterministic loop recognized: {reason}. Attempt it now?', [True,False],lambda x:'attempt combo' if x else 'do not attempt')
        if not do:return False
        self.log('combo_attempt',p.name,None,reason)
        for op in self.opponents(p):
            options=[]
            for nm in ['Beast Within','Chaos Warp','Pongify','Utter End',"Hero's Downfall",'Murder','Breathe Your Last']:
                c=self.card_in_hand(op,nm)
                if c and self.can_pay(op,c.d) is not None:options.append(c)
            if not options:continue
            if self.decision_surface_revision>=2:options.append(('concede',None,{}))
            c=self._request_decision(
                'combo_response',op,f'{p.name} attempts {reason}. Use removal?',options,
                lambda c:('CONCEDE — leave this game immediately'
                          if isinstance(c,tuple) and c[0]=='concede' else c.d.name),
                allow_pass=True,gameplan_access=True)
            if not c:continue
            if isinstance(c,tuple) and c[0]=='concede':
                self.concede_from_priority(op,'combo response')
                if self.winner or self.pilot_terminal:return False
                continue
            # Let removal spell's own referee target selection choose among legal permanents.
            self.pay(op,c.d);op.hand.remove(c);op.graveyard.append(c);self.mark_appearance(c.d.name,cast=True,realized=True)
            self.log('combo_interaction',op.name,c.d.name,f'{c.d.name} used during combo attempt')
            self.resolve_removal_spell(op,c.d.name)
            return False
        for op in list(self.opponents(p)):
            if not op.eliminated:self.lose_life(op,max(1,op.life),'infinite combo: '+reason)
        if not self.winner:
            self.winner=p.name;self.win_turn=self.turn_number;self.win_reason=reason;self.log('winner',p.name,None,p.name+' wins via '+reason)
        return True

    def write_game(self):
        """Write the normal game narrative plus a non-ledger trigger-audit sidecar."""
        narrative=super().write_game()
        audit_path=narrative.with_name(
            f'game_{self.game_no:02d}_seed_{self.seed}_catalog_trigger_audit.json')
        payload={
            'schema':'edh.catalog_trigger_audit.v1',
            'game':self.game_no,
            'seed':self.seed,
            'audit_count':len(self.catalog_trigger_audit),
            'records':self.catalog_trigger_audit,
        }
        audit_path.write_text(
            json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        return narrative

    def write_decisions(self):
        path=self.outdir/'decisions';path.mkdir(parents=True,exist_ok=True)
        fn=path/f'game_{self.game_no:02d}_seed_{self.seed}_decisions.jsonl'
        with fn.open('w',encoding='utf8') as f:
            for d in self.decisions:f.write(json.dumps(d,separators=(',',':'))+'\n')
        return fn

    def run(self):
        """Run until a rules winner, a decision/blocker, or the configured horizon.

        Official manual play never converts a horizon into a heuristic winner.
        """
        max_global_turns=self.max_turns*4
        while not self.winner and not self.pilot_terminal and self.turn_number<max_global_turns:
            p=self.players[self.turn_order[self.active_idx]]
            try:self.turn(p)
            except PilotGameComplete:break
            self.active_idx=(self.active_idx+1)%4
            alive=[player for player in self.players.values() if not player.eliminated]
            if len(alive)==1 and not self.winner:
                self.winner=alive[0].name;self.win_turn=self.turn_number;self.win_reason='last player standing'
        if not self.winner and not self.pilot_terminal:
            self.win_reason='manual horizon reached without a rules winner'
            self.log('horizon_stop',None,None,f'No rules winner after {self.max_turns} rounds; no heuristic adjudication')
        self.assert_invariants('final')
        return self.result()

    def result(self):
        result=super().result();result['terminal']=self.pilot_terminal or ('rules_winner' if self.winner else 'horizon')
        return result


def run_one(seed:int,outdir:Path,game_no=1,max_rounds=16,decision_tape=None):
    outdir.mkdir(parents=True,exist_ok=True)
    g=ManualGame(seed,game_no,outdir,max_turns=max_rounds,decision_tape=decision_tape)
    try:
        r=g.run()
    finally:
        g.write_game();g.write_decisions()
    print(json.dumps(g.result(),indent=2))
    return g

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--seed',type=int,default=2026083160);ap.add_argument('--game-no',type=int,default=1);ap.add_argument('--outdir',default=str(Path(__file__).resolve().parent/'llm_referee_test'));ap.add_argument('--max-rounds',type=int,default=16);ap.add_argument('--script');ap.add_argument('--resume-script');ap.add_argument('--request')
    a=ap.parse_args()
    if a.script and a.resume_script:ap.error('--script and --resume-script are mutually exclusive')
    request_path=Path(a.request) if a.request else None
    tape=(DecisionTape(Path(a.script),request_path) if a.script else
          ResumeConsoleDecisionTape(Path(a.resume_script),request_path) if a.resume_script else
          ConsoleDecisionTape())
    try:run_one(a.seed,Path(a.outdir),a.game_no,a.max_rounds,tape)
    except NeedDecision as e:
        print(json.dumps({'status':'NEED_DECISION','request':e.request},indent=2));raise SystemExit(75)
