"""User model."""


class User:
    def __init__(self, username: str, email: str, password: str):
        self.username = username
        self.email = email
        self.password = password
        self.is_active = True

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
        }