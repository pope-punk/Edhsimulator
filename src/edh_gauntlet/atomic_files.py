"""Atomic artifact replacement with bounded Windows sharing-conflict retries."""
import os
import time


def replace(source,destination):
    for attempt in range(7):
        try:
            os.replace(source,destination)
            return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in {5,32,33} or attempt==6:raise
            # Antivirus/indexing readers can briefly hold a destination open.
            # Never unlink the accepted artifact or retry a higher-level action.
            time.sleep(.01*2**attempt)
