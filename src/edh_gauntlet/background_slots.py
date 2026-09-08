"""Bounded independent inference lanes; immutable jobs remain seat/role scoped."""
from .runtime_store import read,locked


def concurrent(state):return state.get('role_slots')==1


def reservations(state):
    return list(state.get('active_by_role',{}).values()) if concurrent(state) else ([state['active']] if state.get('active') else [])


def reservation(state,batch_id):
    return next((job for job in reservations(state) if job['batch_id']==batch_id),None)


def available(state,pending):
    active=reservations(state)
    if not concurrent(state):return [] if active else pending
    occupied={job['role'] for job in active}
    return [job for job in pending if job.get('role') not in occupied]


def assign(state,job):
    if concurrent(state):
        if job['role'] in state.setdefault('active_by_role',{}):raise SystemExit('Background role slot is already occupied.')
        state['active_by_role'][job['role']]=job
    else:state['active']=job


def release(state,job):
    if concurrent(state):state['active_by_role'].pop(job['role'])
    else:state['active']=None


def enable(root,game):
    """Explicit transport update at a stopped frontier, or on a fresh host."""
    from . import planner_runtime as runtime,agent_architecture
    from pathlib import Path
    root=Path(root);directory=runtime.directory_for(root,game)
    with locked(root),locked(directory,'planning'):
        if not agent_architecture.enabled(root,game):raise SystemExit('Independent role slots require split architecture.')
        if runtime._rows(root,game) and not (root/'HOST_PAUSED.json').exists():
            raise SystemExit('Pause the host before explicitly enabling independent role slots.')
        state=runtime._state(directory)
        if reservations(state):raise SystemExit('Stop all background reservations before changing admission.')
        state.update(role_slots=1,active=None,active_by_role={})
        runtime._save(directory,state)
        return {'role_slots':1,'background_concurrency':3,'decision_inference_slots':1}
