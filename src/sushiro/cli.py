"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from . import __version__, auth, keys, paths, shape
from .client import Api, ApiError


def _common() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir", help="config/token/state directory (default: auto)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--app-version", help="X-Miniapp-Version override")
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="sushiro",
        description="Read-only client for the Sushiro mini-program APIs.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"sushiro {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("cities", parents=[common], help="list serviced cities")

    stores = sub.add_parser("stores", parents=[common], help="list stores")
    stores.add_argument("--city", help="exact city name or substring")
    stores.add_argument("--open-only", action="store_true", help="only OPEN stores")
    stores.add_argument("--limit", type=int, default=0, help="max rows, 0 = all")

    store = sub.add_parser("store", parents=[common], help="one store by id")
    store.add_argument("store_id")

    slots = sub.add_parser("slots", parents=[common], help="reservation slots")
    slots.add_argument("--store", help="store id (default: config store_id)")
    slots.add_argument("--persons", type=int, default=0, help="number of people")
    slots.add_argument("--table-type", default="T")
    slots.add_argument("--date", help="single date, 2026-11-05 or 20261105")
    slots.add_argument("--days", type=int, help="horizon in days starting today")
    slots.add_argument("--all", action="store_true", help="show unavailable slots too")
    slots.add_argument("--raw", action="store_true", help="dump the raw API list")

    login = sub.add_parser("login", parents=[common], help="initialize endpoint probe")
    login.add_argument("--probe", action="store_true",
                       help="send a dummy js_code and report what the server says")
    login.add_argument("--js-code")
    login.add_argument("--device-id", default="")

    capture = sub.add_parser("capture", parents=[common], help="run the mitmproxy capture")
    capture.add_argument("--port", type=int, default=8888)
    capture.add_argument("--host", default="0.0.0.0")

    sub.add_parser("config", parents=[common], help="show resolved paths and token state")
    return parser


def _emit(payload, as_json: bool, text: str = "") -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text or json.dumps(payload, ensure_ascii=False, indent=2))


def _api(args) -> Api:
    cfg = auth.load_config()
    token = auth.read_token(cfg)
    app_version = args.app_version or cfg.get("app_version") or None
    if not token:
        raise SystemExit(
            "no auth_token. Capture one with `sushiro capture`, "
            f"or set ${auth.TOKEN_ENV}."
        )
    expiry = auth.token_expiry(token)
    if expiry and expiry <= datetime.now():
        raise SystemExit(
            f"auth_token expired at {expiry:%Y-%m-%d %H:%M:%S}. "
            "Refresh it: `sushiro capture` while opening the mini-program."
        )
    kwargs = {"app_version": app_version} if app_version else {}
    return Api(token, **kwargs)


def cmd_config(args) -> int:
    paths.bind(args.data_dir)
    cfg = auth.load_config()
    token = auth.read_token(cfg)
    expiry = auth.token_expiry(token) if token else None
    key_state = keys.status()
    info = {
        "root": str(paths.root()),
        "config": str(paths.config()),
        "token_present": bool(token),
        "token_expiry": expiry.isoformat(sep=" ", timespec="seconds") if expiry else None,
        "token_fresh": auth.is_fresh(token) if token else False,
        "store_id": cfg.get("store_id"),
        "sign_key": key_state["sign_key"],
        "aes_keys": key_state["aes_key"] and key_state["aes_iv"],
    }
    if args.json:
        _emit(info, True)
        return 0
    for key, value in info.items():
        print(f"{key:>14}: {value}")
    return 0


def cmd_cities(args) -> int:
    cities = _api(args).cities()
    if args.json:
        _emit(cities, True)
        return 0
    for city in cities:
        print(f"{city.get('city_id', '?'):>4}  {city.get('name')}")
    print(f"\n共 {len(cities)} 个城市", file=sys.stderr)
    return 0


def cmd_stores(args) -> int:
    stores = _api(args).stores()
    if args.city:
        needle = args.city.strip()
        stores = [
            s for s in stores
            if needle in str(s.get("name") or "") or needle in str(s.get("nameKana") or "")
        ]
    if args.open_only:
        stores = [s for s in stores if str(s.get("storeStatus", "")).upper() == "OPEN"]
    if args.limit:
        stores = stores[: args.limit]
    if args.json:
        _emit(stores, True)
        return 0
    for store in stores:
        print(shape.store_line(store))
    print(f"\n共 {len(stores)} 家门店", file=sys.stderr)
    return 0


def cmd_store(args) -> int:
    store = _api(args).store(args.store_id)
    if args.json:
        _emit(store, True)
        return 0
    print(shape.store_detail(store))
    return 0


def cmd_slots(args) -> int:
    cfg = auth.load_config()
    store_id = args.store or cfg.get("store_id")
    if not store_id:
        raise SystemExit("pass --store, or set store_id in config.json")
    persons = args.persons or int(cfg.get("numpersons") or 2)
    table_type = args.table_type or cfg.get("table_type") or "T"

    raw = _api(args).slots(store_id, persons, table_type)
    if args.raw:
        _emit(raw, args.json)
        return 0

    days = shape.group_by_day(raw)
    days = shape.filter_days(days, date=args.date, days_ahead=args.days)
    stats = shape.summarize(days)

    if args.json:
        _emit({
            "store_id": str(store_id),
            "persons": persons,
            **stats,
            "days": [
                {"date": day.date, "available": day.available, "total": day.total}
                for day in days
            ],
        }, True)
        return 0

    if not days:
        print(f"门店 {store_id}：该范围内没有排期")
        return 0
    first, last = days[0].date, days[-1].date
    print(f"门店 {store_id} · {first} → {last} · 可约 {stats['available']}/{stats['slots']} 段")
    print(shape.format_days(days, show_blocked=args.all))
    return 0


def cmd_login(args) -> int:
    if not args.probe and not args.js_code:
        print("use --probe to test with a dummy code, or --js-code to send a real one")
        return 2
    js_code = args.js_code or "0" * 32
    payload = Api().initialize(js_code, args.device_id)
    if args.json:
        _emit(payload, True)
        return 0
    status = payload.get("status")
    code = payload.get("error_code")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if str(status) == "1":
        print("\nstatus=1: a token was issued", file=sys.stderr)
    elif str(code) == "10":
        print("\nerror_code=10: signature accepted, js_code rejected (expected for a dummy code)",
              file=sys.stderr)
    elif str(code) == "101":
        print("\nerror_code=101: missing parameters", file=sys.stderr)
    return 0


def cmd_capture(args) -> int:
    from .capture import run

    return run(host=args.host, port=args.port, data_dir=args.data_dir)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    paths.bind(args.data_dir)
    handler = {
        "cities": cmd_cities,
        "stores": cmd_stores,
        "store": cmd_store,
        "slots": cmd_slots,
        "login": cmd_login,
        "capture": cmd_capture,
        "config": cmd_config,
    }[args.command]
    try:
        return handler(args)
    except (ApiError, keys.MissingKey) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
