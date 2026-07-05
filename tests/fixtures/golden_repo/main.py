"""Application entrypoint."""

from api.routes import register_routes
from auth.login import authenticate_user


def bootstrap(app):
    register_routes(app)
    authenticate_user("admin", "secret")