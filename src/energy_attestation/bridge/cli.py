"""energy-bridge: put a real solar installation on attest.energy.

Keys are read from the environment, never from the config file:
  OWNER_PRIVATE_KEY     wallet that owns the watcher (used by `setup` only)
  ATTESTER_PRIVATE_KEY  wallet on the device that signs readings (`run`, `manual`)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from ..errors import ContractRevertError, EnergySDKError
from ..networks import get_network_config
from ..sdk import EnergySDK
from ..types import EnergyType, Network
from .runner import Bridge
from .sources import ManualSource, PowerIntegrationSource, SourceError, build_source

EXPLORERS = {
    Network.CELO: ("https://celo.easscan.org/attestation/view/", "https://celoscan.io/tx/"),
    Network.POLYGON: ("https://polygon.easscan.org/attestation/view/", "https://polygonscan.com/tx/"),
    Network.AMOY: ("https://polygon-amoy.easscan.org/attestation/view/", "https://amoy.polygonscan.com/tx/"),
}


def _key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"Set {name} in the environment (never put private keys in the config file).")
    return v


def _load_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    for k in ("network", "project_id", "source"):
        if k not in cfg:
            sys.exit(f"config {path} is missing '{k}'")
    cfg["_path"] = path
    return cfg


_OVERRIDES = ("registry_address", "schema_uid", "eas_address", "chain_id")


def _sdk(network: str, rpc_url, key_env: str, overrides: dict | None = None) -> EnergySDK:
    """Overrides let you point at a custom deployment (a fork or a local test chain)."""
    extra = {k: v for k, v in (overrides or {}).items() if k in _OVERRIDES and v}
    return EnergySDK.from_private_key(_key(key_env), network, rpc_url, **extra)


def _links(network: str, uid: str, tx: str) -> str:
    att, txu = EXPLORERS[Network(network)]
    return f"  attestation: {att}{uid}\n  transaction: {txu}{tx}"


def cmd_setup(a) -> None:
    overrides = json.load(open(a.deployment)) if a.deployment else {}
    owner = _sdk(a.network, a.rpc_url or overrides.get("rpc_url"), "OWNER_PRIVATE_KEY", overrides)
    attester = a.attester
    if not attester:
        if os.environ.get("ATTESTER_PRIVATE_KEY"):
            from eth_account import Account

            attester = Account.from_key(os.environ["ATTESTER_PRIVATE_KEY"]).address
        else:
            sys.exit("Pass --attester ADDRESS or set ATTESTER_PRIVATE_KEY so the device wallet can be authorized.")
    if a.watcher_id:
        watcher_id = int(a.watcher_id)
        print(f"Using existing watcher {watcher_id}")
    else:
        w = owner.watchers.create_watcher(a.watcher_name)
        watcher_id = w.watcher_id
        print(f"Watcher registered: #{watcher_id} {a.watcher_name} (tx {w.tx_hash})")
    p = owner.projects.create_project(watcher_id, a.project_name, EnergyType[a.energy_type.upper()])
    print(f"Project registered: #{p.project_id} {a.project_name} (tx {p.tx_hash})")
    if a.metadata_uri:
        owner.projects.set_project_metadata_uri(p.project_id, a.metadata_uri)
        print(f"Metadata set: {a.metadata_uri}")
    owner.attesters.add_attester(p.project_id, attester)
    print(f"Attester authorized: {attester}")
    print("\nPut this project_id in bridge.json:", p.project_id)


def _state_dir(path: str) -> str:
    return os.path.dirname(os.path.abspath(path))


def cmd_read(a) -> None:
    cfg = _load_config(a.config)
    src = build_source(cfg["source"], _state_dir(a.config))
    if isinstance(src, PowerIntegrationSource):
        w = src.read_power_w()
        print(f"PV power now: {w:.0f} W (this inverter is read by power integration, sampled every {src.sample_s:.0f}s)")
        print("Check this matches the PV watts on the inverter screen before running the bridge.")
        return
    wh = src.read_total_wh()
    print(f"Lifetime counter: {wh} Wh ({wh / 1000:.1f} kWh)")
    print("Check this matches the total energy figure on the inverter screen before running the bridge.")


def _bridge(cfg: dict, dry_run: bool) -> Bridge:
    sdk = _sdk(cfg["network"], cfg.get("rpc_url"), "ATTESTER_PRIVATE_KEY", cfg)
    if not sdk.read.is_project_attester(int(cfg["project_id"]), sdk.address):
        watcher = sdk.read.get_project_watcher_id(int(cfg["project_id"]))
        if not sdk.read.is_watcher_attester(watcher, sdk.address):
            sys.exit(f"{sdk.address} is not an authorized attester for project {cfg['project_id']}. Run `energy-bridge setup` first.")
    return Bridge(
        sdk,
        build_source(cfg["source"], _state_dir(cfg["_path"])),
        int(cfg["project_id"]),
        cfg.get("state_file", f"bridge-state-{cfg['project_id']}.json"),
        interval_hours=int(cfg.get("interval_hours", 1)),
        metadata_uri=cfg.get("metadata_uri", ""),
        dry_run=dry_run,
    )


def cmd_run(a) -> None:
    cfg = _load_config(a.config)
    bridge = _bridge(cfg, a.dry_run)
    if isinstance(bridge.source, PowerIntegrationSource) and (a.once or a.dry_run):
        sys.exit("This source integrates PV power continuously, so it needs `energy-bridge run` to keep running. Use `read` to test the connection.")
    if a.once or a.dry_run:
        r = bridge.tick()
        print(f"{r.action}: {r.detail}")
        if r.uid:
            print(_links(cfg["network"], r.uid, r.tx_hash))
        return
    bridge.run_forever(poll_s=int(cfg.get("poll_seconds", 300)))


def cmd_manual(a) -> None:
    cfg = _load_config(a.config)
    sdk = _sdk(cfg["network"], cfg.get("rpc_url"), "ATTESTER_PRIVATE_KEY", cfg)
    bridge = Bridge(
        sdk,
        ManualSource(a.total_kwh),
        int(cfg["project_id"]),
        cfg.get("state_file", f"bridge-state-{cfg['project_id']}.json"),
        interval_hours=int(cfg.get("interval_hours", 1)),
        metadata_uri=cfg.get("metadata_uri", ""),
    )
    r = bridge.tick()
    print(f"{r.action}: {r.detail}")
    if r.uid:
        print(_links(cfg["network"], r.uid, r.tx_hash))


def plan_estimate(now: int, tip: int, kw_readings, start: int | None = None, end: int | None = None) -> tuple:
    """Pick the period to estimate and the energy for it.

    Default: the period ends at the last whole hour and starts at the chain tip
    (or one hour earlier for a project with no readings yet).
    With start/end (whole minutes): a custom window, e.g. 09:30 to 10:30. The end
    must already be in the past, and once a project has readings the start must be
    the chain tip, because the record has to stay gapless.
    Energy = average of the PV kW figures read off the screen during that period x hours.
    Returns (from_ts, minutes, wh).
    """
    if not kw_readings:
        raise ValueError("give at least one PV kW reading")
    if any(k < 0 for k in kw_readings):
        raise ValueError("PV kW readings must not be negative")
    hm = lambda t: datetime.fromtimestamp(t).strftime("%H:%M")  # noqa: E731
    if start is None and end is None:
        end = now - now % 3600
        start = tip if tip > 0 else end - 3600
        if end - start < 3600:
            raise ValueError(f"no whole hour to estimate yet; try again after {hm(start + 3600)}")
    else:
        if end is None:
            end = now - now % 60
        if start is None:
            if tip <= 0:
                raise ValueError("give --start for a project with no readings yet")
            start = tip
        if tip > 0 and start != tip:
            raise ValueError(f"this project's record continues from {hm(tip)}, so --start must be {hm(tip)}")
        if end > now:
            raise ValueError(f"the period ends at {hm(end)}, which hasn't happened yet; run it after {hm(end)}")
        if end - start < 60:
            raise ValueError("the period must be at least one minute long and end after it starts")
    hours = (end - start) / 3600
    avg_kw = sum(kw_readings) / len(kw_readings)
    return start, (end - start) // 60, int(round(avg_kw * 1000 * hours))


def _today_at(hhmm: str, now: int) -> int:
    """Turn "09:30" into today's local timestamp."""
    try:
        h, m = (int(x) for x in hhmm.strip().split(":"))
    except ValueError as e:
        raise ValueError(f"time must look like 09:30, got {hhmm!r}") from e
    d = datetime.fromtimestamp(now).replace(hour=h, minute=m, second=0, microsecond=0)
    return int(d.timestamp())


