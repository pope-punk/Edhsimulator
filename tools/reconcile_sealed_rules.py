"""Explicit operator rules-draw correction for a historical, learning-disabled game.

Preserves the original directory and seals before replacing its canonical branch.
Never supplies pilot choices. A prepared transaction is rolled back on retry.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from edh_gauntlet import campaign,pilot_handoff,pilot_dispatch,planner_runtime,quarantine
from edh_gauntlet.runtime_store import locked,read,write


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate(root,response):
    manifest=campaign.load_manifest(root);number=response['game'];directory=campaign.game_dir(root,number)
    if not read(root/'HOST_PAUSED.json',{}):raise ValueError('Pause the host before rules reconciliation.')
    if not 0<number<int(manifest['active_game']):raise ValueError('Only a historical game is supported.')
    if manifest.get('learning_enabled',True) is not False:raise ValueError('Published learning requires its separate review transaction.')
    config=read(directory/'game_config.json');seal=read(directory/'terminal_result.json')
    if config.get('learning_enabled',True) is not False or campaign._review_applications(directory):
        raise ValueError('Only games without learned evidence can be corrected by this tool.')
    if read(directory/'status.json',{}).get('state')!='complete':raise ValueError('Expected a sealed completed game.')
    if seal['terminal_fingerprint']!=response['original_terminal_fingerprint']:raise ValueError('Original terminal binding changed.')
    if 'terminal-'+fingerprint({k:v for k,v in seal.items() if k!='terminal_fingerprint'})!=seal['terminal_fingerprint']:
        raise ValueError('Invalid terminal fingerprint.')
    if campaign._sha256_file(directory/'decisions.jsonl')!=seal['decisions_sha256']:raise ValueError('Original tape changed.')
    if campaign._sha256_file(directory/'strategy_snapshot.json')!=seal['strategy_snapshot_sha256']:raise ValueError('Original strategy changed.')
    if read(directory/'postgame_learning/skipped.json',{}).get('terminal_fingerprint')!=seal['terminal_fingerprint']:
        raise ValueError('Learning skip binding changed.')
    rows=campaign.read_jsonl(directory/'decisions.jsonl');accepted=response['accepted']
    if type(accepted) is not int or not 0<accepted<len(rows):raise ValueError('A strict, nonempty original prefix is required.')
    issues=quarantine.read_work_items(root,number)['issues']
    if not issues or {i['issue_id'] for i in issues}!=set(response['reviewed_issues']):raise ValueError('Review every tagged issue.')
    quarantine.require_repairs_complete(root,number)
    if response.get('verdict')!='rules_draw' or not response.get('rules_basis','').strip() or not response.get('reason','').strip():
        raise ValueError('An explicit rules-draw verdict and substantive basis are required.')
    if response.get('adjudicator')!='operator_authorized_root':raise ValueError('Explicit operator-authorized adjudication is required.')
    campaign._require_no_prepared_learning_transaction(root,'reconcile sealed rules')
    return manifest,config,seal,rows


def rollback(root,transaction):
    """Restore originals if an interrupted/failed installation has not committed."""
    journal=read(transaction/'transaction.json',{})
    if journal.get('state')!='prepared':return
    directory=campaign.game_dir(root,journal['game']);archive=transaction/'original_game'
    if archive.exists():
        if directory.exists():shutil.rmtree(directory)
        shutil.copytree(archive,directory)
    for name in ('cohort.json','NEXT_ACTION.json'):
        backup=transaction/name
        if backup.exists():shutil.copy2(backup,root/name)
    registry=quarantine.registry_path(campaign.DEFAULT_STRATEGY_FILE)
    backup=transaction/'quarantine_registry.json'
    if backup.exists():shutil.copy2(backup,registry)
    write(transaction/'transaction.json',{**journal,'state':'rolled_back'})


def reconcile(root,response,apply=False):
    root=Path(root).resolve();transaction=root/'rules_reconciliations'/fingerprint(response)
    with locked(root,'host-driver',timeout=0),locked(root):
        journal=read(transaction/'transaction.json',{})
        if journal.get('state')=='committed':return read(transaction/'receipt.json')
        rollback(root,transaction)
        manifest,config,seal,rows=validate(root,response);number=config['game'];directory=campaign.game_dir(root,number)
        transaction.mkdir(parents=True,exist_ok=True);write(transaction/'response.json',response)
        prefix=transaction/'prefix.jsonl';campaign.write_jsonl(prefix,rows[:response['accepted']])
        outcome=campaign._run(root,config,prefix,transaction/'unanswered.json',retain_suspended_game=True)
        game=outcome.get('game') or outcome.get('pilot_game')
        if outcome['state']!='need_decision' or game is None or len(game.decisions)!=response['accepted']:
            raise ValueError('Corrected replay did not reproduce the entire proposed prefix.')
        if outcome['request'].get('rebase_existing_decision'):raise ValueError('Proposed prefix contains a displaced decision.')
        evidence={'game':number,'accepted':len(game.decisions),'events':game.seq,
                  'next_decision':outcome['request']['decision_id'],
                  'prefix_sha256':campaign._sha256_file(prefix),
                  'public_corrections':[{'type':e['type'],'card':e.get('card'),'detail':e.get('detail')} for e in game.events
                    if e.get('card') in ('Body Double','Animate Dead') and e['type'] in ('graveyard','sacrifice','dies','ltb')]}
        write(transaction/'replay.json',evidence)
        if not apply:return evidence
        active=int(manifest['active_game']);active_dir=campaign.game_dir(root,active)
        protected={name:campaign._sha256_file(active_dir/name) for name in ('decisions.jsonl','game_config.json','status.json')}
        public=campaign._retained_public_history(root,number,rows[:response['accepted']])
        for name in ('cohort.json','NEXT_ACTION.json'):shutil.copy2(root/name,transaction/name)
        registry=quarantine.registry_path(campaign.DEFAULT_STRATEGY_FILE)
        shutil.copy2(registry,transaction/'quarantine_registry.json')
        archive=transaction/'original_game'
        if archive.exists():shutil.rmtree(archive)
        shutil.copytree(directory,archive)
        write(transaction/'transaction.json',{'state':'prepared','game':number})
        try:
            campaign.write_jsonl(directory/'decisions.jsonl',rows[:response['accepted']])
            for name in ('terminal_result.json','status.json','STATUS.md','request.json'):(directory/name).unlink(missing_ok=True)
            for name in ('checkpoints','postgame_learning','postgame_evidence','postgame_review','pilot_turns','pilot_sessions'):
                if (directory/name).exists():shutil.rmtree(directory/name)
            pilot_handoff.invalidate_sessions(root,number,'operator_rules_draw')
            campaign._rebind_public_history(root,number,rows[:response['accepted']],public)
            pilot_dispatch.invalidate_registry(root,number);planner_runtime.invalidate_contexts(root,number)
            campaign._truncate_gameplans(directory,response['accepted'])
            campaign._truncate_combo_adjudications(directory,{r['decision_id'] for r in rows[:response['accepted']]},response['accepted'])
            review_id='operator-rules-'+fingerprint(response)
            quarantine.complete_critical_review(campaign.DEFAULT_STRATEGY_FILE,root,number,review_id,fingerprint(response))
            game.winner=None;game.win_turn=game.turn_number;game.win_reason=response['reason'];game.pilot_terminal='adjudicated_draw'
            game.log('draw_adjudication',None,None,response['reason'])
            result=game.result();result['rules_reconciliation_id']=fingerprint(response)
            campaign._commit_checkpoint_outcome(root,manifest,config,{'state':'complete','game':game,'result':result})
            # A historical correction cannot steal the current game's route.
            current=campaign.load_manifest(root)
            if current['active_game']!=active:raise ValueError('Historical correction moved the active game.')
            campaign._write_next_action(root,current,read(active_dir/'status.json'))
            for name,digest in protected.items():
                if campaign._sha256_file(active_dir/name)!=digest:raise ValueError('Active game changed during reconciliation.')
            new_seal=read(directory/'terminal_result.json')
            receipt={'schema':1,'game':number,'verdict':'rules_draw','response_sha256':fingerprint(response),
                     'original_terminal_fingerprint':seal['terminal_fingerprint'],
                     'terminal_fingerprint':new_seal['terminal_fingerprint'],
                     'archive':str(archive),'retained':response['accepted'],'discarded':len(rows)-response['accepted'],
                     'active_game_preserved':active,'active_artifacts_sha256':protected,'replay':evidence}
            write(directory/'rules_reconciliation.json',receipt);write(transaction/'receipt.json',receipt)
            write(transaction/'transaction.json',{'state':'committed','game':number})
            return receipt
        except BaseException:
            rollback(root,transaction)
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',type=Path,required=True);parser.add_argument('--response',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Commit the verified, archived correction.')
    args=parser.parse_args();print(json.dumps(reconcile(args.cohort,read(args.response),args.apply),indent=2))
