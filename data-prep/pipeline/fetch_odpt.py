from __future__ import annotations

import argparse
import logging


def fetch_odpt(dataset_id: str, **_: object) -> None:
    logging.getLogger(__name__).info(
        "fetch_odpt noop for dataset %s (cached/offline mode)",
        dataset_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    fetch_odpt(args.dataset)


if __name__ == "__main__":
    main()
