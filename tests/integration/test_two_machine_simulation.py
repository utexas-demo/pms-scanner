"""Two-machine fleet simulation — T043 (US4, SC-009/SC-010/SC-011).

Two machine instances (macmini, nuc) share the same env watch tree and
poll concurrently. Atomic-rename claims (FR-017) must guarantee every
file is processed exactly once across the fleet, each machine claims
only into its own in-progress/<self>/ subfolder, and no file ever
appears in two machines' subfolders at once.
"""
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
from batch import BatchRunner
from config import Environment
from machine import MachineIdentity
from pydantic import SecretStr
from state import BatchRunState

N_FILES = 10


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(str(path))
    doc.close()


def _env(tmp_path: Path) -> Environment:
    watch = tmp_path / "shared-prod"
    watch.mkdir()
    return Environment(
        name="production",
        watch_dir=watch,
        backend_base_url="https://adg.mpsinc.io",
        api_token=SecretStr("tok"),
        schedule_offset_seconds=0,
    )


def _ok_post(*a, **kw):
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = {
        "batch_id": "b",
        "images": [{"original_file_name": "f"}],
        "rejected": [],
    }
    return r


def test_two_machine_exactly_once_no_cross_writes(tmp_path: Path) -> None:
    env = _env(tmp_path)
    for i in range(N_FILES):
        _make_pdf(env.watch_dir / f"scan_{i:02d}.pdf")

    macmini = MachineIdentity("macmini")
    nuc = MachineIdentity("nuc")
    runners = {
        "macmini": BatchRunner(
            env, macmini, BatchRunState(macmini, [env.name]), settle_seconds=0
        ),
        "nuc": BatchRunner(
            env, nuc, BatchRunState(nuc, [env.name]), settle_seconds=0
        ),
    }

    with patch("uploader.requests.post", side_effect=_ok_post):
        threads = [
            threading.Thread(target=r.run_once) for r in runners.values()
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    processed = sorted(p.name for p in env.processed_dir.iterdir())
    # (a) exactly N files processed, (b) zero duplicates.
    assert len(processed) == N_FILES
    assert len(set(processed)) == N_FILES
    assert processed == sorted(f"scan_{i:02d}.pdf" for i in range(N_FILES))

    # (c) each machine's own in-progress subfolder drained post-run.
    assert list(env.in_progress_dir(macmini).iterdir()) == []
    assert list(env.in_progress_dir(nuc).iterdir()) == []

    # (d) nothing left in the watch dir; no file in both subfolders at once.
    assert [p for p in env.watch_dir.iterdir() if p.is_file()] == []


def test_recovery_is_machine_scoped_after_simulated_crash(
    tmp_path: Path,
) -> None:
    """nuc restart recovers only nuc's stranded files (SC-011)."""
    env = _env(tmp_path)
    macmini = MachineIdentity("macmini")
    nuc = MachineIdentity("nuc")
    BatchRunner(env, macmini, BatchRunState(macmini, [env.name]))
    nuc_runner = BatchRunner(env, nuc, BatchRunState(nuc, [env.name]))

    # macmini is "live" with in-flight files; nuc crashed mid-run.
    (env.in_progress_dir(macmini) / "live_mac.pdf").write_bytes(b"mac")
    (env.in_progress_dir(nuc) / "stuck_nuc.pdf").write_bytes(b"nuc")
    mac_snapshot = {
        p.name: p.read_bytes()
        for p in env.in_progress_dir(macmini).iterdir()
    }

    recovered = nuc_runner.recover_stranded()

    assert recovered == ["stuck_nuc.pdf"]
    assert (env.watch_dir / "stuck_nuc.pdf").is_file()
    # macmini's live subfolder is byte-for-byte untouched.
    assert {
        p.name: p.read_bytes()
        for p in env.in_progress_dir(macmini).iterdir()
    } == mac_snapshot
