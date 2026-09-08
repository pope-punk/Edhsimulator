"""Bounded, metadata-only errors and narrowly eligible capacity retries."""
import hashlib

def error_code(error):
    info=error.get('codexErrorInfo',error.get('codex_error_info'))
    if isinstance(info,dict):info=next(iter(info),'unknown')
    code=str(info or 'unknown')
    if code.lower().replace('_','')=='serveroverloaded':return 'server_overloaded'
    return code[:80]

def metadata(method,params):
    error=params.get('error') or (params.get('turn') or {}).get('error') or {}
    if not isinstance(error,dict):error={}
    # Arbitrary backend messages can contain request data. Keep a fingerprint;
    # the recognized category supplies an operator-readable explanation.
    return {'method':method,'thread_id':params.get('threadId'),
            'turn_id':params.get('turnId') or (params.get('turn') or {}).get('id'),
            'code':error_code(error),
            'message_sha256':hashlib.sha256(str(error.get('message','')).encode()).hexdigest(),
            'will_retry':params.get('willRetry') is True}

def validation_key(message):
    if message.startswith('action_sequence[') and '.scheduler:' in message:return 'sequence_scheduler'
    for prefix in ('Invalid answer fields:','choice must','Unknown PASS ON'):
        if message.startswith(prefix):return prefix
    return 'other'
