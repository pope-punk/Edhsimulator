"""Initialization-bound learning policy; never represents an unperformed review."""
from .runtime_store import read, write

SKIPPED='skipped_by_configuration'


def enabled(config):
    value=config.get('learning_enabled',True)
    if type(value) is not bool:raise ValueError('learning_enabled must be boolean.')
    return value


def skip(directory):
    config=read(directory/'game_config.json')
    if enabled(config):raise ValueError('Cannot skip learning in a learning-enabled game.')
    seal=read(directory/'terminal_result.json')
    value={'state':SKIPPED,'learning_enabled':False,'game':config['game'],
           'terminal_fingerprint':seal['terminal_fingerprint'],
           'reason':'Learning disabled when this run was initialized. No review or strategy update was performed.'}
    path=directory/'postgame_learning'/'skipped.json'
    previous=read(path)
    if previous and previous!=value:raise ValueError('Learning skip receipt differs from the terminal seal.')
    if not previous:write(path,value)
    return {**value,'audit_path':f'game_{config["game"]:02d}/postgame_learning/skipped.json'}
