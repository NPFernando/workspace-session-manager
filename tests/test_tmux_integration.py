from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from wf_session_manager.tmux import TmuxBackend


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("WF_RUN_TMUX_INTEGRATION") != "1",
    reason="set WF_RUN_TMUX_INTEGRATION=1 to create one disposable tmux session",
)
def test_real_tmux_create_capture_and_guarded_delete(tmp_path: Path) -> None:
    backend = TmuxBackend()
    name = f"wf-it-{uuid4().hex[:12]}"
    assert not backend.session_exists(name)
    created = backend.create_session(
        name=name,
        cwd=tmp_path,
        shell_command=("/bin/bash", "--noprofile", "--norc"),
        agent_command=None,
    )
    try:
        assert created.name == name
        assert backend.get_option(name, "@wf_owner") == "wf-session-manager"
        assert backend.get_session(name).session_id == created.session_id
        backend.capture_pane(name, 10)
    finally:
        live = next((item for item in backend.list_sessions() if item.name == name), None)
        if (
            live is not None
            and live.session_id == created.session_id
            and backend.get_option(name, "@wf_owner") == "wf-session-manager"
        ):
            backend.kill_session(name, expected_id=created.session_id)
    assert not backend.session_exists(name)
