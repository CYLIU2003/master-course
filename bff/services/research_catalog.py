from __future__ import annotations

from typing import Any, Dict, List

from src.research_dataset_loader import (
    DEFAULT_DATASET_ID,
    build_dataset_bootstrap,
    get_dataset_status,
    list_dataset_statuses,
)


def default_dataset_id() -> str:
    return DEFAULT_DATASET_ID


def list_datasets() -> List[Dict[str, Any]]:
    return list_dataset_statuses()


def get_default_dataset_status() -> Dict[str, Any]:
    return get_dataset_status(DEFAULT_DATASET_ID)


def get_dataset(dataset_id: str) -> Dict[str, Any]:
    return get_dataset_status(dataset_id)


def bootstrap_scenario(
    *,
    scenario_id: str,
    dataset_id: str = DEFAULT_DATASET_ID,
    random_seed: int = 42,
) -> Dict[str, Any]:
    return build_dataset_bootstrap(
        dataset_id,
        scenario_id=scenario_id,
        random_seed=random_seed,
    )
