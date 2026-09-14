"""Explicit one-shot paper observation; no scheduler or orders."""
import argparse
import asyncio
from pathlib import Path

from alphaforge.execution.spot_paper import PaperCredentials
from alphaforge.validation.portfolio_observation import ObservationReader, collect, save_capture


async def run(args):
    reader = ObservationReader(PaperCredentials.from_file(args.credentials))
    try:
        packet = await collect(reader, expected_binding=args.account_binding,
                               after=args.after, until=args.until)
        save_capture(args.output, packet)
        print(packet['status'])
        print('Receipts:', len(packet['receipts']))
        print('Capture incomplete:', 'INCOMPLETE_OR_INVALID_CAPTURE' in packet['blocking_reasons'])
    finally:
        await reader.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--account-binding', required=True)
    parser.add_argument('--after', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
