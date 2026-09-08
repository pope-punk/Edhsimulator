"""Private seat personality from the game's immutable source snapshot."""
def own(root,game,actor):
    from . import campaign
    snapshot=campaign._load_game_messaging_personality_snapshot(campaign.game_dir(root,game))
    if not snapshot:return None
    return {'actor':actor,'source_file':campaign.PILOT_MESSAGING_PERSONALITY_FILES[actor],
            'text':snapshot['pilots'][actor]['text']}
