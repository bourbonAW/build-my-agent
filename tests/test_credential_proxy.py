"""Unit tests for CredentialProxy."""

from __future__ import annotations

import urllib.request

import pytest

from bourbon.sandbox.credential_proxy import CredentialProxy


class TestCredentialProxyLifecycle:
    def test_start_returns_address(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        addr = proxy.start()
        try:
            assert ":" in addr
            host, port_str = addr.rsplit(":", 1)
            assert int(port_str) > 0
        finally:
            proxy.stop()

    def test_stop_is_idempotent(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        proxy.start()
        proxy.stop()
        proxy.stop()  # second stop should not raise

    def test_address_before_start_raises(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        with pytest.raises(RuntimeError, match="not started"):
            _ = proxy.address


class TestCredentialProxyDomainMatching:
    def test_exact_domain_allowed(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["api.example.com"])
        assert proxy._is_domain_allowed("api.example.com") is True

    def test_exact_domain_denied(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["api.example.com"])
        assert proxy._is_domain_allowed("other.example.com") is False

    def test_wildcard_matches_subdomain(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["*.example.com"])
        assert proxy._is_domain_allowed("api.example.com") is True
        assert proxy._is_domain_allowed("cdn.example.com") is True

    def test_wildcard_does_not_match_root(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["*.example.com"])
        assert proxy._is_domain_allowed("example.com") is False

    def test_empty_allowlist_denies_all(self) -> None:
        proxy = CredentialProxy(credential_mgr=None, allow_domains=[])
        assert proxy._is_domain_allowed("api.example.com") is False

    def test_denied_domain_returns_403(self) -> None:
        """Proxy returns HTTP 403 for non-allowlisted domain."""
        proxy = CredentialProxy(credential_mgr=None, allow_domains=["allowed.com"])
        addr = proxy.start()
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": f"http://{addr}"})
            opener = urllib.request.build_opener(proxy_handler)
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open("http://denied.com/path", timeout=3)
            assert exc_info.value.code == 403
        finally:
            proxy.stop()
