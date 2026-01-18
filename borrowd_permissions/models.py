"""
In this file, OLP stands for Object Level Permissions.
"""

from enum import StrEnum


class BorrowdGroupOLP(StrEnum):
    VIEW = "view_this_group"
    EDIT = "edit_this_group"
    DELETE = "delete_this_group"


class ItemOLP(StrEnum):
    VIEW = "view_this_item"
    EDIT = "edit_this_item"
    DELETE = "delete_this_item"
