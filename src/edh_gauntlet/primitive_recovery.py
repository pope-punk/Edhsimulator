"""Verify stopped Linux process identities without killing or replaying anything."""
from pathlib import Path
from .rules_state import RulesViolation
from .runtime_store import read,write


def process_facts(pid,proc=Path('/proc')):
    # The command field can contain spaces and parentheses.
    fields=(proc/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
    return {'state':fields[0],'session':int(fields[3]),'start_ticks':int(fields[19])}


def identity(pid,proc=Path('/proc')):
    if type(pid) is not int or pid<1:return None
    try:
        boot=(proc/'sys/kernel/random/boot_id').read_text().strip()
        facts=process_facts(pid,proc)
        return {'pid':pid,'boot_id':boot,'start_ticks':facts['start_ticks']}
    except (OSError,ValueError,IndexError):return None


def verify_exited(owned,*,session=None,proc=Path('/proc')):
    if (type(owned) is not dict or set(owned)!={'pid','boot_id','start_ticks'}
            or type(owned['pid']) is not int or owned['pid']<1
            or type(owned['start_ticks']) is not int or owned['start_ticks']<0
            or type(owned['boot_id']) is not str or not owned['boot_id']):
        raise RulesViolation('No verifiable owned process identity; automatic crash fencing is unavailable')
    try:boot=(proc/'sys/kernel/random/boot_id').read_text().strip()
    except OSError:raise RulesViolation('Linux process evidence is unavailable') from None
    if boot!=owned['boot_id']:return
    try:current=process_facts(owned['pid'],proc)
    except FileNotFoundError:current=None
    except (OSError,ValueError,IndexError):raise RulesViolation('Cannot verify the owned process state') from None
    if current and current['start_ticks']==owned['start_ticks'] and current['state'] not in {'Z','X'}:
        raise RulesViolation('The owned process is still running')
    if session is not None:
        if session!=owned['pid']:raise RulesViolation('Transport was not launched in its own session')
        # A CLI wrapper exiting is insufficient: its inference child may survive.
        try:
            for entry in proc.iterdir():
                if not entry.name.isdecimal():continue
                try:child=process_facts(int(entry.name),proc)
                except FileNotFoundError:continue
                if child['session']==session and child['state'] not in {'Z','X'}:
                    raise RulesViolation('An owned transport session process is still running')
        except RulesViolation:raise
        except (OSError,ValueError,IndexError):raise RulesViolation('Cannot verify the complete transport session') from None


def fence_crash(campaign,expected):
    """Caller holds host-driver lock. Retain pending inputs and logical seats."""
    path=campaign.root/'host_runtime/process.json';process=read(path,{})
    state=campaign.state()
    if (process.get('binding')!=campaign.binding or
            process.get('generation')!=state['transport_generation']):
        raise RulesViolation('Crash evidence does not match this transport generation')
    if campaign.store.committed_head()!=expected:raise RulesViolation('Accepted prefix changed')
    if not process.get('active') and process.get('contexts_unloaded'):
        if process.get('commit')!=expected:raise RulesViolation('Stopped prefix changed')
        return
    verify_exited(process.get('host_identity'))
    if process.get('transport_session') is None:
        raise RulesViolation('No isolated transport session evidence')
    verify_exited(process.get('transport_identity'),session=process['transport_session'])
    receipt={'generation':state['transport_generation'],'commit':expected,
             'host_identity':process['host_identity'],'transport_identity':process['transport_identity']}
    with campaign.transaction() as state:
        if state.get('crash_fence')!=receipt:
            for actor in state['actors']:campaign.record(actor,'crash_fence',receipt)
            state['crash_fence']=receipt
        if not state['paused'] and not state['terminal']:
            state['paused']={'reason':'host_stopped','commit':expected}
    # A failed write can safely retry the same receipt. No recovery occurs here.
    write(path,{**process,'active':False,'contexts_unloaded':True,'commit':expected,'crash_fenced':True})
