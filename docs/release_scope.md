# Public release boundary

This table describes the current public repository and its build archives.
"Public in Git" includes the current repository history.

| Material | Git source | Source archive | Wheel | Purpose and limit |
| --- | --- | --- | --- | --- |
| `src/ofag/`, `README.md`, `LICENSE`, `pyproject.toml` | Public | Public | Installed code | Framework implementation and installation contract. |
| `tests/`, `scripts/case*.py`, release and data-registration scripts | Public | Public | Excluded | Inspectable checks and case-stage code. Case scripts call services directly; their original runs did not pass the Agent audit gate. |
| `.github/workflows/` | Public | Excluded | Excluded | CI configuration remains inspectable in Git. |
| `examples/Fig*.ipynb` | Public | Excluded | Excluded | Computational figure-panel sources with cached output removed. They do not assemble the final manuscript figures. |
| `docs/case*.md`, `docs/reproducibility.md`, `docs/data_sources/`, `docs/validation.md`, `docs/case_audit*` | Public | Public | Case notes only | Provenance, run IDs, retrospective audit verdicts and limits. Manifests are filenames and citations, not the source measurements. The audit extract does not contain full run artifacts. |
| Agent procedure, `docs/knowledge/`, `docs/lessons/lessons.yaml` | Public | Public | Included | Runtime knowledge used in Agent briefs. Development-time lessons are labelled by origin; they are not independent discoveries by the finished Agent. |
| `docs/development/` case/design histories and benchmark task corpora; `scripts/development/` | Public, labelled as development | Public | Runtime histories and two task corpora included | Current retrieval and replay code reads some of these files; replay probes are source scripts. Their presence in an open repository prevents a blind evaluation using the same repository as an answer-free environment. |
| Detailed exploratory benchmark run reports (`local_private/benchmark_results/`) | Local only in the current checkout | Excluded | Excluded | Internal diagnostic logs from a small, partly contaminated evaluation. They are absent from the current repository history. |
| `paper/`, manuscript drafts, editable figure decks | Local only | Excluded | Excluded | Author working files. The manuscript is distributed through its submission route. |
| `data/`, `Result/`, `artifacts/`, `examples/Figure/` | Local only | Excluded | Excluded | External field data, derived inputs, complete project records, runs, and rendered panels. Their release needs a separate provenance and rights check. |
| `local_private/`, `.claude/`, `.venv/`, `.env*`, credentials, personal settings and third-party PDFs | Local only | Excluded | Excluded | Internal diagnostics, local tools, secrets and files with their own distribution terms. |

The publication check rejects local-only paths from the Git candidate list and
from both build archives. `.gitignore` is only the first guard: Git can track an
ignored file if it is explicitly forced into the index. The wheel bundles the
documents the installed Agent reads, while the source archive retains labelled
development records for inspection. Neither archive includes the manuscript,
field data, saved runs or final figure deck.

## Claims this release does not establish

- A fresh clone cannot currently regenerate all three field cases or the eight
  assembled manuscript figures from one command. Readers must obtain the source
  releases and prepare some derived inputs; final panel assembly is manual.
- The 19 saved runs received **retrospective** `ofag.audit` decisions. Five
  were vetoed. The original case scripts bypassed the Agent gate, and the
  existing Llano model was not rebuilt after those vetoes. The public audit
  extract cannot independently prove a verdict without the corresponding run
  artifacts and source data. See the [audit register](case_audit.md).
- The exploratory benchmark is not a controlled blind comparison. Its tasks
  and historical answers remain visible in this source repository. Detailed
  run reports are outside the current repository.

These evidence boundaries belong in the paper and repository description.
The public case notes retain poor fits, coverage limits and vetoed uses.

The source datasets remain at their original repositories. The USGS catalog
marks the [Llano](https://data.usgs.gov/datacatalog/data/USGS%3A59f0ad86e4b0220bbd9ade2d),
[Cedar Rapids ground](https://data.usgs.gov/datacatalog/data/USGS%3A5bc8ec12e4b0fc368ebfe4bb)
and [Cedar Rapids airborne](https://data.usgs.gov/datacatalog/data/USGS%3A5b1987ffe4b092d9652384b3)
releases as public-domain material, but this
does not itself license every related contractor report, external figure or
Utah FORGE resource under OFAG's MIT software license. Keep their bytes out of
this repository unless the terms for each item have been checked. The source
manifests provide identifiers and citations without redistributing those
files.

Before a public tag, compare the candidate commit, source archive and wheel
with this table. The current public repository began with a new root commit
that excludes earlier reports and notebook outputs.
