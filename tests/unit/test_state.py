"""Unit tests for scanner/state.py — T006."""
import threading
from datetime import datetime

from state import AppState, BatchRunState, FileResult, PageResult


def test_app_state_initial_values():
    """AppState initialises with current_run=None and last_run=None."""
    s = AppState()
    assert s.current_run is None
    assert s.last_run is None


def test_app_state_has_lock():
    """AppState._lock is a threading.Lock."""
    s = AppState()
    assert isinstance(s._lock, type(threading.Lock()))


def test_page_result_fields():
    """PageResult stores all required fields."""
    p = PageResult(page_num=1, total_pages=5, rotation_applied=90, upload_success=True)
    assert p.page_num == 1
    assert p.total_pages == 5
    assert p.rotation_applied == 90
    assert p.orientation_uncertain is False
    assert p.upload_success is True
    assert p.error is None


def test_file_result_defaults():
    """FileResult starts with status=pending and empty pages list."""
    f = FileResult(filename="test.pdf", total_pages=3)
    assert f.status == "pending"
    assert f.pages == []
    assert isinstance(f.started_at, datetime)
    assert f.completed_at is None


def test_batch_run_state_has_run_id():
    """BatchRunState auto-generates a run_id UUID string."""
    r = BatchRunState()
    assert isinstance(r.run_id, str)
    assert len(r.run_id) == 36  # UUID4 format


def test_batch_run_state_defaults():
    """BatchRunState starts with status=running and empty lists."""
    r = BatchRunState()
    assert r.status == "running"
    assert r.files == []
    assert r.recovered_files == []


def test_app_state_lock_prevents_concurrent_mutation():
    """Acquiring _lock blocks concurrent writes."""
    s = AppState()
    results: list[int] = []

    def writer(val: int) -> None:
        with s._lock:
            results.append(val)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 50
    assert sorted(results) == list(range(50))


def test_to_status_dict_structure():
    """to_status_dict returns dict with current_run and last_run keys."""
    s = AppState()
    d = s.to_status_dict()
    assert "current_run" in d
    assert "last_run" in d
    assert d["current_run"] is None
    assert d["last_run"] is None


def test_to_status_dict_with_run():
    """to_status_dict serialises a BatchRunState correctly."""
    s = AppState()
    run = BatchRunState()
    with s._lock:
        s.current_run = run
    d = s.to_status_dict()
    assert d["current_run"] is not None
    assert d["current_run"]["run_id"] == run.run_id
    assert d["current_run"]["status"] == "running"
    assert isinstance(d["current_run"]["files"], list)
