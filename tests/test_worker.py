"""Worker / queue wiring tests.

These don't need Redis or Postgres — they lock in the contract that indexing is
enqueued to the Arq worker (not run inline in the web request) and that the
worker entrypoint is shaped the way `arq app.worker.WorkerSettings` expects.
"""
import inspect

from app.queue import BULK_INDEX_TASK
from app.services.index_service import process_bulk_index, run_bulk_index_job
from app.worker import WorkerSettings, run_bulk_index, sweep_stale_jobs


def test_bulk_index_no_longer_runs_inline():
    # process_bulk_index must NOT accept a FastAPI BackgroundTasks anymore —
    # the work is handed to the worker via Redis.
    params = inspect.signature(process_bulk_index).parameters
    assert "background_tasks" not in params
    assert set(params) == {"pages", "tenant_id", "db"}


def test_worker_task_name_matches_registration():
    # The enqueue task name (used by the web service) must match a function the
    # worker actually registers, or jobs would queue and never run.
    registered = {fn.__name__ for fn in WorkerSettings.functions}
    assert BULK_INDEX_TASK in registered
    assert run_bulk_index.__name__ == BULK_INDEX_TASK


def test_worker_settings_shape():
    assert WorkerSettings.on_startup is sweep_stale_jobs
    assert WorkerSettings.max_jobs >= 1
    assert WorkerSettings.job_timeout > 0
    assert WorkerSettings.max_tries >= 1
    # redis_settings must be a parsed RedisSettings instance, not a raw URL.
    from arq.connections import RedisSettings

    assert isinstance(WorkerSettings.redis_settings, RedisSettings)


def test_core_job_function_is_importable_and_async():
    # The worker imports this directly; it must exist and be a coroutine fn.
    assert inspect.iscoroutinefunction(run_bulk_index_job)
    assert inspect.iscoroutinefunction(run_bulk_index)
