"""Bind experimental checkpoints to the loaded source bundle and Python runtime."""
import hashlib
import json
from pathlib import Path
import platform
import sys


# Captured at import, not recomputed after a developer edits files underneath a
# running process. Production historical launchers remain a separate gate.
_MODULES = (
    'rules_identity.py', 'rules_modal.py', 'rules_state.py', 'rules_program.py', 'rules_choices.py',
    'rules_kernel.py', 'rules_counters.py', 'rules_actor.py', 'rules_adapter.py', 'rules_durable.py', 'rules_departure.py', 'rules_library.py', 'rules_attachments.py', 'rules_replacements.py',
    'rules_characteristics.py', 'rules_casting.py', 'rules_turns.py', 'rules_combat.py', 'block_declaration.py', 'combat_damage.py',
)
ROOT = Path(__file__).resolve().parent
IMPLEMENTATION_MANIFEST = {
    'python': {'implementation': platform.python_implementation(), 'version': list(sys.version_info[:3])},
    'modules': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in _MODULES},
}
IMPLEMENTATION_ID = hashlib.sha256(json.dumps(IMPLEMENTATION_MANIFEST, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
