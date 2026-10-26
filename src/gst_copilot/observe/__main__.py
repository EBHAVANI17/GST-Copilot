"""Command line: python -m gst_copilot.observe [--days 7]"""

import argparse
import asyncio

from gst_copilot.db.session import get_engine, get_sessionmaker
from gst_copilot.observe.report import build_report, render


async def _main(days: float) -> None:
    async with get_sessionmaker()() as session:
        print(render(await build_report(session, days)))
    await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise real usage from ask_logs.")
    parser.add_argument("--days", type=float, default=7.0)
    asyncio.run(_main(parser.parse_args().days))


if __name__ == "__main__":
    main()
