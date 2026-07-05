"""HTTP auth middleware."""

from auth.login import verify_token


def auth_middleware(request):
    token = request.headers.get("Authorization", "")
    if not verify_token(token):
        raise PermissionError("unauthorized")
    return request