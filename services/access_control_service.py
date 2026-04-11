"""Centralised access-control service.

Permission matrix
-----------------
viewer  — read only (all drill-down and report pages)
manager — read + write (import, data-trust mutations, exception/action creation)
admin   — all of the above + team management, billing, settings mutations

Usage
-----
    from services.access_control_service import require_write

    def create_something(tenant_id: str, user_role: str = "", ...):
        require_write(user_role)
        ...

All ``require_*`` helpers raise ``AccessDeniedError`` on denial so callers do
not need extra branching — a single guard at the top is enough.

When ``user_role`` is left empty, ``require_write`` / ``require_admin`` default
to the most restrictive role (``viewer``), following the principle of least
privilege.  UI callers should always pass the role from session state explicitly
rather than relying on a default.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

ROLE_VIEWER = "viewer"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"

# Ordered from least to most privileged.  Used for comparison helpers.
_ROLE_RANK: dict[str, int] = {
    ROLE_VIEWER: 1,
    ROLE_MANAGER: 2,
    ROLE_ADMIN: 3,
}

# Legacy alias mapped before migration 018 renamed "member" → "manager".
_LEGACY_ALIASES: dict[str, str] = {
    "member": ROLE_MANAGER,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(role: str) -> str:
    """Lower-case, strip, and resolve legacy aliases."""
    cleaned = str(role or "").lower().strip()
    return _LEGACY_ALIASES.get(cleaned, cleaned) or ROLE_VIEWER


def _rank(role: str) -> int:
    return _ROLE_RANK.get(_normalize(role), 0)


# ---------------------------------------------------------------------------
# Boolean helpers (side-effect free)
# ---------------------------------------------------------------------------

def can_write(role: str) -> bool:
    """True for manager and admin roles."""
    return _rank(role) >= _rank(ROLE_MANAGER)


def can_admin(role: str) -> bool:
    """True for admin role only."""
    return _normalize(role) == ROLE_ADMIN


def can_import(role: str) -> bool:
    """Alias for can_write — importing data requires at least manager."""
    return can_write(role)


def can_manage_data_trust(role: str) -> bool:
    """Marking source data as trusted/untrusted requires at least manager."""
    return can_write(role)


def can_manage_team(role: str) -> bool:
    """Inviting/removing team members requires admin."""
    return can_admin(role)


# ---------------------------------------------------------------------------
# Enforcement guards (raise on denial)
# ---------------------------------------------------------------------------

class AccessDeniedError(PermissionError):
    """Raised when a user lacks the required role for an operation."""


def require_write(role: str) -> None:
    """Raise ``AccessDeniedError`` if the role cannot perform write operations.

    Args:
        role: The user's role string.  Pass ``""`` to use the most restrictive
              default (viewer).  UI callers should always supply the session role.
    """
    effective = _normalize(role)
    if not can_write(effective):
        raise AccessDeniedError(
            f"Role '{effective}' does not have write access. "
            "A 'manager' or 'admin' role is required."
        )


def require_admin(role: str) -> None:
    """Raise ``AccessDeniedError`` if the role is not admin.

    Args:
        role: The user's role string.  Pass ``""`` to use the most restrictive
              default (viewer).  UI callers should always supply the session role.
    """
    effective = _normalize(role)
    if not can_admin(effective):
        raise AccessDeniedError(
            f"Role '{effective}' does not have admin access. "
            "An 'admin' role is required."
        )

