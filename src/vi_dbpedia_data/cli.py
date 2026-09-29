"""Command-line orchestration for the Member-1-only country data pipeline."""

import argparse
import json
import logging
from pathlib import Path

from vi_dbpedia_data.collect import collect, collect_reference
from vi_dbpedia_data.discover import discover, pilot_candidates
from vi_dbpedia_data.extract import process
from vi_dbpedia_data.inspect_infobox import inspect
from vi_dbpedia_data.models import CandidateCountry
from vi_dbpedia_data.reports import generate_reports, review_sample, review_summary
from vi_dbpedia_data.utils import ROOT, load_settings, read_json
from vi_dbpedia_data.validate import validate_dataset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vi-dbpedia-data", description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="Project root (for testing/relocation)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    reference = commands.add_parser("reference", help="Fetch exactly the five reference titles")
    reference.add_argument("--force", action="store_true")
    commands.add_parser("discover", help="Discover candidates via Wikidata")
    collection = commands.add_parser("collect", help="Collect discovered candidates")
    collection.add_argument("--limit", type=int)
    collection.add_argument("--force", action="store_true")
    inspection = commands.add_parser("inspect", help="Inspect selected raw pages")
    scope = inspection.add_mutually_exclusive_group()
    scope.add_argument("--reference-only", action="store_true")
    scope.add_argument("--all", action="store_true", help="All selected raw records (default)")
    for name in (
        "process",
        "validate",
        "report",
        "pilot",
        "full",
        "review-sample",
        "review-summary",
    ):
        commands.add_parser(name)
    return parser


def _print_counts(attempted: int, successful: int, location: str) -> None:
    print(
        f"attempted={attempted} successful={successful} "
        f"failed={attempted - successful} | {location}"
    )


def _collection_result(rows: list[dict], root: Path) -> None:
    success = sum(row["collection_status"] in {"collected", "skipped"} for row in rows)
    _print_counts(len(rows), success, str(root / "data/raw/collection_manifest.csv"))


def _finish(root: Path) -> None:
    inspection = inspect(load_settings(root), root)
    _print_counts(inspection["attempted"], inspection["selected"], str(root / "data/reports"))
    interim, records = process(load_settings(root), root)
    _print_counts(len(interim), len(records), str(root / "data/processed/countries.json"))
    results = validate_dataset(root)
    _print_counts(
        len(results),
        sum(row.status != "invalid" for row in results),
        str(root / "data/reports/validation.json"),
    )
    summary = generate_reports(root)
    print(f"report: {json.dumps(summary, ensure_ascii=False)} | {root / 'data/reports'}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = args.root
    settings = load_settings(root)
    if args.command == "reference":
        rows = collect_reference(settings, root, force=args.force)
        _collection_result(rows, root)
        print(f"reference index: {root / 'data/reference/pages.json'}")
    elif args.command == "discover":
        candidates = discover(settings, root)
        _print_counts(len(candidates), len(candidates), str(root / "data/candidates"))
    elif args.command == "collect":
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be positive")
        candidates = [
            CandidateCountry.model_validate(row)
            for row in read_json(root / "data/candidates/countries.json")
        ]
        rows = collect(candidates[: args.limit], settings, root, force=args.force)
        _collection_result(rows, root)
    elif args.command == "inspect":
        result = inspect(settings, root, reference_only=args.reference_only, all_available=args.all)
        _print_counts(result["attempted"], result["selected"], str(root / "data/reports"))
    elif args.command == "process":
        interim, records = process(settings, root)
        _print_counts(len(interim), len(records), str(root / "data/processed"))
    elif args.command == "validate":
        results = validate_dataset(root)
        _print_counts(
            len(results),
            sum(row.status != "invalid" for row in results),
            str(root / "data/reports/validation.json"),
        )
    elif args.command == "report":
        summary = generate_reports(root)
        _print_counts(
            summary["selected_count"], summary["processed_count"], str(root / "data/reports")
        )
        print(json.dumps(summary, ensure_ascii=False))
    elif args.command in {"pilot", "full"}:
        candidates = discover(settings, root)
        if args.command == "pilot":
            references = collect_reference(settings, root)
            _collection_result(references, root)
            reference_qids = {
                row["requested_title"]: qid
                for row in references
                if row["raw_file_path"]
                if (qid := read_json(root / row["raw_file_path"]).get("pageprops_wikidata_id"))
            }
            selected = pilot_candidates(candidates, settings, reference_qids)
        else:
            selected = candidates
        rows = collect(selected, settings, root)
        _collection_result(rows, root)
        _finish(root)
    elif args.command == "review-sample":
        rows = review_sample(root, seed=settings.pilot_seed, size=settings.pilot_size)
        _print_counts(len(rows), len(rows), str(root / "data/reports/manual_link_review.csv"))
    elif args.command == "review-summary":
        summary = review_summary(root)
        _print_counts(
            summary["reviewed_count"] + summary["unreviewed_count"],
            summary["reviewed_count"],
            str(root / "data/reports/manual_link_review.csv"),
        )
        print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
