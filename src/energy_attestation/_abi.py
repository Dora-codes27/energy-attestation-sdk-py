"""Contract ABIs, copied from energy-attestation-sdk (JS) v1.2.0."""

import json
from importlib import resources


def _load(name: str) -> list:
    return json.loads(resources.files(__package__).joinpath("abi", f"{name}.json").read_text())


EAS_ABI = _load("EAS")
ENERGY_REGISTRY_ABI = _load("EnergyRegistry")
ENERGY_ATTESTATION_RESOLVER_ABI = _load("EnergyAttestationResolver")
