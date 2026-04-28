"""User service."""

from src.models import User


_users: dict[str, User] = {}


def register(username: str, email: str, password: str) -> dict:
    if username in _users:
        raise ValueError(f"User {username} already exists")
    user = User(username, email, password)
    _users[username] = user
    return user.to_dict()


def get_user(username: str) -> dict:
    user = _users.get(username)
    if not user:
        raise ValueError(f"User {username} not found")
    user_dict = user.to_dict()
    if 'password' in user_dict:
        del user_dict['password']
    return user_dict
