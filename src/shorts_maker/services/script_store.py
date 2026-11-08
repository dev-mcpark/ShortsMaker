"""Store a new script copy without granting any review or spending approval."""

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from shorts_maker.planner.models import ShortsScript


def save_script_copy(script: ShortsScript, directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    title = re.sub(r'[^\w\s-]', '', script.title).strip().replace(' ', '_')[:30]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=directory,
                prefix=f'script_{datetime.now():%Y%m%d_%H%M%S}_{title}_', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(script.model_dump_json(indent=2))
            file.flush()
            os.fsync(file.fileno())
        destination = temporary.with_suffix('.json')
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
