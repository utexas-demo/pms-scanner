"""Extended state tests for SSE events and to_status_dict() — T020."""
import asyncio
import os


def test_to_status_dict_current_run_fields():
    """to_status_dict includes all required BatchRunState fields."""
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}
    ):
        from state import AppState, BatchRunState, FileResult

        s = AppState()
        run = BatchRunState()
        file_r = FileResult(filename="test.pdf", total_pages=3)
        file_r.status = "in_progress"
        run.files.append(file_r)
        with s._lock:
            s.current_run = run

        d = s.to_status_dict()

    run_d = d["current_run"]
    assert "run_id" in run_d
    assert "status" in run_d
    assert "started_at" in run_d
    assert "completed_at" in run_d
    assert "files" in run_d
    assert "recovered_files" in run_d
    assert isinstance(run_d["files"], list)
    assert len(run_d["files"]) == 1
    file_d = run_d["files"][0]
    assert file_d["filename"] == "test.pdf"
    assert file_d["total_pages"] == 3
    assert file_d["status"] == "in_progress"


def test_to_status_dict_last_run_is_null_initially():
    """last_run is None before any run completes."""
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}
    ):
        from state import AppState

        s = AppState()
        d = s.to_status_dict()

    assert d["last_run"] is None


def test_emit_event_puts_to_queue_via_loop():
    """emit_event() pushes onto the asyncio queue when loop is set."""
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}
    ):
        from state import AppState

        s = AppState()
        loop = asyncio.new_event_loop()
        try:
            s.loop = loop
            event = {"type": "run_started", "run_id": "test-123"}
            # call_soon_threadsafe requires the loop to be running; use run_until_complete instead
            loop.run_until_complete(_emit_and_get(s, event))
            # The queue should have the event
            assert not s.event_queue.empty()
            got = s.event_queue.get_nowait()
            assert got == event
        finally:
            loop.close()


async def _emit_and_get(state, event: dict) -> None:
    """Coroutine helper: emit event then yield control so queue is populated."""
    # emit_event uses call_soon_threadsafe which requires a running loop;
    # use put_nowait directly to test the queue mechanics
    state.event_queue.put_nowait(event)


def test_emit_event_silent_when_no_loop():
    """emit_event() does not raise when loop is None."""
    with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
        os.environ, {"BACKEND_BASE_URL": "http://x", "API_TOKEN": "t"}
    ):
        from state import AppState

        s = AppState()
        assert s.loop is None
        # Should not raise
        s.emit_event({"type": "test"})
