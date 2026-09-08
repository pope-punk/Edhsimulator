"""Shared asset location for a source checkout or installed distribution."""
import os
from pathlib import Path
import sys


def asset_root():
    configured=os.environ.get('EDH_PROJECT_ROOT')
    candidates=([Path(configured)] if configured else [Path(__file__).resolve().parents[2],
                Path(sys.prefix)/'share/edh-gauntlet',Path(__file__).resolve().parents[1]/'share/edh-gauntlet'])
    for root in candidates:
        if (root/'data/catalog/cards.json').is_file() and (root/'docs/HOST_AGENT_POLICY.md').is_file():
            return root.resolve()
    raise RuntimeError('EDH data and policy assets are missing. Install the complete distribution or set EDH_PROJECT_ROOT to the project checkout.')


PROJECT_ROOT=asset_root()
