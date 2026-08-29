"""repositories — Data access layer for the crosswalk alert system."""

from repositories.user_repository import UserRepository
from repositories.event_repository import EventRepository

user_repo = UserRepository()
event_repo = EventRepository()

__all__ = ["UserRepository", "EventRepository", "user_repo", "event_repo"]
