"""Tests for services.access_control_service."""

import pytest

from services.access_control_service import (
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_VIEWER,
    AccessDeniedError,
    can_admin,
    can_import,
    can_manage_data_trust,
    can_manage_team,
    can_write,
    require_admin,
    require_write,
)


# ---------------------------------------------------------------------------
# can_write
# ---------------------------------------------------------------------------

def test_viewer_cannot_write():
    assert can_write(ROLE_VIEWER) is False


def test_manager_can_write():
    assert can_write(ROLE_MANAGER) is True


def test_admin_can_write():
    assert can_write(ROLE_ADMIN) is True


def test_empty_role_treated_as_viewer():
    assert can_write("") is False


def test_unknown_role_cannot_write():
    assert can_write("superuser") is False


def test_legacy_member_role_can_write():
    """'member' is the pre-migration name for 'manager'."""
    assert can_write("member") is True


# ---------------------------------------------------------------------------
# can_admin
# ---------------------------------------------------------------------------

def test_admin_can_admin():
    assert can_admin(ROLE_ADMIN) is True


def test_manager_cannot_admin():
    assert can_admin(ROLE_MANAGER) is False


def test_viewer_cannot_admin():
    assert can_admin(ROLE_VIEWER) is False


# ---------------------------------------------------------------------------
# can_import / can_manage_data_trust / can_manage_team
# ---------------------------------------------------------------------------

def test_can_import_requires_manager():
    assert can_import(ROLE_VIEWER) is False
    assert can_import(ROLE_MANAGER) is True
    assert can_import(ROLE_ADMIN) is True


def test_can_manage_data_trust_requires_manager():
    assert can_manage_data_trust(ROLE_VIEWER) is False
    assert can_manage_data_trust(ROLE_MANAGER) is True


def test_can_manage_team_requires_admin():
    assert can_manage_team(ROLE_VIEWER) is False
    assert can_manage_team(ROLE_MANAGER) is False
    assert can_manage_team(ROLE_ADMIN) is True


# ---------------------------------------------------------------------------
# require_write
# ---------------------------------------------------------------------------

def test_require_write_passes_for_manager():
    require_write(ROLE_MANAGER)  # must not raise


def test_require_write_passes_for_admin():
    require_write(ROLE_ADMIN)  # must not raise


def test_require_write_raises_for_viewer():
    with pytest.raises(AccessDeniedError, match="write access"):
        require_write(ROLE_VIEWER)


def test_require_write_raises_for_empty_role():
    with pytest.raises(AccessDeniedError):
        require_write("")


def test_require_write_is_case_insensitive():
    require_write("MANAGER")  # must not raise


def test_require_write_accepts_legacy_member():
    require_write("member")  # must not raise


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

def test_require_admin_passes_for_admin():
    require_admin(ROLE_ADMIN)  # must not raise


def test_require_admin_raises_for_manager():
    with pytest.raises(AccessDeniedError, match="admin"):
        require_admin(ROLE_MANAGER)


def test_require_admin_raises_for_viewer():
    with pytest.raises(AccessDeniedError):
        require_admin(ROLE_VIEWER)


# ---------------------------------------------------------------------------
# AccessDeniedError is a PermissionError subclass
# ---------------------------------------------------------------------------

def test_access_denied_error_is_permission_error():
    with pytest.raises(PermissionError):
        require_write(ROLE_VIEWER)
