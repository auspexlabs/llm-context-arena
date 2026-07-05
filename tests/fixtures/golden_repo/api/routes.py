"""API route handlers."""

from auth.middleware import auth_middleware
from services.user_service import UserService


def register_routes(app):
    service = UserService()

    @app.get("/users/{user_id}")
    def fetch_user(user_id: int):
        auth_middleware(app.request)
        return service.get_user(user_id)