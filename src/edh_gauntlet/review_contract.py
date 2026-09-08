"""Bounded evidence coverage gates; assessments remain reviewer-authored."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

TOPICS=('opening','plan_execution','mana_and_timing','interaction_and_scheduler','information_boundaries')

_OPENING_KINDS={'mulligan','london_bottom'}
_MECHANICAL_EVENT_TYPES={
    'cleanup','llm_decision','mana_pool_empty','priority_closed',
    'scheduler_control','scheduler_suppressed','untap',
}


def _decision_topics(decision,request):
    """Classify a decision for deterministic first/last review anchoring."""

    kind=str(decision.get('kind',''))
    topics=[]
    if kind in _OPENING_KINDS:topics.append('opening')
    if kind not in _OPENING_KINDS and not any(
        token in kind for token in ('messageboard','combat_target','declare_attackers','block','counter')
    ):topics.append('plan_execution')
    if any(token in kind for token in ('land','main_action','mana','shock')):
        topics.append('mana_and_timing')
    scheduler=(decision.get('scheduler') or {}).get('mode','hold_full_control')
    if (any(token in kind for token in (
        'priority','counter','target','attack','block','combat','trigger','damage','phase','sacrifice'
    )) or scheduler!='hold_full_control'):
        topics.append('interaction_and_scheduler')
    if any(token in kind for token in (
        'messageboard','gifts','tutor','scry','surveil','top_order','wayfinder','sylvan'
    )):
        topics.append('information_boundaries')
    return topics


def _canonical_sha256(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(',',':'),ensure_ascii=False
    ).encode('utf-8')).hexdigest()


def _compact_scheduler(value):
    if not isinstance(value,dict):return value
    return {key:item for key,item in value.items()
            if key not in {'help','compact_legend','eligible_objects'}}


def _compact_decision_context(context):
    """Keep the legal frontier, not the repeated planning/catalog payload."""

    request=dict((context or {}).get('request') or {})
    keep={
        'game','seed','decision_id','actor','kind','round','turn','phase','prompt',
        'options','allow_pass','multi_select','required_indexes','turn_order','planning_checkpoint','rationale_policy',
        'scheduler','pilot_memory','seat_view',
    }
    compact={key:request[key] for key in keep if key in request}
    if 'scheduler' in compact:compact['scheduler']=_compact_scheduler(compact['scheduler'])
    if 'pilot_memory' in compact:
        compact['pilot_memory_ids']=[row.get('note_id') for row in compact.pop('pilot_memory')
                                     if row.get('note_id')]
    plan=request.get('private_active_plan') or {}
    if plan:
        compact['active_plan_reference']={
            key:plan[key] for key in ('projection_sha256','sources') if key in plan
        }
    return {'context_id':(context or {}).get('context_id'),'request':compact}


def review_requirements(evidence):
    decisions=evidence['decisions']
    contexts=evidence.get('decision_contexts',{})
    # Review every planning checkpoint plus bounded, deterministic first/last
    # anchors for each topic, the first use of every scheduler mode and delivered
    # note, explicit rules-issue decision references, and the terminal own-seat
    # decision. The complete accepted tape remains sealed for rules audit; making
    # every routine answer a six-field critical review merely reproduces the raw
    # transcript and crowds out actual synthesis.
    important=[];seen=set();topic_ids={topic:[] for topic in TOPICS}
    first_scheduler={};note_deliveries={};card_decisions={}
    valid={row.get('decision_id') for row in decisions}
    def add(decision_id):
        if decision_id and decision_id in valid and decision_id not in seen:
            important.append(decision_id);seen.add(decision_id)
    for decision in decisions:
        request=(contexts.get(decision['decision_id']) or {}).get('request',{})
        did=decision['decision_id']
        if request.get('planning_checkpoint'):add(did)
        for topic in _decision_topics(decision,request):topic_ids[topic].append(did)
        mode=(decision.get('scheduler') or {}).get('mode','hold_full_control')
        first_scheduler.setdefault(mode,did)
        for note in request.get('pilot_memory',[]):
            note_deliveries.setdefault(note['note_id'],[]).append(did)
        for card in decision.get('cards',[]):card_decisions.setdefault(card,[]).append(did)
    # A pair of lifecycle anchors is enough for the broad topic summaries. Card
    # analysis below owns the detailed action evidence instead of duplicating it
    # as hundreds of generic decision essays.
    if decisions:add(decisions[0]['decision_id']);add(decisions[-1]['decision_id'])
    for did in first_scheduler.values():add(did)
    for ids in note_deliveries.values():
        if ids:add(ids[0])
    for issue in (evidence.get('rules_integrity') or {}).get('issues',[]):
        for did in re.findall(r'G\d{2}-D\d{4}',str(issue.get('reason',''))):add(did)
    context_anchors=list(important)
    for ids in card_decisions.values():
        if ids and ids[0] not in context_anchors:context_anchors.append(ids[0])
        if ids and ids[-1] not in context_anchors:context_anchors.append(ids[-1])
    notes={note_id:[did for did in ids if did in seen]
           for note_id,ids in note_deliveries.items()}
    issues=(evidence.get('rules_integrity') or {}).get('issues',[])
    return {'schema':2,'critical_decisions':important,'topics':list(TOPICS),
            'delivered_notes':notes,
            'context_anchor_decisions':context_anchors,
            'card_review_cards':sorted((evidence.get('card_event_counts') or {}).keys()),
            'card_decision_ids':{
                card:[did for did in (ids[:1]+ids[-1:]) if did]
                for card,ids in sorted(card_decisions.items())
            },
            'rules_issue_ids':[row['issue_id'] for row in issues],
            'rules_issue_impact_values':['unaffected','evidence_limited','invalidated','uncertain'],
            'required_decision_fields':['known_information','intended_line','chosen_vs_alternative',
                                        'rules_check','outcome','assessment'],
            'assessment_values':['sound','execution_error','plan_error','rules_blocker','uncertain']}


def compact_evidence(evidence):
    """Convert a lossless schema-3 envelope into a bounded review packet."""

    if evidence.get('schema')==5:return evidence
    if evidence.get('schema')==4:
        result=dict(evidence)
        result['decision_contexts']={
            did:_compact_decision_context(context)
            for did,context in (result.get('decision_contexts') or {}).items()
        }
        result['schema']=5
        return result
    result=dict(evidence)
    contexts=dict(result.get('decision_contexts') or {})
    full_decisions=list(result.get('decisions') or [])
    requirements=review_requirements({**result,'decisions':full_decisions,
                                      'decision_contexts':contexts})
    critical=set(requirements['context_anchor_decisions'])
    result['decisions']=[row for row in full_decisions
                         if row.get('decision_id') in critical]
    result['decision_contexts']={
        did:_compact_decision_context(contexts[did])
        for did in requirements['context_anchor_decisions'] if did in contexts
    }
    events=list(result.get('visible_events') or [])
    omitted=Counter(str(row.get('type')) for row in events
                    if row.get('type') in _MECHANICAL_EVENT_TYPES)
    result['visible_events']=[row for row in events
                              if row.get('type') not in _MECHANICAL_EVENT_TYPES]
    embedded_inspections=result.pop('inspection_evidence',{}) or {}
    result['review_requirements']=requirements
    result['card_observations']={
        card:{
            'event_counts':dict(counts),
            'decision_ids':requirements['card_decision_ids'].get(card,[]),
        }
        for card,counts in sorted((result.get('card_event_counts') or {}).items())
    }
    result['history_provenance']={
        'accepted_own_decision_count':len(full_decisions),
        'accepted_own_decisions_sha256':_canonical_sha256(full_decisions),
        'retained_review_anchor_count':len(result['decisions']),
        'visible_event_count':len(events),
        'retained_visible_event_count':len(result['visible_events']),
        'omitted_mechanical_event_counts':dict(sorted(omitted.items())),
        'visible_events_sha256':_canonical_sha256(events),
        'full_decision_context_count':len(contexts),
        'full_decision_contexts_sha256':_canonical_sha256(contexts),
        'embedded_inspection_count':len(embedded_inspections),
        'embedded_inspections_sha256':_canonical_sha256(embedded_inspections),
    }
    result['inspection_evidence_delivery']={
        'mode':'content_addressed_on_demand',
        'count':len(embedded_inspections),
        'references_are_in':'inspections[].evidence_reference',
    }
    result['schema']=5
    return result


def review_template(evidence):
    required=evidence['review_requirements']
    return {'topics':{topic:{'decision_ids':[],'analysis':''} for topic in TOPICS},
            'plan_assessment':{
                'short_term_history':'','long_term_history':'','outcome':'',
            },
            'card_assessments':[
                {'card':card,'decision_ids':[], 'plan_context':'',
                 'observed_result':'','assessment':'','note_recommendation':'','analysis':''}
                for card in required.get('card_review_cards',[])],
            'decisions':[{ 'decision_id':did,**{field:'' for field in required['required_decision_fields']}}
                         for did in required['critical_decisions']],
            'note_effectiveness':[{ 'note_id':nid,'decision_ids':[],'assessment':'','analysis':''}
                                  for nid in required['delivered_notes']],
            'rules_issue_reviews':[
                {'issue_id':issue_id,'decision_ids':[],'impact':'','analysis':''}
                for issue_id in required.get('rules_issue_ids',[])],
            'inspection_and_rejections':'','information_boundary_audit':''}


def validate_analyses(review,evidence_by_pilot):
    analyses=review.get('pilot_analyses')
    if not isinstance(analyses,dict) or set(analyses)!=set(evidence_by_pilot):
        raise ValueError('Review requires pilot_analyses for exactly all four seats')
    for actor,evidence in evidence_by_pilot.items():
        analysis=analyses[actor];required=evidence['review_requirements']
        if not isinstance(analysis,dict):raise ValueError(f'{actor}: analysis must be an object')
        valid={row['decision_id'] for row in evidence['decisions']}
        def citations(ids):
            if not isinstance(ids,list) or (valid and not ids) or any(did not in valid for did in ids):
                raise ValueError(f'{actor}: citations must refer to this seat’s accepted decisions')
        topics=analysis.get('topics')
        if not isinstance(topics,dict) or set(topics)!=set(TOPICS):raise ValueError(f'{actor}: missing review topics')
        for topic,row in topics.items():
            if not isinstance(row,dict) or not str(row.get('analysis','')).strip():raise ValueError(f'{actor}: explain {topic}')
            citations(row.get('decision_ids'))
        plan=analysis.get('plan_assessment')
        if not isinstance(plan,dict) or set(plan)!={'short_term_history','long_term_history','outcome'}:
            raise ValueError(f'{actor}: complete the plan assessment')
        if any(not isinstance(value,str) or not value.strip() for value in plan.values()):
            raise ValueError(f'{actor}: explain the short-term plan, long-term plan, and outcome')
        cards=analysis.get('card_assessments')
        if not isinstance(cards,list) or any(not isinstance(row,dict) for row in cards):
            raise ValueError(f'{actor}: card assessments must be a list')
        card_names=[row.get('card') for row in cards]
        if (len(card_names)!=len(set(card_names)) or
                set(card_names)!=set(required.get('card_review_cards',[]))):
            raise ValueError(f'{actor}: assess every observed card exactly once')
        observations=evidence.get('card_observations') or {}
        for row in cards:
            ids=row.get('decision_ids')
            if not isinstance(ids,list) or any(did not in valid for did in ids):
                raise ValueError(f'{actor}: card citations must use retained actor-visible decisions')
            if not set(ids).issubset(set((observations.get(row['card']) or {}).get('decision_ids',[]))):
                raise ValueError(f'{actor}: card citation does not mention that card')
            if row.get('assessment') not in {
                'worked_as_planned','worked_with_caveat','underperformed',
                'mis_sequenced','not_deployed','uncertain',
            }:
                raise ValueError(f'{actor}: invalid card assessment')
            if row.get('note_recommendation') not in {'add','revise','none','uncertain'}:
                raise ValueError(f'{actor}: invalid card-note recommendation')
            for field in ('plan_context','observed_result','analysis'):
                if not isinstance(row.get(field),str) or not row[field].strip():
                    raise ValueError(f'{actor}: incomplete card assessment')
        rows=analysis.get('decisions')
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError(f'{actor}: decision reviews must be a list')
        seen=[row.get('decision_id') for row in rows]
        if len(seen)!=len(set(seen)) or not set(required['critical_decisions']).issubset(seen) or set(seen)-valid:
            raise ValueError(f'{actor}: review every critical decision exactly once using this seat’s evidence')
        for row in rows:
            if any(not isinstance(row.get(field),str) or not row[field].strip() for field in required['required_decision_fields']):
                raise ValueError(f'{actor}: incomplete critical decision review')
            if row['assessment'] not in required['assessment_values']:raise ValueError(f'{actor}: invalid decision assessment')
        notes=analysis.get('note_effectiveness')
        if not isinstance(notes,list) or any(not isinstance(row,dict) for row in notes):raise ValueError(f'{actor}: note review must be a list')
        nids=[row.get('note_id') for row in notes]
        if len(nids)!=len(set(nids)) or set(nids)!=set(required['delivered_notes']):raise ValueError(f'{actor}: assess every delivered note')
        for row in notes:
            citations(row.get('decision_ids'))
            if not set(row['decision_ids']).issubset(required['delivered_notes'][row['note_id']]):raise ValueError(f'{actor}: note was not delivered at cited decision')
            if row.get('assessment') not in {'followed','missed','contradicted','not_applicable','uncertain'} or not str(row.get('analysis','')).strip():
                raise ValueError(f'{actor}: explain note effectiveness')
        issue_rows=analysis.get('rules_issue_reviews')
        if not isinstance(issue_rows,list) or any(not isinstance(row,dict) for row in issue_rows):
            raise ValueError(f'{actor}: rules issue reviews must be a list')
        issue_ids=[row.get('issue_id') for row in issue_rows]
        if len(issue_ids)!=len(set(issue_ids)) or set(issue_ids)!=set(required.get('rules_issue_ids',[])):
            raise ValueError(f'{actor}: critically review every tagged rules issue')
        for row in issue_rows:
            ids=row.get('decision_ids')
            if not isinstance(ids,list) or any(did not in valid for did in ids):
                raise ValueError(f'{actor}: rules issue citations must refer to this seat’s accepted decisions')
            if (row.get('impact') not in required.get('rules_issue_impact_values',[]) or
                    not str(row.get('analysis','')).strip()):
                raise ValueError(f'{actor}: explain the evidence impact of each rules issue')
        for field in ('inspection_and_rejections','information_boundary_audit'):
            if not isinstance(analysis.get(field),str) or not analysis[field].strip():raise ValueError(f'{actor}: complete {field}')
        if any(row['assessment']=='rules_blocker' for row in rows):
            disposition=review.get('pilot_dispositions',{}).get(actor,{})
            if disposition.get('disposition')!='rules_blocker':raise ValueError(f'{actor}: rules blocker cannot be promoted as strategy')


INSTRUCTIONS='''
## Required evidence analysis

Complete review.pilot_analyses for all four seats using their separate evidence
packets. Every packet has an explicit review_requirements manifest and compact
actor-visible state for each bounded review anchor. For each critical decision,
record information known at that time, intended strategic line, chosen action
versus a legal alternative, rules check, outcome, and assessment. Separate later
observations from facts known at the decision. Assess every delivered note at a
cited delivery: followed, missed, contradicted, not_applicable, or uncertain.

The packet deliberately aggregates routine priority closures, scheduler bookkeeping,
untaps, cleanup and duplicated decision events. Counts and hashes preserve their
audit provenance. Inspection payloads remain in their content-addressed evidence
files and are opened only when their query is material to the review. Do not try to
reconstruct or ingest the raw accepted transcript.

The primary review unit is the card under the pilot's actual Short-Term and
Long-Term plans. Complete plan_assessment, then assess every card listed in
card_review_cards using card_observations and the card's retained first/last
decision anchors. State the applicable plan context, what happened, whether the
card worked as planned, and whether a reusable card note should be added or
revised. A note recommendation is not itself a strategy operation; add an
operation only when the evidence supports durable guidance beyond this game.

Cover opening hand/card types and mulligan counts; strategic plans versus actions
and pivot cues; mana source order and reserved interaction; target/trigger timing;
scheduler usage, wake events and lost response opportunities; inspected rules,
rejected answers, and private-information boundaries. Review card costs and Oracle
text when an interaction is uncertain. Include each pilot's opening, execution,
mana/timing, interaction/scheduling, and information-boundary topic analysis.
An execution error with adequate existing guidance still requires recording.

When the packet carries a `RULES-AFFECTED GAME` tag, review every listed issue
skeptically. Identify which cited decisions remain trustworthy, which conclusions
are limited or invalidated, and whether a proposed strategy operation has support
independent of the incorrect rules resolution. A game-breaking referee blocker is
a draw and remains tagged as quarantined within the cohort; it may still contribute
carefully bounded learning after the engine repair is recorded.

The validator checks coverage and seat-valid citations. It does not decide whether
the reasoning is sound: that is the external reviewer's responsibility. The review
context may see all four packets, but must never be reused to pilot a later game.
'''
