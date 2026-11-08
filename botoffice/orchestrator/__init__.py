"""Office orchestration: roles, layout and the four interaction modes."""

from .office import Office, Point, meeting_seat, walk_seconds
from .roles import Role, RoleRegistry, RoleScope

__all__ = [
    "Office",
    "Point",
    "Role",
    "RoleRegistry",
    "RoleScope",
    "meeting_seat",
    "walk_seconds",
]
