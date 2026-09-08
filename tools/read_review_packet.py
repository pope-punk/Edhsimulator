"""Print one seat's bounded review evidence without opening raw game tapes."""
import json
from pathlib import Path
import sys


def view(path):
    data=json.loads(path.read_text(encoding='utf8'))
    requirements=data['review_requirements']
    strategic=json.loads((path.parent.parent/'strategy_snapshot.json').read_text(encoding='utf8'))
    deck=next(deck for deck in strategic['decks'] if deck['label'].startswith(data['viewer']))
    notes=[note for card in deck['cards'] for note in card['notes']
           if note['note_id'] in requirements['delivered_notes']]
    plans={};seen=set()
    for pid,plan in data.get('private_continuity',{}).get('plans',{}).items():
        selected={k:plan[k] for k in ('standing_plan','short_term_plan','long_term_plan','continuity') if plan.get(k)}
        unique={key:text for key,text in selected.items() if (key,text) not in seen}
        seen.update(selected.items())
        if unique:plans[pid]=unique
    return {'viewer':data['viewer'],'requirements':requirements,'decisions':data['decisions'],
            'contexts':{did:value['request'] for did,value in data['decision_contexts'].items()},
            'plans':plans,'notes':notes,'cards':data['card_observations'],
            'rejected_answers':data['rejected_answers'],'inspections':data['inspections'],
            'events':[event for event in data['visible_events']
                if event.get('type') not in {'llm_decision','stack_add','stack_priority_pass','mana_payment',
                'trigger_stack_add','trigger_resolve','resolve','scheduler_control','scheduler_suppressed',
                'priority_closed','planner_phase_boundary','planner_turn_boundary','untap','cleanup'}]}


if __name__=='__main__':
    value=view(Path(sys.argv[1]))
    if len(sys.argv)>2:value={key:value[key] for key in sys.argv[2:]}
    print(json.dumps(value,ensure_ascii=True,separators=(',',':')))