def cmd_estimate(a) -> None:
    from ..types import AttestParams

    cfg = _load_config(a.config)
    sdk = _sdk(cfg["network"], cfg.get("rpc_url"), "ATTESTER_PRIVATE_KEY", cfg)
    pid = int(cfg["project_id"])
    tip = sdk.read.get_project_last_timestamp(pid)
    now = int(time.time())
    try:
        start = _today_at(a.start, now) if a.start else None
        end = _today_at(a.end, now) if a.end else None
        start, minutes, wh = plan_estimate(now, tip, a.kw, start, end)
    except ValueError as e:
        sys.exit(str(e))
    end = start + minutes * 60
    fmt = lambda t: datetime.fromtimestamp(t).strftime("%d %b %H:%M")  # noqa: E731
    print(f"Period:   {fmt(start)} to {fmt(end)} ({minutes // 60} h {minutes % 60} min)")
    print(f"Readings: {', '.join(f'{k:g}' for k in a.kw)} kW, average {sum(a.kw) / len(a.kw):.2f} kW")
    print(f"Estimate: {wh} Wh ({wh / 1000:.2f} kWh), recorded with method 'estimated'")
    print("Only confirm if these readings were taken from the screen during this period.")
    if not a.yes and input("Record it on chain? (y/N): ").strip().lower() != "y":
        print("Nothing sent.")
        return
    res = sdk.attestations.attest(
        AttestParams(pid, [wh], minutes, start, "estimated", cfg.get("metadata_uri", ""))
    )
    print("attested:", f"{wh} Wh")
    print(_links(cfg["network"], res.uid, res.tx_hash))


