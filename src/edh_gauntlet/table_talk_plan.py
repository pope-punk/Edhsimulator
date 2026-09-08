"""One optional private message proposal; only the pilot can choose to post it."""
from copy import deepcopy
import unicodedata

SCHEMA = {'type':'object','properties':{
    'message_text':{'type':'string','minLength':1,'maxLength':300},
    'message_address':{'type':'string','enum':['generic','all','pilot']},
    'message_recipient':{'type':'string','minLength':1,'maxLength':200},
    'rationale':{'type':'string','minLength':1,'maxLength':160}},
    'required':['message_text','message_address','rationale'],'additionalProperties':False}
GUIDANCE = ('Optional table_talk: one draft with message_text (300 characters), '
    'message_address (generic/all/pilot), message_recipient only for pilot, and rationale '
    '(160 characters: purpose/condition). Use own-seat information and neutral wording; '
    'the pilot applies its established messaging personality. '
    'Do not disclose private strategy by accident. Suggest talk only when useful; '
    'addressed talk may prompt opponent responses. The pilot chooses whether/when to '
    'post at an existing legal opportunity. Omit to clear the previous draft; never '
    'repeat it in short-term prose or symbolic actions.')


def normalize(value, actor, board):
    if not isinstance(value, dict) or set(value)-set(SCHEMA['properties']):
        raise ValueError('table_talk must be one object with only the documented message fields and rationale.')
    if not set(SCHEMA['required']) <= set(value):
        raise ValueError('table_talk requires message_text, message_address and rationale.')
    result = deepcopy(value)
    from .referee import normalize_messageboard_text
    if not isinstance(result['message_text'],str):
        raise ValueError('table_talk.message_text must be a string.')
    result['message_text']=normalize_messageboard_text(result['message_text'])
    for key, limit in [('rationale',160),('message_recipient',200)]:
        if key not in result:continue
        text = result[key]
        if not isinstance(text, str):raise ValueError('table_talk.' + key + ' must be a string.')
        text = unicodedata.normalize('NFC', text.replace('\r\n','\n').replace('\r','\n')).strip()
        if not text or len(text)>limit:
            raise ValueError(f'table_talk.{key} must be 1–{limit} characters.')
        result[key] = text
    address = result['message_address']
    if address not in ('generic','all','pilot'):
        raise ValueError('table_talk.message_address must be generic, all or pilot.')
    if address == 'pilot':
        recipient = result.get('message_recipient')
        if recipient == actor or recipient not in board.get('players', {}):
            raise ValueError('table_talk.message_recipient must name an opponent in the frozen board.')
    elif 'message_recipient' in result:
        raise ValueError('table_talk.message_recipient is only allowed with message_address pilot.')
    return result


def for_decision(plan, request, events=()):
    """Present a draft only at a current legal posting opportunity; never execute."""
    draft = plan.get('table_talk')
    if request.get('actor') != plan.get('actor'):return None
    meta = request.get('messageboard') or {}
    if not draft or request.get('kind') != 'main_action' or not meta.get('available'):
        return None
    if meta.get('opening_salutation_required') and draft['message_address'] != 'generic':
        return None
    if draft['message_address'] == 'pilot' and draft['message_recipient'] not in meta.get('valid_recipients', []):
        return None
    messages = (request.get('public_state') or {}).get('public_messageboard', [])
    if isinstance(messages,dict):messages=messages.get('recent_messages',[])
    if any(row.get('author') == plan['actor'] and row.get('text') == draft['message_text'] for row in messages):
        return None
    # Reuse already loaded since-plan events; no new adoption field or queue.
    # The pilot's own post handles the suggestion even if edited/replaced. An
    # unrelated prompted reply does not consume this proposed root message.
    for row in events:
        if row.get('type')!='messageboard_message' or row.get('actor')!=plan['actor']:continue
        if (row.get('detail')==draft['message_text'] or row.get('message_kind')=='post'
                or ('reply_to' in row and row['reply_to'] is None)):
            return None
    return deepcopy(draft)
