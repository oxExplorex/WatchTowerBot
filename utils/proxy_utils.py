import re

import data.text as constant_text

_PROXY_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _valid_port(port: str) -> bool:
    if not port.isdigit():
        return False
    value = int(port)
    return 1 <= value <= 65535


def _valid_host(host: str) -> bool:
    if not host:
        return False
    if _PROXY_IPV4_RE.match(host):
        return all(0 <= int(part) <= 255 for part in host.split("."))
    return True


def normalize_http_proxy_input(raw_value: str) -> str | None:
    value = (raw_value or "").strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered.startswith("socks"):
        return None

    if lowered.startswith("http://"):
        core = value[7:]
    elif "://" in lowered:
        return None
    else:
        core = value

    # format: ip:port:user:password
    parts = core.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        if not (_valid_host(host) and _valid_port(port) and user and password):
            return None
        return f"http://{user}:{password}@{host}:{port}"

    # format: ip:port@user:password
    if "@" in core:
        left, right = core.split("@", 1)
        left_parts = left.split(":")
        right_parts = right.split(":")
        if len(left_parts) != 2 or len(right_parts) != 2:
            return None

        host, port = left_parts
        user, password = right_parts
        if not (_valid_host(host) and _valid_port(port) and user and password):
            return None
        return f"http://{user}:{password}@{host}:{port}"

    return None


def compact_proxy_display(proxy_url: str | None) -> str:
    if not proxy_url:
        return constant_text.PROXY_NOT_SET_TEXT

    value = proxy_url.replace("http://", "", 1)
    if "@" not in value:
        return value

    creds, hostpart = value.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
    else:
        user = creds
    return f"{user}:***@{hostpart}"


