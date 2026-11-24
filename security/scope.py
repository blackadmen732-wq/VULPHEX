# VULPHEX scope gate: the one rule that keeps this a defensive tool. An ACTIVE scan (anything that reaches a target over
# the network) runs ONLY if that exact target is listed in security/scope.json as something you own or have written
# permission to test. Local code audits read your own files and need no entry. Default = deny.
import fnmatch, ipaddress, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))


class OutOfScope(Exception): pass


def load(path=None):
    p = path or os.path.join(HERE, "scope.json")
    try: s = json.load(open(p))
    except (OSError, ValueError): s = {}
    return {"hosts": [h.strip().lower() for h in s.get("hosts", []) if str(h).strip()],
            "allow_private_ranges": bool(s.get("allow_private_ranges", False)),
            "owner": s.get("owner", ""), "authorization_note": s.get("authorization_note", "")}


def host_of(target):
    t = re.sub(r"^[a-z]+://", "", str(target).strip().lower())
    t = t.split("/")[0].split("@")[-1]
    if t.startswith("["): return t[1:t.index("]")]                      # [ipv6]:port
    return t.rsplit(":", 1)[0] if t.count(":") == 1 else t


def _is_private(host):
    try: return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError: return host in ("localhost",)


def check(target, scope):
    """Raise OutOfScope unless an active scan of `target` is authorized. Returns the host on success."""
    host = host_of(target)
    if not host: raise OutOfScope("no target host given")
    if _is_private(host):
        if scope["allow_private_ranges"] or any(fnmatch.fnmatch(host, h) for h in scope["hosts"]): return host
        raise OutOfScope(f"{host} is a private/loopback address; set allow_private_ranges or list it in scope.json")
    if not scope["hosts"]:
        raise OutOfScope("scope.json lists no authorized targets yet; add the hosts you own or are allowed to test")
    if any(fnmatch.fnmatch(host, h) for h in scope["hosts"]): return host
    raise OutOfScope(f"{host} is not in scope.json. VULPHEX only scans targets you own or have written permission to test.")
