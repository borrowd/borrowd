from .models import BorrowdUser, MenuBadgeState

def menu_badges(request):
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return {"menu_badges": None}

    state = MenuBadgeState.for_user(user)
    return {"menu_badges": state}