from django.db.models import IntegerChoices


class TrustLevel(IntegerChoices):
    """
    Represents two, related things:
    1. The level of Trust a User has selected to have for a specific
       Group. For example, a User may trust a public group less than
       they trust a group of their close friends.
    2. The level of Trust a user **requires** in order to lend out a
       specific Item. E.g, a user may require a higher level of trust
       to lend an Item that is very valuable or important to them.
    The TrustLevel is therefore crucial to the functioning of the
    system. It is used at query time in order to determine which
    users can see which items for borrowing.
    """

    LOW = 1, "Low"
    MEDIUM = 2, "Medium"
    HIGH = 3, "High"
