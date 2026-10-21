"""Session middleware with an explicit browser-session / remembered-session choice."""

from base64 import b64decode, b64encode
import json
from typing import Literal

from itsdangerous import BadSignature, TimestampSigner
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import Session
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RememberableSessionMiddleware:
    """Keep the session cookie only when the user explicitly asked for it.

    The signed payload always has a bounded lifetime.  A remembered login gets
    a persistent cookie; all other logins get a browser-session cookie.
    """

    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int | None = 14 * 24 * 60 * 60,
        remember_max_age: int = 14 * 24 * 60 * 60,
        path: str = "/",
        same_site: Literal["lax", "strict", "none"] = "lax",
        https_only: bool = False,
        domain: str | None = None,
    ) -> None:
        self.app = app
        self.signer = TimestampSigner(str(secret_key))
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.remember_max_age = remember_max_age
        self.path = path
        self.security_flags = "httponly; samesite=" + same_site
        if https_only:
            self.security_flags += "; secure"
        if domain is not None:
            self.security_flags += f"; domain={domain}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        initial_session_was_empty = True
        if self.session_cookie in connection.cookies:
            data = connection.cookies[self.session_cookie].encode("utf-8")
            try:
                data = self.signer.unsign(data, max_age=self.max_age)
                scope["session"] = Session(json.loads(b64decode(data)))
                initial_session_was_empty = False
            except BadSignature:
                scope["session"] = Session()
        else:
            scope["session"] = Session()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: Session = scope["session"]
                headers = MutableHeaders(scope=message)
                if session.accessed:
                    headers.add_vary_header("Cookie")
                if session.modified and session:
                    data = b64encode(json.dumps(session).encode("utf-8"))
                    signed_data = self.signer.sign(data).decode("utf-8")
                    cookie_max_age = self.remember_max_age if session.get("remember_me") else None
                    max_age = f"Max-Age={cookie_max_age}; " if cookie_max_age else ""
                    headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}={signed_data}; path={self.path}; "
                        f"{max_age}{self.security_flags}",
                    )
                elif session.modified and not initial_session_was_empty:
                    headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}=null; path={self.path}; "
                        "expires=Thu, 01 Jan 1970 00:00:00 GMT; "
                        f"{self.security_flags}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
