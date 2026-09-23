"""Calling an MCP server the desk's owner added.

The desk is a client here, not a server: a person registers their firm's
research server or a vendor's tools, and every specialist on that desk can
call them. Streamable HTTP, JSON-RPC 2.0, stdlib only, like app/mcp.py.

What this module refuses to do matters more than what it does. The request is
made by *our* server, from inside our network, to an address the customer
typed. Without a check that is a way to read anything our container can
reach: the cloud metadata endpoint, a database on a private address, the
Observatory's own admin port. So a host is resolved first and every address
it resolves to must be public, the scheme must be https (except an explicitly
allowed host for local development), redirects are not followed, the reply is
capped, and the timeout is short.
"""
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "plover-desk", "version": "1.0.0"}
TIMEOUT_SECONDS = 30
MAX_BYTES = 2 * 1024 * 1024
MAX_TOOLS = 60


class RemoteError(Exception):
    """The server could not be reached, refused us, or answered badly."""


def _allowed_hosts():
    raw = os.environ.get("ASSISTANT_MCP_ALLOW_HOSTS", "")
    return set(h.strip().lower() for h in raw.split(",") if h.strip())


def check_url(url):
    """Return the URL if a desk may call it, else raise RemoteError."""
    url = (url or "").strip()
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        raise RemoteError("That is not a URL.")
    host = (parts.hostname or "").lower()
    if not host:
        raise RemoteError("Give the server's full URL, including https://.")
    allowed = _allowed_hosts()
    if host in allowed:
        return url
    if parts.scheme != "https":
        raise RemoteError("An MCP server must be reached over https.")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise RemoteError("That host does not resolve.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise RemoteError("That address is inside a private network, so it cannot be "
                              "reached from here.")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could land on an address the check above just refused."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RemoteError("The server redirected; give its direct URL.")


def _headers(server, secret_value):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    kind = server.get("auth_kind") or "none"
    if kind == "bearer" and secret_value:
        h["Authorization"] = "Bearer " + secret_value
    elif kind == "header" and secret_value:
        h[(server.get("header_name") or "Authorization").strip()] = secret_value
    return h


def rpc(server, method, params=None, secret_value=None, msg_id=1):
    """One JSON-RPC call. Returns the `result`, or raises RemoteError."""
    url = check_url(server.get("url"))
    body = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method,
                       "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in _headers(server, secret_value).items():
        req.add_header(k, v)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except RemoteError:
        raise
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        if exc.code in (401, 403):
            raise RemoteError("The server refused the key (HTTP %s)." % exc.code)
        raise RemoteError("The server answered HTTP %s. %s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise RemoteError("The server could not be reached (%s)." % exc.reason)
    except (socket.timeout, TimeoutError):
        raise RemoteError("The server did not answer in %d seconds." % TIMEOUT_SECONDS)
    if len(raw) > MAX_BYTES:
        raise RemoteError("The server's reply was too large.")
    if not raw.strip():
        return {}
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RemoteError("The server did not answer with JSON.")
    if isinstance(msg, list):
        msg = msg[0] if msg else {}
    if isinstance(msg, dict) and msg.get("error"):
        raise RemoteError(str(msg["error"].get("message") or msg["error"])[:200])
    return (msg or {}).get("result") or {}


def connect(server, secret_value=None):
    """Handshake and list the tools. Returns (server_info, tools)."""
    info = rpc(server, "initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": CLIENT_INFO}, secret_value)
    result = rpc(server, "tools/list", {}, secret_value, msg_id=2)
    tools = []
    for t in (result.get("tools") or [])[:MAX_TOOLS]:
        if not t.get("name"):
            continue
        tools.append({"name": t["name"],
                      "description": (t.get("description") or "")[:600],
                      "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
                      "annotations": t.get("annotations") or {}})
    return (info.get("serverInfo") or {}), tools


def call_tool(server, name, args, secret_value=None):
    """Run one tool. Returns (text, is_error) like the local tool layer."""
    try:
        result = rpc(server, "tools/call", {"name": name, "arguments": args or {}}, secret_value)
    except RemoteError as exc:
        return json.dumps({"error": str(exc)}), True
    parts = []
    for block in result.get("content") or []:
        if block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif block.get("type") == "resource":
            res = block.get("resource") or {}
            parts.append(res.get("text") or res.get("uri") or "")
    text = "\n".join(p for p in parts if p) or json.dumps(result)[:4000]
    return text, bool(result.get("isError"))
