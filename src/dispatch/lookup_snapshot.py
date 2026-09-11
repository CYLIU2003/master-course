"""Bound repeated location queries to one immutable computation snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import TypeVar

from .models import DispatchContext

_Key = TypeVar("_Key")
_Value = TypeVar("_Value")
_MAX_LOOKUP_ENTRIES = 4096


def _remember(
    cache: dict[_Key, _Value], key: _Key, compute: Callable[[], _Value]
) -> _Value:
    if key not in cache:
        if len(cache) >= _MAX_LOOKUP_ENTRIES:
            cache.pop(next(iter(cache)))
        cache[key] = compute()
    return cache[key]


class _LocationLookupSnapshot(DispatchContext):
    def __post_init__(self) -> None:
        super().__post_init__()
        self._resolved_cache: dict[str, tuple[str, ...]] = {}
        self._deadhead_cache: dict[tuple[str, str], int] = {}
        self._turnaround_cache: dict[str, int] = {}
        self._equivalent_cache: dict[tuple[str, str], bool] = {}
        self._known_cache: dict[str, bool] = {}

    def resolve_location_ids(self, raw: str) -> tuple[str, ...]:
        key = str(raw or "").strip()
        return _remember(
            self._resolved_cache,
            key,
            lambda: DispatchContext.resolve_location_ids(self, key),
        )

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        key = (str(from_stop or "").strip(), str(to_stop or "").strip())
        return _remember(
            self._deadhead_cache,
            key,
            lambda: DispatchContext.get_deadhead_min(self, *key),
        )

    def get_base_turnaround_min(self, stop_id: str) -> int:
        key = str(stop_id or "").strip()
        return _remember(
            self._turnaround_cache,
            key,
            lambda: DispatchContext.get_base_turnaround_min(self, key),
        )

    def locations_equivalent(self, left: str, right: str) -> bool:
        key = (str(left or "").strip(), str(right or "").strip())
        return _remember(
            self._equivalent_cache,
            key,
            lambda: DispatchContext.locations_equivalent(self, *key),
        )

    def has_location_data(self, raw: str) -> bool:
        key = str(raw or "").strip()
        return _remember(
            self._known_cache, key, lambda: DispatchContext.has_location_data(self, key)
        )


def snapshot_location_lookups(context: DispatchContext) -> DispatchContext:
    """Copy current rules and aliases, with bounded caches private to this call.

    Callers discard the snapshot after their batch. The original context stays
    mutable, so edits and turnaround sensitivity levels are reflected by the
    next batch. Custom contexts retain their own lookup implementations.
    """
    if type(context) is not DispatchContext:
        return context
    field_names = {item.name for item in fields(DispatchContext)}
    if set(vars(context)) != field_names:
        # Preserve custom instance attributes/methods instead of guessing how
        # to clone them or overriding their behavior with the standard cache.
        return context
    snapshot = _LocationLookupSnapshot(
        **{name: getattr(context, name) for name in field_names}
    )
    # __post_init__ derives aliases from trips. Preserve the exact current map,
    # including explicit removals made since the original context was created.
    snapshot.location_aliases = {
        key: tuple(targets) for key, targets in context.location_aliases.items()
    }
    snapshot.turnaround_rules = dict(context.turnaround_rules)
    snapshot.deadhead_rules = dict(context.deadhead_rules)
    return snapshot
