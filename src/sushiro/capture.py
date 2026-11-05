"""Capture a live auth_token from the phone's own WeChat session.

``js_code`` is issued by WeChat and single-use, and the server never leaks the
JWT signing key, so a token cannot be minted offline. The only renewable path is
to watch real traffic: the mini-program refreshes its token roughly hourly, and
this addon writes each fresh one to ``token.txt`` and ``config.json``.

Runs mitmproxy in-process, so there is no separate mitmdump command to
remember::

    sushiro capture            # 0.0.0.0:8888
    sushiro capture --port 9090

Then point the phone's Wi-Fi proxy at this machine, install the CA from
``mitm.it``, and open the mini-program once.
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime

from . import auth, paths

HOSTS = ("sapi.sushiro.com.cn", "miniprogram-api.sushiro.com.cn")
BEARER = re.compile(r"Bearer\s+([A-Za-z0-9._\-]+)")
AUTH_TOKEN = re.compile(r'"auth_token"\s*:\s*"([A-Za-z0-9._\-]+)"')
STORE_ID = re.compile(r"[?&](?:storeId|shop_id|id)=([0-9]+)")


def _log(message: str) -> None:
    print(message, flush=True)


def lan_ip() -> str:
    """Best-effort local address, so the printed instructions are usable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("223.5.5.5", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class TokenCapture:
    """mitmproxy addon: harvest tokens and keep one sample of each payload."""

    def _save_token(self, token: str, source: str) -> None:
        if len(token) < 20:
            return
        if not auth.is_fresh(token):
            # WeChat replays a cached token after a 401; only store live ones.
            _log(f"[skip] 忽略过期 token（来自 {source}），继续等微信刷新")
            return
        target = paths.token_file()
        if target.is_file() and target.read_text(encoding="utf-8").strip() == token:
            return
        auth.store_token(token)
        _log(f"[captured] 有效 auth_token  <- {source}")
        expiry = auth.token_expiry(token)
        if expiry:
            _log(f"[auto-refresh] 新 token 有效至 {expiry:%Y-%m-%d %H:%M:%S}")

    def _save_sample(self, url: str, body: str) -> None:
        if not body:
            return
        if "/getStoreById" in url:
            name = "store.json"
        elif "/store/timeslots" in url:
            name = "timeslots.json"
        elif "/wechat/api/2.0/stores" in url:
            name = "stores.json"
        else:
            return
        directory = paths.samples()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        if target.exists():
            return
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"[sample] samples/{target.name}")

    def _note_client(self, headers) -> None:
        """Record which iOS and WeChat build produced this traffic.

        Endpoint behaviour drifts with the client version (the ``profile`` call
        changed verb between builds), so keep the identifying headers around.
        """
        user_agent = headers.get("User-Agent", "")
        if not user_agent:
            return
        target = paths.root() / "client-info.json"
        if target.is_file():
            try:
                if json.loads(target.read_text(encoding="utf-8")).get("user_agent") == user_agent:
                    return
            except json.JSONDecodeError:
                pass
        info = {
            "user_agent": user_agent,
            "miniapp_version": headers.get("X-Miniapp-Version"),
            "app_client": headers.get("X-App-Client"),
            "session_id": headers.get("x-miniapp-session-id"),
            "seen_at": datetime.now().isoformat(timespec="seconds"),
        }
        payload = json.dumps(info, ensure_ascii=False, indent=2) + "\n"
        target.write_text(payload, encoding="utf-8")
        _log(f"[client] {user_agent[:140]}")

    def _inspect(self, url: str, headers, body: str, source: str) -> None:
        if not any(host in url for host in HOSTS):
            return
        self._note_client(headers)
        authorization = headers.get("Authorization", "")
        match = BEARER.search(authorization or "")
        if match:
            self._save_token(match.group(1), source + " (Authorization header)")
        match = AUTH_TOKEN.search(body or "")
        if match:
            self._save_token(match.group(1), source + " (initialize response)")
        self._save_sample(url, body or "")

    # -- mitmproxy hooks ---------------------------------------------------

    def request(self, flow) -> None:
        try:
            self._inspect(flow.request.pretty_url, flow.request.headers, "",
                          flow.request.path)
        except Exception as exc:  # never let a hook kill the proxy
            _log(f"[warn] request hook: {exc}")

    def response(self, flow) -> None:
        try:
            body = flow.response.get_text(strict=False)
        except Exception:
            body = ""
        try:
            self._inspect(flow.request.pretty_url, flow.request.headers, body,
                          flow.request.path)
        except Exception as exc:
            _log(f"[warn] response hook: {exc}")

    def tls_clienthello(self, data) -> None:
        try:
            sni = data.client_hello.sni
            if sni and any(host in sni for host in HOSTS):
                _log(f"[tls] ClientHello SNI={sni}")
        except Exception:
            pass

    def tls_failed_client(self, data) -> None:
        try:
            context = data.context.client
            peer = context.peername[0] if context.peername else "?"
            _log(f"[tls] {peer} 拒绝了我们签发的证书")
        except Exception:
            _log("[tls] 客户端拒绝了我们签发的证书")

    def tls_failed_server(self, data) -> None:
        try:
            server = data.context.server
            _log(f"[tls] 上游握手失败 {server.address if server else '?'}")
        except Exception:
            _log("[tls] 上游握手失败")

    def error(self, flow) -> None:
        url = getattr(getattr(flow, "request", None), "pretty_url", "")
        if any(host in url for host in HOSTS):
            _log("[hint] TLS 握手失败 —— iOS 需在 设置→通用→关于本机→证书信任设置 打开开关")


def run(*, host: str = "0.0.0.0", port: int = 8888,
        data_dir: str | None = None) -> int:
    try:
        from mitmproxy import options
        from mitmproxy.tools.dump import DumpMaster
    except ImportError:
        print("mitmproxy 未安装，抓包需要额外依赖：\n"
              "  uv sync --extra capture\n"
              "  uv run sushiro capture")
        return 1

    import asyncio

    paths.bind(data_dir)
    confdir = paths.mitm_confdir()
    confdir.mkdir(parents=True, exist_ok=True)

    ip = lan_ip()
    _log(f"代理监听 {host}:{port}，CA 目录 {confdir}")
    _log(f"手机 Wi-Fi 设置 HTTP 代理 → {ip}:{port}，浏览器打开 mitm.it 安装证书")
    _log("随后打开寿司郎小程序，让 token 刷新一次即可。Ctrl+C 退出。")

    opts = options.Options(listen_host=host, listen_port=port, confdir=str(confdir))

    async def serve() -> None:
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(TokenCapture())
        try:
            await master.run()
        finally:
            master.shutdown()

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        _log("已停止抓包")
    return 0
