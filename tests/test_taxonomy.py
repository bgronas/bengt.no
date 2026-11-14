from __future__ import annotations

from pathlib import Path

import pytest
from lib import content
from lib.common import PolicyError, load_policy
from lib.taxonomy import Taxonomy

from tests.conftest import make_meta


@pytest.fixture
def tax(repo: Path) -> Taxonomy:
    return Taxonomy(load_policy().taxonomy)


def test_unambiguous_variants_normalise(tax: Taxonomy) -> None:
    result = tax.normalise_tags(["K8s", "kubernetes", "gitops", "hugo", "GITHUB ACTIONS", "home-assistant"])
    assert result.tags == ["Kubernetes", "GitOps", "Hugo", "GitHub Actions", "Home Assistant"]
    assert not result.unknown and not result.ambiguous


def test_ambiguous_ha_is_never_converted(tax: Taxonomy) -> None:
    result = tax.normalise_tags(["ha", "HA"])
    assert result.tags == []
    assert set(result.ambiguous) == {"ha", "HA"}
    assert "Home Assistant" in result.ambiguous["ha"] and "High Availability" in result.ambiguous["ha"]


def test_distinct_concepts_are_not_conflated(tax: Taxonomy) -> None:
    result = tax.normalise_tags(["Kubernetes", "OpenShift", "Docker", "Home Assistant", "Home Automation"])
    assert result.tags == ["Kubernetes", "Home Assistant"]
    assert result.unknown == ["OpenShift", "Docker", "Home Automation"]


def test_author_supplied_disallowed_values_fail_validation(repo: Path, tax: Taxonomy) -> None:
    policy = load_policy()
    issues = content.validate_meta(
        policy, tax, make_meta(categories=["Gardening"], tags=["Hugo", "Docker", "ha", "k8s"])
    )
    codes = {i.code for i in issues if i.severity == "error"}
    assert {"category-not-allowed", "tag-not-allowed", "tag-ambiguous", "tag-spelling"} <= codes


def test_category_count_is_limited(repo: Path, tax: Taxonomy) -> None:
    policy = load_policy()
    issues = content.validate_meta(policy, tax, make_meta(categories=["Technology", "Personal", "Sustainability"]))
    assert any(i.code == "categories" and i.severity == "error" for i in issues)


def test_policy_rejects_alias_to_unknown_tag(repo: Path) -> None:
    path = repo / "data/taxonomy-policy.yaml"
    path.write_text(path.read_text().replace("k8s: Kubernetes", "k8s: Kubernetez"))
    with pytest.raises(PolicyError):
        load_policy()


def test_policy_rejects_unknown_keys(repo: Path) -> None:
    path = repo / "data/automation-policy.yaml"
    path.write_text(path.read_text() + "\nsurprise: true\n")
    with pytest.raises(PolicyError):
        load_policy()
