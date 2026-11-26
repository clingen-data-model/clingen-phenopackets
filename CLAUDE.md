# CLAUDE.md — GCI to Phenopacket Pipeline

## Project Overview

This pipeline reads a ClinGen GCI snapshot (JSONL format) and produces GA4GH Phenopacket v2 JSON files — one per qualifying individual with HPO terms.

**Remote:** `github.com/bpow/genegraph-to-phenopacket`

## Key Files

| File | Purpose |
|---|---|
| `src/gci_phenopacket/cli.py` | Click CLI entry point, JSONL loop, output writing |
| `src/gci_phenopacket/transformer.py` | All GCI → Phenopacket field mapping logic; loads HPO + Mondo via oaklib sqlite adapter (auto-cached by oaklib) |
| `src/gci_phenopacket/allele_registry_client.py` | AlleleRegistryClient: ClinGen Allele Registry API fetch + persistent gzip-compressed JSON cache |
| `tests/test_gci_transformer.py` | Unit tests (across 4 test files under `tests/`) |
| `data/cache/allele_registry_cache.json.gz` | Persistent allele registry variant info cache (gzip-compressed JSON) |
| `pyproject.toml` | Package metadata and `gci-transform` entry point |
| `data/gci/` | Input JSONL snapshots |
| `scripts/combine_yaml.sh` | Concatenate all output JSON phenopackets into a single YAML stream (requires `yq` on PATH) |

## Running the Pipeline

```bash
# Full run (prompts for --input if omitted)
pixi run gci_transform

# With explicit input (output written to ./gci_phenopackets/{gene_symbol}/ subdirs)
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl

# Custom output directory
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl --output /path/to/output/

# Single record (0-based line index)
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl --record 0

# Control log verbosity (DEBUG, INFO, WARNING, ERROR)
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl --log-level DEBUG

# Preserve freetext disease terms instead of falling back to MONDO:0700096
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl --preserve-freetext

# Write all files flat into the output dir (no per-gene subdirectories)
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl --no-subdirs

# Pipe logs to a file
pixi run gci_transform --input data/gci/gci_snapshot_2026-03-11.jsonl > run.log

# Pipe JSONL from stdin (reads /dev/stdin, log level fixed at WARNING)
zcat gene_validity_raw.jsonl.gz | pixi run stdin
grep '"gene":"BRCA1"' data/gci/snapshot.jsonl | pixi run stdin

# Once installed as a package (from any directory)
pip install .
gci-transform --input /path/to/snapshot.jsonl
```

## Combining Output into YAML

`pixi run combine_yaml` concatenates every `*.json` under `gci_phenopackets/` into a
single multi-document YAML stream. It requires [`yq`](https://github.com/mikefarah/yq)
to be installed and on `PATH` (not managed by Pixi — install separately, e.g.
`brew install yq`).

## Running Tests

```bash
pixi run test
```

## Key Design Decisions

- Any individual with at least one HPO term is converted — `is_proband` status is not checked
- GCI stores HPO terms as `"Label (HP:XXXXXXX)"` — `extract_hpo_id()` strips the label before lookup
- `FREETEXT_` or missing disease IDs fall back to `MONDO:0700096` ("human disease")
- Vital status is only set when `ageType == "Death"` — omitted otherwise
- Evidence code: `ECO:0000304` ("author statement supported by traceable reference used in manual assertion")
- Variant IDs are prefixed: `caid:CA123` or `clinvar:789`
- Phenopacket ID format: `{gene_symbol}_{mondo_id}_{pmid}_{label_sanitized}_{individual_uuid}_{record_uuid}_{gdm_uuid}_{annotation_uuid}`
- `metadata.external_references` always contains `PMID:{pmid}` (with article title as description); when a provenance ID is present it is appended as a second entry (`gdm:...`); then one `PMID:{id}` entry per PMID in the **individual's own** `otherPMIDs` (built by `build_other_pmid_references()`), skipping the main PMID and duplicates. Entries may be plain PMID strings (no description) or embedded article dicts (title used as description); PubMed is never queried
- **`otherPMIDs` first iteration (caveat):** only the individual's own `otherPMIDs` are used. Family- and group-level `otherPMIDs` are intentionally skipped, since they describe the family/group rather than the individual, and `otherPMIDs` are added to `external_references` only, not to phenotype `evidence` (which still cites only the annotation PMID). Both choices are pending discussion; e.g. FANCE individual EUFA130's phenotypes actually come from its `otherPMIDs` paper (9147877), not the annotation paper (11001585)
- Output files are written to `{output_dir}/{gene_symbol}/{phenopacket_id}.json` by default; `--no-subdirs` / `-S` writes them flat into `{output_dir}/`
- Tag values: `individual` (direct), `family`, `group` — reflects nesting in the GCI annotation
- GENO zygosity terms are hardcoded in `GCI_ZYGOSITY_TO_GENO` (4 terms + fallback `GENO:0000137`); unknown values log a warning
- `iter_individuals(annotation)` yields `GCIIndividualContext` (fields: `individual`, `individual_id`, `group_id`, `family_id`) for all nesting levels
- ClinGen Allele Registry API (`https://reg.genome.network`) enriches `VariationDescriptor` with HGVS expressions, VCF record (GRCh38, from the gnomAD v4 id), xrefs, and gene confirmation; three-tier lookup: `carId` → `/allele/{carId}`, then `clinvarVariantId` → `/alleles?ClinVar.variationId={id}`, then GCI record fallback (`hgvsNames`, `dbSNPIds`); responses cached in `data/cache/allele_registry_cache.json.gz` (gzip-compressed)
- Gene context confirmed by matching `gene_symbol` against the gene list returned by the registry API (applies to both carId and clinvarVariantId lookup paths); falls back to string-match on `clinvarVariantTitle` when no API data available
- `VariantInterpretation.acmg_pathogenicity_classification` is **always** `NOT_PROVIDED` — do NOT populate it from ClinVar or any other source. The Phenopacket v2 spec cannot record the provenance of a pathogenicity classification, so filling this field would falsely present another group's ClinVar assertion as our own. Revisit only if the Phenopacket spec adds provenance metadata for this field.
- Ontologies (HP, Mondo only) are loaded in `GCITransformer.__init__` via oaklib's sqlite adapter (`sqlite:obo:hp`, `sqlite:obo:mondo`); oaklib manages download and caching automatically. Tests patch `gci_phenopacket.transformer.get_adapter` to inject mock adapters
- HP/Mondo `Resource.version` is read from the loaded ontology's `owl:versionIRI` release date (fallback `owl:versionInfo`) by `ontology_version()`; per-instance list in `GCITransformer.resources`. GENO/ECO have no version (hardcoded, not loaded). Pinnable versions via CLI are a wishlist item (see README)
- `--record N` jumps directly to line N via `itertools.islice` — does not scan the whole file

## Environment

- Package manager: [Pixi](https://pixi.sh)
- Python: 3.12
- Key dependencies: `phenopackets>=2.0.2.post5`, `oaklib`, `click`, `pytest`

## Conventions

- Do not auto-commit — always ask before committing
- Run all tests before committing any change
- Use `pixi run test` not bare `pytest`
- Update CLAUDE.md (Key Files table, Key Design Decisions) whenever files are moved, renamed, deleted, or their responsibilities change
