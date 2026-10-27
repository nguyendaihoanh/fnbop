"""
Kiểm thử dịch vụ mDNS Broadcaster (chamcong.local) cho Standalone POS
"""

import socket
import pytest
try:
    from backend.services.mdns_service import MDNSBroadcaster, get_lan_ip, ZEROCONF_AVAILABLE
except ImportError:
    from services.mdns_service import MDNSBroadcaster, get_lan_ip, ZEROCONF_AVAILABLE

def test_get_lan_ip_format():
    ip = get_lan_ip()
    assert isinstance(ip, str)
    parts = ip.split(".")
    assert len(parts) == 4
    for p in parts:
        assert 0 <= int(p) <= 255

def test_mdns_broadcaster_lifecycle():
    broadcaster = MDNSBroadcaster(hostname="chamcong.local", port=8100, check_interval_secs=10)
    started = broadcaster.start()
    if ZEROCONF_AVAILABLE:
        assert started is True
        assert broadcaster._running is True
        assert broadcaster.current_ip is not None
        # Start again should be idempotent
        assert broadcaster.start() is True
        broadcaster.stop()
        assert broadcaster._running is False
        assert broadcaster.zc is None
    else:
        assert started is False
