"""找出"朋友可能連得到"的本地位址：虛擬網路（Tailscale／Radmin VPN／Hamachi／ZeroTier）與區網

只看這台電腦的網路介面位址，不會對外連線、也不會送出任何資料

Find local addresses that friends might be able to reach: virtual networks
(Tailscale / Radmin VPN / Hamachi / ZeroTier) and the LAN.

It only inspects this computer's own network interfaces. It never contacts the internet and sends no data.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

# (優先順序, 網段, 標籤)：越前面越優先，虛擬網路排在區網前面，因為朋友多半不在同一個區網
# (priority, network range, label): lower number wins. Virtual networks rank above the LAN
# because friends are usually not on the same LAN as the host.
_RANGES = [
    (0, "100.64.0.0/10", "Tailscale"),
    (1, "26.0.0.0/8", "Radmin VPN"),
    (2, "25.0.0.0/8", "Hamachi"),
]


@dataclass(frozen=True)
class Candidate:
    """一個可分享的網址候選 / One shareable-URL candidate."""
    ip: str
    label: str
    priority: int
    url: str
    note: str = ""


# ============================================================
# 偵測 / Detection
# ============================================================
def local_ipv4s() -> list[str]:
    """這台電腦所有 IPv4 位址（不含 127.x 與 169.254.x）

    All IPv4 addresses of this machine (excluding loopback 127.x and link-local 169.254.x).
    """
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:  # 主要對外介面（UDP connect 不會真的送封包）/ the primary outbound interface (a UDP "connect" sends no packet)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # 192.0.2.0/24 是文件專用保留網段 / reserved documentation range (TEST-NET-1)
            found.append(s.getsockname()[0])
    except OSError:
        pass
    seen: list[str] = []
    for ip in found:
        addr = ipaddress.ip_address(ip)
        if not (addr.is_loopback or addr.is_link_local) and ip not in seen:
            seen.append(ip)
    return seen


def classify(ip: str) -> tuple[int, str, str]:
    """回傳 (優先順序, 標籤, 備註)

    Classify an address and return ``(priority, label, note)``.
    """
    addr = ipaddress.ip_address(ip)
    for prio, net, label in _RANGES:
        if addr in ipaddress.ip_network(net):
            return prio, label, "虛擬網路：朋友也要安裝並加入同一個網路"
    if addr.is_private:
        return 3, "區網／虛擬網路（如 ZeroTier）", "同一個區網或同一個虛擬網路才連得到"
    return 4, "公網 IP", "通常被防火牆擋住，且 HTTP 不加密，不建議"


# ============================================================
# 組成網址 / Building URLs
# ============================================================
def candidates(port: int, ips: list[str] | None = None) -> list[Candidate]:
    """把每個位址組成候選網址，依優先順序排序

    Turn every address into a candidate URL, sorted by priority.
    Pass ``ips`` to bypass detection (handy in tests).
    """
    out = []
    for ip in (local_ipv4s() if ips is None else ips):
        prio, label, note = classify(ip)
        out.append(Candidate(ip, label, prio, f"http://{ip}:{port}", note))
    return sorted(out, key=lambda c: c.priority)


def best_url(port: int, ips: list[str] | None = None) -> Candidate | None:
    """挑最適合分享的位址，公網 IP 不自動採用（不加密、多半連不到）

    Pick the best address to share. Public IPs are never chosen automatically
    (traffic is unencrypted HTTP and usually blocked by firewalls).
    """
    for c in candidates(port, ips):
        if c.priority < 4:
            return c
    return None
