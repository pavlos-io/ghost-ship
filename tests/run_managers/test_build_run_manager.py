from unittest.mock import patch

import pytest

from run_managers.interface import RunManagerType, build_run_manager
from run_managers.fake import FakeRunManager
from run_managers.web import WebRunManager


def test_build_fake_returns_fake_instance():
    mgr = build_run_manager(RunManagerType.FAKE)
    assert isinstance(mgr, FakeRunManager)


def test_build_web_returns_web_instance():
    with patch.dict("os.environ", {"WEB_RUN_MANAGER_URL": "https://api.example.com"}):
        mgr = build_run_manager(RunManagerType.WEB)
    assert isinstance(mgr, WebRunManager)
    assert mgr.base_url == "https://api.example.com"


def test_build_invalid_type_raises():
    with pytest.raises(ValueError, match="Unknown run_manager_type"):
        build_run_manager("nonexistent")  # type: ignore[arg-type]
