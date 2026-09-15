"""Transactional host projection journal; replay never dispatches game actions."""
from copy import deepcopy
import json
import zlib
from .rules_adapter import digest
from .rules_durable import encoded
from .rules_state import RulesViolation

TABLES={
    'host_inputs':('request_id','actor','payload','state','receipt'),
    'host_publications':('id','actor','role','input_sha','receipt'),
    'host_messages':('id','actor','text','payload'),
    'host_evidence':('seq','actor','kind','rules_seq','payload'),
}


def delta(before,after,path=()):
    if type(before) is dict and type(after) is dict:
        changes=[]
        for key in sorted(set(before)|set(after)):
            if key not in after:changes.append(['remove',list(path+(key,))])
            elif key not in before:changes.append(['set',list(path+(key,)),after[key]])
            else:changes.extend(delta(before[key],after[key],path+(key,)))
        return changes
    return [] if encoded(before)==encoded(after) else [['set',list(path),after]]


def apply(state,changes):
    for change in changes:
        kind,path,*value=change
        if not path:
            if kind!='set':raise RulesViolation('Invalid root journal mutation')
            state=deepcopy(value[0]);continue
        target=state
        for key in path[:-1]:target=target[key]
        if kind=='remove':del target[path[-1]]
        elif kind=='set':target[path[-1]]=deepcopy(value[0])
        else:raise RulesViolation('Unknown host journal mutation')
    return state


def row_value(row):
    return [{'blob':value.hex()} if type(value) is bytes else value for value in row]


def head(connection):
    row=connection.execute('SELECT seq,sha256 FROM host_journal ORDER BY seq DESC LIMIT 1').fetchone()
    if not row:raise RulesViolation('Missing host journal')
    return {'sequence':row[0],'sha256':row[1]}


def append(connection,binding,rules_commit,changes,rows):
    previous=connection.execute('SELECT seq,sha256 FROM host_journal ORDER BY seq DESC LIMIT 1').fetchone()
    sequence=previous[0]+1 if previous else 0
    value={'schema':1,'sequence':sequence,'previous':previous[1] if previous else digest(binding),
           'rules_commit':rules_commit,'state':changes,'rows':rows}
    sha=digest(value)
    connection.execute('INSERT INTO host_journal VALUES (?,?,?)',
                       (sequence,sha,zlib.compress(encoded(value).encode(),level=1)))


def initialize(connection,binding,rules_commit,state):
    connection.execute('CREATE TABLE host_journal (seq INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, payload BLOB NOT NULL)')
    for table,columns in TABLES.items():
        for operation in ('INSERT','UPDATE','DELETE'):
            refs=['OLD','NEW'] if operation=='UPDATE' else ['NEW' if operation=='INSERT' else 'OLD']
            args=','.join(f'{ref}.{column}' for ref in refs for column in columns)
            connection.execute(f'''CREATE TRIGGER journal_{table}_{operation} AFTER {operation} ON {table}
                BEGIN SELECT edh_capture('{table}','{operation}',{args}); END''')
    append(connection,binding,rules_commit,[['set',[],state]],[])


def capture(connection):
    rows=[]
    def record(table,operation,*values):
        rows.append([table,operation,row_value(values)])
        return 0
    connection.create_function('edh_capture',-1,record)
    return rows


def verify(connection,binding):
    """Reconstruct host state and receipt tables, then compare live projections.

    This offline/open-time audit has no model or kernel execution. Normal host
    transactions append only changed state and affected rows.
    """
    state=None;tables={name:{} for name in TABLES};previous=digest(binding);count=0;last_rules=0
    commits=dict(connection.execute('SELECT seq,sha FROM commands'))
    commits[0]=connection.execute('SELECT sha FROM header WHERE id=1').fetchone()[0]
    try:
        for sequence,sha,payload in connection.execute('SELECT seq,sha256,payload FROM host_journal ORDER BY seq'):
            value=json.loads(zlib.decompress(payload))
            if (sequence!=count or value['sequence']!=sequence or value['previous']!=previous
                    or value['schema']!=1 or digest(value)!=sha):
                raise RulesViolation('Host journal chain mismatch')
            commit=value['rules_commit'];rules_sequence=commit['sequence']
            if rules_sequence<last_rules or commits.get(rules_sequence)!=commit['sha256']:
                raise RulesViolation('Host journal refers to a different rules prefix')
            last_rules=rules_sequence
            state=apply(state,value['state'])
            for table,operation,values in value['rows']:
                size=len(TABLES[table]);rows=tables[table];key=values[0]
                if operation=='INSERT':
                    if key in rows or len(values)!=size:raise RulesViolation('Invalid host journal insertion')
                    rows[key]=values
                else:
                    if rows.get(key)!=values[:size]:raise RulesViolation('Host journal row precondition changed')
                    del rows[key]
                    if operation=='UPDATE':
                        new=values[size:]
                        if len(new)!=size or new[0] in rows:raise RulesViolation('Invalid host journal update')
                        rows[new[0]]=new
                    elif operation!='DELETE':raise RulesViolation('Invalid host journal operation')
            previous=sha;count+=1
        if not count:raise RulesViolation('Missing host journal')
        actual=json.loads(connection.execute('SELECT value FROM host_state WHERE id=1').fetchone()[0])
        if encoded(state)!=encoded(actual):raise RulesViolation('Host state differs from replayed journal')
        for table,columns in TABLES.items():
            actual={row[0]:row_value(row) for row in connection.execute(f'SELECT {",".join(columns)} FROM {table}')}
            if actual!=tables[table]:raise RulesViolation('Host receipt table differs from replayed journal: '+table)
        return {'sequence':count-1,'sha256':previous}
    except RulesViolation:raise
    except (KeyError,TypeError,ValueError,IndexError,zlib.error) as exc:
        raise RulesViolation('Invalid host journal encoding') from exc
