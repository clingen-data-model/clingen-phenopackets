from unittest.mock import MagicMock, patch
import pytest
from gci_phenopacket.transformer import GCITransformer, ontology_version


def _make_adapter(label_map=None):
    adapter = MagicMock()
    adapter.label.side_effect = lambda curie: (label_map or {}).get(curie)
    return adapter


def _make_transformer(hp_labels=None, mondo_labels=None):
    hp_adapter = _make_adapter(hp_labels)
    mondo_adapter = _make_adapter(mondo_labels)
    with patch("gci_phenopacket.transformer.get_adapter", side_effect=[hp_adapter, mondo_adapter]):
        t = GCITransformer()
    return t, hp_adapter


def test_hpo_to_labeled_phenotype_looks_up_by_id():
    t, hp_adapter = _make_transformer(hp_labels={"HP:0001250": "Seizure"})
    result = t.hpo_to_labeled_phenotype("HP:0001250")
    hp_adapter.label.assert_called_with("HP:0001250")
    assert result == ("HP:0001250", "Seizure")


def test_hpo_to_labeled_phenotype_returns_fallback_on_unknown_id():
    """Unknown HPO ID returns normalized id with 'Unknown Phenotype' label."""
    t, _ = _make_transformer(hp_labels={})
    result = t.hpo_to_labeled_phenotype("HP:9999999")
    assert result == ("HP:9999999", "Unknown Phenotype")


def _versioned_adapter(meta):
    adapter = MagicMock()
    adapter.ontologies.return_value = ["obo:x.owl"]
    adapter.ontology_metadata_map.return_value = meta
    return adapter


@pytest.mark.parametrize("meta,expected", [
    ({"owl:versionIRI": ["obo:hp/releases/2026-09-01/hp.owl"]}, "2026-09-01"),
    ({"owl:versionInfo": ["2026-09-01"]}, "2026-09-01"),
    ({}, None),
])
def test_ontology_version(meta, expected):
    assert ontology_version(_versioned_adapter(meta)) == expected


def test_resources_carry_loaded_ontology_versions():
    hp = _versioned_adapter({"owl:versionIRI": ["obo:hp/releases/2026-09-01/hp.owl"]})
    mondo = _versioned_adapter({"owl:versionIRI": ["obo:mondo/releases/2026-08-15/mondo.owl"]})
    with patch("gci_phenopacket.transformer.get_adapter", side_effect=[hp, mondo]):
        t = GCITransformer()
    versions = {r.id: r.version for r in t.resources}
    assert versions["hp"] == "2026-09-01"
    assert versions["mondo"] == "2026-08-15"
