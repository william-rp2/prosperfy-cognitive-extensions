"""
tests/unit/test_prosperfy_skills_guard.py — Testes da boundary guard (Sprint 0.3).

ADR-V2-003: adapter é o único boundary externo do Cognitive para o
ProsperfySkill. guard_arguments() é a defesa em profundidade que bloqueia
comando/shell arbitrário e 'resource' malformado (IP/host se passando por
resource lógico) antes de qualquer chamada — real ou mock.
"""

from __future__ import annotations

import pytest

from cognitive.adapters.prosperfy_skills.guard import (
    ForbiddenArgumentError,
    guard_arguments,
)


class TestForbiddenArgKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "command",
            "cmd",
            "comando",
            "shell",
            "bash",
            "exec",
            "execute",
            "script",
            "sh",
            "powershell",
            "eval",
        ],
    )
    def test_forbidden_key_rejected(self, key):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": "prosperfy-main", key: "rm -rf /"})

    def test_multiple_forbidden_keys_rejected_together(self):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments(
                "prosperfy_vps_panorama",
                {"resource": "prosperfy-main", "command": "ls", "shell": "/bin/sh"},
            )

    def test_legit_arguments_without_forbidden_keys_pass(self):
        # Não deve levantar.
        guard_arguments("prosperfy_vps_panorama", {"host": "mock-vps.test", "token": "x"})


class TestResourceValidation:
    def test_valid_slug_passes(self):
        guard_arguments("prosperfy_vps_panorama", {"resource": "prosperfy-main"})

    def test_valid_slug_with_underscore_and_digits_passes(self):
        guard_arguments("prosperfy_vps_panorama", {"resource": "tenant_2-main9"})

    def test_ipv4_as_resource_rejected(self):
        """ADR-V2-002: cliente nunca deve conseguir passar um IP como 'resource'."""
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": "192.168.1.1"})

    def test_hostname_with_dots_as_resource_rejected(self):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": "evil.example.com"})

    def test_ipv6_as_resource_rejected(self):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": "::1"})

    def test_non_string_resource_rejected(self):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": 12345})

    def test_resource_with_shell_metacharacters_rejected(self):
        with pytest.raises(ForbiddenArgumentError):
            guard_arguments("prosperfy_vps_panorama", {"resource": "prosperfy-main; rm -rf /"})

    def test_absent_resource_key_passes(self):
        # Capabilities sem resource lógico (ex: já resolvido) não devem ser bloqueadas.
        guard_arguments("prosperfy_vps_panorama", {"host": "mock-vps.test"})
