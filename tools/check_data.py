"""Check the fake data files before tests or a deploy: python -m tools.check_data

Unit tests use their own small inputs, so a broken file in data/ (a typo in a price, a price list
nobody added to config.py, a product without a cost) would otherwise only show up in the demo.
Exit code 0 means every check passed; 1 means at least one problem was printed.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from quote_sim import config
from quote_sim.access import Role
from quote_sim.costs import load_cost_sheet
from quote_sim.evidence import PriceList, load_price_list
from quote_sim.pricing import ValidationError
from quote_sim.users import load_users

PRICE_LIST_GLOB = "price_list_*.json"


def check_data(
    data_directory: Path,
    listed_price_lists: Sequence[Path],
    users_file: Path,
    cost_sheet_file: Path,
) -> list[str]:
    """Return every problem found, instead of stopping at the first, so one run shows them all."""
    problems: list[str] = []
    price_lists = _check_price_lists(data_directory, listed_price_lists, problems)
    _check_users(users_file, problems)
    _check_costs(cost_sheet_file, price_lists, problems)
    return problems


def _check_price_lists(
    data_directory: Path,
    listed: Sequence[Path],
    problems: list[str],
) -> list[PriceList]:
    listed_resolved = [path.resolve() for path in listed]
    for path in sorted(data_directory.glob(PRICE_LIST_GLOB)):
        if path.resolve() not in listed_resolved:
            problems.append(f"{path.name} is not listed in config.PRICE_LIST_FILES")

    loaded: list[PriceList] = []
    seen_versions: set[str] = set()
    for path in listed:
        if not path.exists():
            problems.append(f"{path.name} is listed in config but does not exist")
            continue
        try:
            price_list = load_price_list(path)
        except ValidationError as error:
            problems.append(f"{path.name}: {error}")
            continue
        # price_list_v2.json must say "v2", so the file name can be trusted as evidence.
        expected_name = f"price_list_{price_list.version}.json"
        if path.name != expected_name:
            problems.append(
                f"{path.name} declares version {price_list.version!r}; rename it to {expected_name}"
            )
        if price_list.version in seen_versions:
            problems.append(f"{path.name} repeats version {price_list.version!r}")
        seen_versions.add(price_list.version)
        loaded.append(price_list)
    return loaded


def _check_users(users_file: Path, problems: list[str]) -> None:
    try:
        users = load_users(users_file)
    except ValidationError as error:
        problems.append(f"{users_file.name}: {error}")
        return
    present = {user.role for user in users.users}
    for role in Role:
        if role not in present:
            problems.append(f"{users_file.name} has no {role.value} user; the demo needs one")


def _check_costs(
    cost_sheet_file: Path,
    price_lists: Sequence[PriceList],
    problems: list[str],
) -> None:
    try:
        cost_sheet = load_cost_sheet(cost_sheet_file)
    except ValidationError as error:
        problems.append(f"{cost_sheet_file.name}: {error}")
        return
    if not price_lists:
        return
    # Only the newest list matters: older versions are kept as evidence, not sold from.
    latest = price_lists[-1]
    for product_id in latest.products:
        if cost_sheet.unit_cost(product_id) is None:
            problems.append(
                f"{cost_sheet_file.name} has no cost for {product_id} "
                f"(sold in {latest.version}); managers would see margin 'unknown'"
            )


def main() -> int:
    problems = check_data(
        config.DATA_DIRECTORY,
        config.PRICE_LIST_FILES,
        config.USERS_FILE,
        config.COST_SHEET_FILE,
    )
    if problems:
        print(f"Found {len(problems)} data problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"Data OK: {len(config.PRICE_LIST_FILES)} price lists, users, and cost sheet checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
