"""Bounded independent inference lanes; immutable jobs remain seat/role scoped."""
from .runtime_store import read,locked


def concurrent(state):return state.get('role_slots') in {1,2}


def seat_roles(state):return state.get('role_slots')==2


def lane_key(state,job):
    from .agent_architecture import registration_key
    return registration_key(job['actor'],job['role']) if seat_roles(state) else job.get('role','planner')


def reservations(state):
    return list(state.get('active_by_role',{}).values()) if concurrent(state) else ([state['active']] if state.get('active') else [])


def reservation(state,batch_id):
    return next((job for job in reservations(state) if job['batch_id']==batch_id),None)


def available(state,pending):
    active=reservations(state)
    if not concurrent(state):return [] if active else pending
    occupied={lane_key(state,job) for job in active}
    return [job for job in pending if lane_key(state,job) not in occupied]


def assign(state,job):
    if concurrent(state):
        key=lane_key(state,job)
        if key in state.setdefault('active_by_role',{}):raise SystemExit('Background inference lane is already occupied.')
        state['active_by_role'][key]=job
    else:state['active']=job


def release(state,job):
    if concurrent(state):state['active_by_role'].pop(lane_key(state,job))
    else:state['active']=None


def enable(root,game,*,role_slots=2):
    """Explicit transport update at a stopped frontier, or on a fresh host."""
    from . import planner_runtime as runtime,agent_architecture
    from pathlib import Path
    if role_slots not in {1,2}:raise ValueError('Unsupported inference lane version.')
    root=Path(root);directory=runtime.directory_for(root,game)
    with locked(root),locked(directory,'planning'):
        if not agent_architecture.enabled(root,game):raise SystemExit('Independent role slots require split architecture.')
        if runtime._rows(root,game) and not (root/'HOST_PAUSED.json').exists():
            raise SystemExit('Pause the host before explicitly enabling independent role slots.')
        state=runtime._state(directory)
        if reservations(state):raise SystemExit('Stop all background reservations before changing admission.')
        state.update(role_slots=role_slots,active=None,active_by_role={})
        runtime._save(directory,state)
        return {'role_slots':role_slots,'background_concurrency':12 if role_slots==2 else 3,
                'decision_inference_slots':4 if role_slots==2 else 1}