def cmd_status(a) -> None:
    cfg = _load_config(a.config)
    net = cfg["network"]
    from web3 import HTTPProvider, Web3

    from .._abi import ENERGY_REGISTRY_ABI

    nc = get_network_config(Network(net))
    w3 = Web3(HTTPProvider(cfg.get("rpc_url") or nc.default_rpc_url))
    reg = w3.eth.contract(address=Web3.to_checksum_address(cfg.get("registry_address") or nc.registry), abi=ENERGY_REGISTRY_ABI)
    pid = int(cfg["project_id"])
    p = reg.functions.getProject(pid).call()
    gen = reg.functions.getTotalGeneratedEnergy(pid).call()
    tip = reg.functions.getProjectLastTimestamp(pid).call()
    when = datetime.fromtimestamp(tip).strftime("%d %b %Y %H:%M (your local time)") if tip else "never"
    print(f"Project #{pid} {p[3]} (watcher #{p[0]}, registered={p[1]})")
    print(f"Total attested generation: {gen / 1000:.3f} kWh")
    print(f"Attested up to: {when}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="energy-bridge", description="Attest real solar output to attest.energy")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="register a watcher and project, authorize the device wallet")
    s.add_argument("--network", required=True, choices=[n.value for n in Network])
    s.add_argument("--rpc-url")
    s.add_argument("--watcher-name", default="My Solar")
    s.add_argument("--watcher-id", help="reuse an existing watcher instead of creating one")
    s.add_argument("--project-name", required=True)
    s.add_argument("--energy-type", default="solar_pv", choices=[e.name.lower() for e in EnergyType])
    s.add_argument("--attester", help="device wallet address (defaults to ATTESTER_PRIVATE_KEY's address)")
    s.add_argument("--metadata-uri", default="")
    s.add_argument("--deployment", help="JSON with registry_address, schema_uid, eas_address, chain_id for a custom deployment")
    s.set_defaults(fn=cmd_setup)

    r = sub.add_parser("read", help="read the inverter counter once, attest nothing")
    r.add_argument("config")
    r.set_defaults(fn=cmd_read)

    run = sub.add_parser("run", help="run the bridge loop")
    run.add_argument("config")
    run.add_argument("--once", action="store_true", help="one tick, then exit (for cron or systemd timers)")
    run.add_argument("--dry-run", action="store_true", help="show what would be attested, send nothing")
    run.set_defaults(fn=cmd_run)

    m = sub.add_parser("manual", help="record a reading typed from the inverter screen")
    m.add_argument("config")
    m.add_argument("--total-kwh", type=float, required=True, help="lifetime total kWh shown on the inverter")
    m.set_defaults(fn=cmd_manual)

    e = sub.add_parser("estimate", help="estimate the last whole hour from PV kW figures read off the screen")
    e.add_argument("config")
    e.add_argument("--kw", type=float, nargs="+", required=True, help="PV power readings in kW taken during that hour, e.g. --kw 1.40 1.52 1.35")
    e.add_argument("--start", help="custom start time today, e.g. 09:30 (first reading only; later ones continue from the record)")
    e.add_argument("--end", help="custom end time today, e.g. 10:30 (must already have passed)")
    e.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    e.set_defaults(fn=cmd_estimate)

    st = sub.add_parser("status", help="show what is on chain for the project")
    st.add_argument("config")
    st.set_defaults(fn=cmd_status)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        a.fn(a)
    except ContractRevertError as e:
        sys.exit(f"Contract reverted: {e.error_name} {e.error_args}")
    except (EnergySDKError, SourceError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
