"""
Thread-safe state synchronization for async coroutines.

Provides the :class:`SyncContext` async context manager for safely mutating
GUI state from background async threads.
"""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any
    from .guistate import GUIState


def shallow_merge(target: Any, source: Any) -> None:
    """Replace top-level attributes from source onto target.
    
    Skips private attributes (those starting with underscore).
    """
    for key, value in source.__dict__.items():
        if not key.startswith('_'):
            setattr(target, key, value)


def deep_merge(target: Any, source: Any) -> None:
    """Recursively merge source attributes into target.
    
    For nested objects with __dict__ (custom classes), recurse into them.
    For builtins (str, int, list, dict, etc.), replace directly.
    Skips private attributes (those starting with underscore).
    """
    for key, value in source.__dict__.items():
        if key.startswith('_'):
            continue
        if not hasattr(target, key):
            setattr(target, key, value)
            continue
        target_val = getattr(target, key)
        # Recurse for objects with __dict__ (custom classes)
        if (hasattr(value, '__dict__') 
            and hasattr(target_val, '__dict__')
            and not isinstance(value, (str, bytes, int, float, bool, list, dict, tuple, set, frozenset))):
            deep_merge(target_val, value)
        else:
            setattr(target, key, value)


class SyncContext:
    """Async context manager for thread-safe state mutations.
    
    Used to safely mutate GUIState from async coroutines running on
    background threads. Creates a deep copy of the state, allows mutations
    on the copy, then merges changes back on the main thread.
    
    Usage::
    
        async def my_coroutine(gui):
            result = await some_async_api()
            async with gui.state.sync() as state:
                state.data = result
    
    Parameters
    ----------
    state : GUIState
        The state object to synchronize with.
    deep : bool, default False
        If True, perform recursive merge of nested objects.
        If False, only merge top-level attributes.
    """
    
    def __init__(self, state: GUIState, deep: bool = False) -> None:
        self._state = state
        self._deep = deep
        self._snapshot: GUIState | None = None
        self._done: asyncio.Event | None = None
    
    async def __aenter__(self) -> GUIState:
        self._snapshot = copy.deepcopy(self._state)
        self._done = asyncio.Event()
        return self._snapshot
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            # Exception occurred, don't merge
            return
        
        snapshot = self._snapshot
        done = self._done
        deep = self._deep
        state = self._state
        
        def merge() -> None:
            if deep:
                deep_merge(state, snapshot)
            else:
                shallow_merge(state, snapshot)
            done.set()
        
        state._sync_queue.put(merge)
        await done.wait()
