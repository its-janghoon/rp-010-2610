# Replication package

Anonymous package for the submission *Most of the LLM Routing Gap Is Task Type*.
Every number in the paper is a macro resolved from one of the two JSON files in
`reports/`, and both are recomputed from `results/` by the two scripts named
below. Nothing has to be trained, and nothing has to be re-executed, to check any
figure in the paper.

## What maps to what

| Paper | Artifact |
| --- | --- |
| the 294 queries, 7 task types x 3 languages | `data/queries_294.jsonl`; rebuilt by `scripts/build_queries.py` from the pinned items and `data/translation_cache.jsonl` |
| the executed 14 x 294 matrix, both runs | `results/phase2/<model>/labels.jsonl`, `results/replicate1/<model>/labels.jsonl` |
| run-to-run movement, and the both-run rule | `scripts/compute_replicate_gate.py` -> `reports/replicate1_gate.json` |
| the seven scoring variants, oracle and best single | same file, `variants` |
| the task-type and task-type-by-language decomposition | `scripts/compute_static_lookup_pareto.py` -> `reports/static_lookup_pareto.json` |
| the 21-cell static lookup, and its cost | same file, `lookup`; flat in `reports/static_lookup_21.csv` |
| the qid ledger and the hash the appendix prints | `reports/final_qid_98.txt`, hashed into `static_lookup_pareto.json` |
| the lookup table's "basis" column | `scripts/analyze_coding_cell_hold.py` -> `reports/coding_cell_hold.json` |
| the three infrastructure failures excluded from the scored keys | `reports/replicate1_gate.md` |
| the model pool, prices, caps and bucket sizes | `config/config.yaml` |
| scoring, per task type | `eval/`, with the checkers' unit tests beside them |

## Recomputing the two result files

From the package root, with `results/` and `data/` in place:

    python3 scripts/compute_replicate_gate.py
    python3 scripts/compute_static_lookup_pareto.py
    python3 scripts/analyze_coding_cell_hold.py

They read only the stored labels, so they need no API key and no network. The
checkers' tests run with `python3 -m pytest eval/`.

## Re-executing the matrix

`scripts/run_pilot.py` is the harness that produced `results/`. Re-running it
needs a gateway API key, which is not in this package, and the prices and model
catalogue are pinned to one snapshot (see the paper's appendices on timestamps
and identifiers). Set `OPENROUTER_API_KEY` in the environment; the key-file path
in the source was replaced with `$OPENROUTER_KEY_FILE` so it names no machine.

Re-execution is also not expected to reproduce the labels exactly, and that is
one of the paper's own measurements: running the whole matrix twice, changing
nothing, scored 5.37% of the 4,116 model-question pairs differently.

## Paths and identifiers

Absolute paths were replaced with environment variables (`$HOME`, `$PKG`,
`$PAPERS`, `$HF_HOME`, `$WORK`, `$OPENROUTER_KEY_FILE`) so nothing points at the
machine the measurements were taken on, and the request header that named a
project repository was replaced with a placeholder. The GitHub URLs that remain
are upstream dataset provenance -- gorilla/BFCL and LiveCodeBench -- which the
paper cites and a reviewer should be able to follow.

## What is deliberately absent

The translation-verification pilots, the cost probe and the stage-review helper
are not here. They produced setup reports rather than any number in the paper's
tables, and the translation inputs they operated on -- the cache and the four
manifests -- are included, so the query construction is still checkable end to
end.

## License

To be released under a permissive license on publication.
