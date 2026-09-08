"""Structural differences with UID-keyed zones, whole additions and bounded previews."""
from .sequence_contract import size


def diff(before,after,path=''):
    if before==after:return []
    if isinstance(before,list) and isinstance(after,list) and all(
            isinstance(item,dict) and item.get('uid') for item in before+after) and before+after:
        if len({x['uid'] for x in before})==len(before) and len({x['uid'] for x in after})==len(after):
            before={x['uid']:x for x in before};after={x['uid']:x for x in after}
    if isinstance(before,dict) and isinstance(after,dict):
        rows=[]
        for key in sorted(set(before)|set(after)):
            sub=path+'/'+key.replace('~','~0').replace('/','~1')
            if key in before and key in after:rows.extend(diff(before[key],after[key],sub))
            else:rows.append({'path':sub,'before':before.get(key),'after':after.get(key),
                              'before_present':key in before,'after_present':key in after})
        return rows
    return [{'path':path,'before':before,'after':after,'before_present':True,'after_present':True}]


def preview(rows,limit=6000):
    result=[]
    for row in rows:
        if len(result)>=24 or size(result+[row])>limit:continue
        result.append(row)
    return result
