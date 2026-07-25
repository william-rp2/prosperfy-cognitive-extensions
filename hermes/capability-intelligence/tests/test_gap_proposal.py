"""
Testes do Gap Proposal.
"""

from capability_intelligence.gap_proposal import GapProposalStore


class TestGapProposal:
    """Testes de registro de lacunas."""

    def test_register_gap(self):
        store = GapProposalStore()
        gap = store.register(intent="migrate database", domain="infrastructure")
        assert gap.intent == "migrate database"
        assert gap.domain == "infrastructure"
        assert gap.requested_by == "hermes"

    def test_list_gaps(self):
        store = GapProposalStore()
        store.register(intent="a", domain="infrastructure")
        store.register(intent="b", domain="marketing")
        assert len(store.list_gaps()) == 2

    def test_count_by_domain(self):
        store = GapProposalStore()
        store.register(intent="a", domain="infrastructure")
        store.register(intent="b", domain="infrastructure")
        store.register(intent="c", domain="marketing")
        assert store.count_by_domain("infrastructure") == 2
        assert store.count_by_domain("marketing") == 1
        assert store.count_by_domain("finance") == 0