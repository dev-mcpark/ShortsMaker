"""Prepare one resumable, locally retained narration set before video editing."""

import argparse
import asyncio
import json
from pathlib import Path

from shorts_maker.services.narration_preparation import VOICES, prepare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--voice", choices=VOICES, required=True)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--usd-per-million-characters", type=float, required=True,
                        help="Check the current official model price before running")
    parser.add_argument("--plan", action="store_true", help="Inspect missing scenes and reserve; make no API calls")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(prepare(
        args.script, args.output_dir, args.voice, args.max_cost_usd,
        args.usd_per_million_characters, args.plan,
    )), ensure_ascii=False))


if __name__ == "__main__":
    main()
