"""User persistence layer."""

from auth.login import authenticate_user


class UserService:
    def get_user(self, user_id: int):
        return {"id": user_id}

    def login(self, username: str, password: str) -> bool:
        return authenticate_user(username, password)