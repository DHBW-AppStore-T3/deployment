"""noVNC in the browser, bridged to the VNC stream of one KubeVirt VM.

QEMU's VNC of a KubeVirt VM is a unix socket inside the virt-launcher pod, not a
pod port, so there is nothing to point websockify at. KubeVirt serves it as a
WebSocket on the API server (``virtualmachineinstances/<name>/vnc``); this proxy
opens that with its service account (which may do exactly that, see the chart's
``vnc-proxy`` role) and hands the bytes to noVNC.

Everything, the page and the stream, is behind HTTP basic auth with the generated
password of the person the VM belongs to. Configuration comes from the environment:
VM_NAME, VM_NAMESPACE, PROXY_USER, PROXY_PASSWORD.
"""

import asyncio
import base64
import contextlib
import hmac
import os
import ssl
from urllib.parse import urlsplit

from aiohttp import ClientSession, WSMsgType, web

KUBE_API = os.environ.get("KUBE_API", "https://kubernetes.default.svc")
SERVICE_ACCOUNT = os.environ.get("SERVICE_ACCOUNT_DIR", "/var/run/secrets/kubernetes.io/serviceaccount")
NOVNC_DIR = os.environ.get("NOVNC_DIR", "/usr/share/novnc")
SUBPROTOCOL = "plain.kubevirt.io"


def _authorised(header: str, user: str, password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        given_user, _, given_password = base64.b64decode(header[6:]).decode().partition(":")
    except ValueError:
        return False
    # Both compared always, so the time taken does not tell which one was wrong.
    user_ok = hmac.compare_digest(given_user.encode(), user.encode())
    password_ok = hmac.compare_digest(given_password.encode(), password.encode())
    return user_ok and password_ok


@web.middleware
async def basic_auth(request: web.Request, handler):
    config = request.app["config"]
    if not _authorised(request.headers.get("Authorization", ""), config["user"], config["password"]):
        raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="VM", charset="UTF-8"'})
    return await handler(request)


async def index(_: web.Request) -> web.Response:
    raise web.HTTPFound("/vnc.html?autoconnect=true&resize=scale&path=websockify")


async def _pump_to_upstream(browser: web.WebSocketResponse, upstream) -> None:
    async for msg in browser:
        if msg.type == WSMsgType.BINARY:
            await upstream.send_bytes(msg.data)
        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
            break


async def _pump_to_browser(browser: web.WebSocketResponse, upstream) -> None:
    async for msg in upstream:
        if msg.type == WSMsgType.BINARY:
            await browser.send_bytes(msg.data)
        elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
            break


async def websockify(request: web.Request) -> web.StreamResponse:
    # A page of another site must not be able to open this stream with the person's cached credentials.
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.headers.get("Host"):
        raise web.HTTPForbidden(text="cross-origin")
    config = request.app["config"]
    browser = web.WebSocketResponse(protocols=("binary",), max_msg_size=0)
    await browser.prepare(request)
    url = (
        f"{KUBE_API}/apis/subresources.kubevirt.io/v1/namespaces/{config['namespace']}"
        f"/virtualmachineinstances/{config['vm']}/vnc"
    )
    token = open(f"{SERVICE_ACCOUNT}/token").read().strip()
    try:
        async with request.app["session"].ws_connect(
            url,
            headers={"Authorization": f"Bearer {token}"},
            protocols=(SUBPROTOCOL,),
            ssl=request.app["ssl"],
            max_msg_size=0,
        ) as upstream:
            tasks = [
                asyncio.create_task(_pump_to_upstream(browser, upstream)),
                asyncio.create_task(_pump_to_browser(browser, upstream)),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except Exception as exc:  # the VM is not (yet) running, the API refused, ...
        await browser.close(code=1011, message=str(exc)[:100].encode())
    finally:
        with contextlib.suppress(Exception):
            await browser.close()
    return browser


def make_app() -> web.Application:
    app = web.Application(middlewares=[basic_auth])
    app["config"] = {
        "vm": os.environ["VM_NAME"],
        "namespace": os.environ["VM_NAMESPACE"],
        "user": os.environ["PROXY_USER"],
        "password": os.environ["PROXY_PASSWORD"],
    }
    ca = f"{SERVICE_ACCOUNT}/ca.crt"
    app["ssl"] = ssl.create_default_context(cafile=ca) if os.path.exists(ca) else None

    async def open_session(app: web.Application) -> None:
        app["session"] = ClientSession()

    async def close_session(app: web.Application) -> None:
        await app["session"].close()

    app.on_startup.append(open_session)
    app.on_cleanup.append(close_session)
    app.router.add_get("/", index)
    app.router.add_get("/websockify", websockify)
    app.router.add_static("/", NOVNC_DIR)
    return app


if __name__ == "__main__":
    # No host: every address of the machine, IPv4 and IPv6. The cluster is dual-stack with IPv6 first, so
    # the pod's address (and its readiness probe) is an IPv6 one.
    web.run_app(make_app(), host=None, port=8080)
