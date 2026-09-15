"""Ability inventory with explicit unverified execution claims; no inferred coverage."""
from __future__ import annotations
import argparse,ast,json
from collections import Counter,defaultdict
from pathlib import Path
from .catalog import load_catalog
from .paths import PROJECT_ROOT


def inventory(root=PROJECT_ROOT):
    root=Path(root);catalog=list(load_catalog(root/'data/catalog/cards.json'));names={c.name for c in catalog};references=defaultdict(list)
    for file in (root/'src/edh_gauntlet').glob('*.py'):
        if file.name.startswith('rules_'):continue
        tree=ast.parse(file.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Compare):continue
            mentioned={value.value for value in ast.walk(node) if isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value in names}
            for name in mentioned:references[name].append({'file':str(file.relative_to(root)),'line':node.lineno})
    rows=[]
    for card in catalog:
        for spec in (*card.abilities,*card.entry_replacements):
            ability=hasattr(spec,'ability_id');handler=spec.handler
            rows.append({'card_id':card.card_id,'card':card.name,'record_id':spec.ability_id if ability else spec.replacement_id,
                'record_type':'ability' if ability else 'entry_replacement','origin':spec.origin if ability else 'entry_replacement',
                'kind':spec.kind,'event':spec.event,'catalog_support':spec.support_status,'handler':handler,
                'execution_class':'legacy_adapter' if (handler or '').startswith('legacy:') else 'unverified',
                'review_state':'unreviewed','oracle_clause':spec.rules_text,
                'name_comparison_references':references[card.name]})
    return {'schema':1,'card_count':len(catalog),'record_count':len(rows),
        'classification_counts':dict(Counter(row['execution_class'] for row in rows)),
        'coverage_percentage':None,'coverage_note':'Raw inventory contains overlapping Oracle, registry and replacement records. Neither metadata labels nor name comparisons establish executable coverage. Clause-to-executor review is required.',
        'records':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=PROJECT_ROOT);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    value=inventory(args.root);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({key:value[key] for key in ('card_count','record_count','classification_counts','coverage_percentage')}))


if __name__=='__main__':main()
