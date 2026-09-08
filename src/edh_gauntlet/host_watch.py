"""Read-only lifecycle classification for a local, non-inference watcher."""
from pathlib import Path
from .runtime_store import read, write

def snapshot(root, *, process_alive, game):
    root=Path(root);action=read(root/'NEXT_ACTION.json',{}).get('next_action',{})
    pause=read(root/'HOST_PAUSED.json',{})
    if action.get('game')!=game:
        kind='lifecycle_changed'
    elif pause:
        kind='paused'
    elif action.get('kind')!='dispatch_pilot':
        kind='lifecycle_ready'
    elif not process_alive:
        kind='host_stopped'
    else:
        kind='running'
    return {'state':kind,'game':game,'next_action':action.get('kind'),
            'decision_id':action.get('decision_id'),'pause_reason':pause.get('reason'),
            'requires_attention':kind!='running','inference_calls':0}

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True)
    parser.add_argument('--game',type=int,required=True)
    args=parser.parse_args()
    write(args.cohort/'HOST_ATTENTION.json',snapshot(args.cohort,process_alive=False,game=args.game))

if __name__=='__main__':main()
