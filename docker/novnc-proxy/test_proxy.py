"""Runs the noVNC proxy against a fake Kubernetes API: auth, origin check, and the VNC bridge.

    python docker/novnc-proxy/test_proxy.py   (needs aiohttp)
"""
import asyncio, base64, os, sys, tempfile, pathlib
from aiohttp import web, ClientSession, WSMsgType

tmp = pathlib.Path(tempfile.mkdtemp()); (tmp/"token").write_text("tok123\n")
novnc = tmp/"novnc"; novnc.mkdir(); (novnc/"vnc.html").write_text("<html>noVNC</html>")
seen = {}

async def fake_vnc(request):
    seen["auth"] = request.headers.get("Authorization"); seen["path"] = request.path
    ws = web.WebSocketResponse(protocols=("plain.kubevirt.io",)); await ws.prepare(request)
    await ws.send_bytes(b"RFB 003.008\n")
    async for m in ws:
        if m.type == WSMsgType.BINARY: await ws.send_bytes(b"echo:" + m.data)
    return ws

async def main():
    api = web.Application(); api.router.add_get("/apis/subresources.kubevirt.io/v1/namespaces/{ns}/virtualmachineinstances/{vm}/vnc", fake_vnc)
    r = web.AppRunner(api); await r.setup(); await web.TCPSite(r, "127.0.0.1", 18091).start()
    os.environ.update(KUBE_API="http://127.0.0.1:18091", SERVICE_ACCOUNT_DIR=str(tmp), NOVNC_DIR=str(novnc),
                      VM_NAME="win-anna", VM_NAMESPACE="dep-1234abcd", PROXY_USER="anna", PROXY_PASSWORD="s3cret")
    sys.path.insert(0, str(pathlib.Path(__file__).parent)); import proxy
    pr = web.AppRunner(proxy.make_app()); await pr.setup(); await web.TCPSite(pr, "127.0.0.1", 18092).start()
    good = {"Authorization": "Basic " + base64.b64encode(b"anna:s3cret").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"anna:wrong").decode()}
    async with ClientSession() as s:
        assert (await s.get("http://127.0.0.1:18092/vnc.html")).status == 401
        assert (await s.get("http://127.0.0.1:18092/vnc.html", headers=bad)).status == 401
        resp = await s.get("http://127.0.0.1:18092/vnc.html", headers=good); assert resp.status == 200 and "noVNC" in await resp.text()
        resp = await s.get("http://127.0.0.1:18092/", headers=good, allow_redirects=False); assert resp.status == 302
        try:
            await s.ws_connect("http://127.0.0.1:18092/websockify"); raise SystemExit("no-auth ws accepted?")
        except Exception as e: assert "401" in str(e), e
        try:
            await s.ws_connect("http://127.0.0.1:18092/websockify", headers={**good, "Origin": "https://evil.example"}); raise SystemExit("cross-origin accepted")
        except Exception as e: assert "403" in str(e), e
        async with s.ws_connect("http://127.0.0.1:18092/websockify", headers={**good, "Origin": "http://127.0.0.1:18092"}, protocols=("binary",)) as ws:
            assert (await ws.receive()).data == b"RFB 003.008\n"
            await ws.send_bytes(b"hi"); assert (await ws.receive()).data == b"echo:hi"
    assert seen["auth"] == "Bearer tok123" and seen["path"].endswith("/namespaces/dep-1234abcd/virtualmachineinstances/win-anna/vnc"), seen
    print("proxy smoke test OK")
asyncio.run(main())
