"""EnergyQuery: read indexed data from the Energy Attestation subgraph. No wallet needed."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

import requests

from .errors import ConfigurationError, EnergySDKError
from .networks import get_network_config
from .types import Network, PageResult

_WATCHER_FIELDS = "id name owner registered totalGeneratedWh totalConsumedWh projectCount createdAt createdAtBlock"
_PROJECT_FIELDS = (
    "id name registered totalGeneratedWh totalConsumedWh lastToTimestamp metadataURI "
    "attestationCount createdAt createdAtBlock watcher { id name } energyType { id name }"
)
_ATTESTATION_FIELDS = (
    "id fromTimestamp toTimestamp energyWh attester metadataURI readings replaced "
    "replacedBy { id } replaces { id } blockTimestamp blockNumber txHash "
    "project { id name } energyType { id name }"
)


class SubgraphError(EnergySDKError):
    pass


class EnergyQuery:
    """Query the subgraph for listings, filters and time series.

    Big numbers (Wh totals, timestamps) come back as strings, exactly as the
    subgraph returns them. Wrap with int() for arithmetic.
    """

    def __init__(
        self,
        network: Network | str,
        api_key: Optional[str] = None,
        subgraph_url: Optional[str] = None,
        timeout_s: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        cfg = get_network_config(Network(network))
        url = subgraph_url or cfg.subgraph_url
        if not url:
            raise ConfigurationError(f"No subgraph URL for {network}; pass subgraph_url")
        self.url = url
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def _query(self, gql: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        m = re.search(r"query\s+(\w+)", gql)
        name = m.group(1) if m else "unknown"
        try:
            resp = self.session.post(
                self.url, json={"query": gql, "variables": variables or {}}, headers=self.headers, timeout=self.timeout_s
            )
        except requests.RequestException as e:
            raise SubgraphError(f"Subgraph request failed (query: {name}): {e}") from e
        if not resp.ok:
            raise SubgraphError(f"Subgraph HTTP {resp.status_code} for query {name}: {resp.reason}")
        body = resp.json()
        if body.get("errors"):
            raise SubgraphError(f"Subgraph query error ({name}): " + ", ".join(e.get("message", "") for e in body["errors"]))
        if not body.get("data"):
            raise SubgraphError(f"Subgraph returned empty data for query {name}")
        return body["data"]

    @staticmethod
    def _page(items: list, first: int) -> PageResult:
        has_more = len(items) > first
        return PageResult(items=items[:first] if has_more else items, has_more=has_more)

    # Protocol -------------------------------------------------------------

    def get_protocol(self) -> Optional[dict]:
        data = self._query(
            '{ protocol(id: "protocol") { totalWatchers totalProjects totalAttestations '
            "totalGeneratedWh totalConsumedWh energyTypeAdmin } }"
        )
        return data.get("protocol")

    def get_energy_types(self) -> List[dict]:
        data = self._query("{ energyTypes(first: 50, orderBy: id, orderDirection: asc) { id name registered totalGeneratedWh } }")
        return data["energyTypes"]

    # Watchers -------------------------------------------------------------

    def get_watcher(self, watcher_id: str) -> Optional[dict]:
        data = self._query(
            f"""query GetWatcher($id: ID!) {{
              watcher(id: $id) {{
                {_WATCHER_FIELDS}
                projects(first: 100, orderBy: createdAt, orderDirection: asc) {{
                  id name registered totalGeneratedWh totalConsumedWh lastToTimestamp metadataURI attestationCount energyType {{ id name }}
                }}
                watcherAttesters(first: 100) {{ id attester active addedAt addedAtBlock }}
                ownershipHistory(orderBy: timestamp, orderDirection: asc) {{ id previousOwner newOwner timestamp blockNumber txHash }}
              }}
            }}""",
            {"id": str(watcher_id)},
        )
        return data.get("watcher")

    def get_watchers(
        self,
        first: int = 100,
        skip: int = 0,
        order_by: str = "createdAt",
        order_direction: str = "desc",
        registered: Optional[bool] = None,
        owner: Optional[str] = None,
    ) -> PageResult:
        where: Dict[str, Any] = {}
        if registered is not None:
            where["registered"] = registered
        if owner:
            where["owner"] = owner.lower()
        data = self._query(
            f"""query GetWatchers($first: Int, $skip: Int, $orderBy: Watcher_orderBy, $orderDirection: OrderDirection, $where: Watcher_filter) {{
              watchers(first: $first, skip: $skip, orderBy: $orderBy, orderDirection: $orderDirection, where: $where) {{ {_WATCHER_FIELDS} }}
            }}""",
            {"first": first + 1, "skip": skip, "orderBy": order_by, "orderDirection": order_direction, "where": where},
        )
        return self._page(data["watchers"], first)

    def iterate_watchers(self, first: int = 100, **filters) -> Iterator[dict]:
        skip = 0
        while True:
            page = self.get_watchers(first=first, skip=skip, **filters)
            yield from page.items
            if not page.has_more:
                return
            skip += first

    def get_watcher_ownership_history(self, watcher_id: str) -> List[dict]:
        data = self._query(
            """query GetOwnershipHistory($watcherId: String!) {
              watcherOwnershipTransfers(where: { watcher: $watcherId }, orderBy: timestamp, orderDirection: asc) {
                id previousOwner newOwner timestamp blockNumber txHash watcher { id name }
              }
            }""",
            {"watcherId": str(watcher_id)},
        )
        return data["watcherOwnershipTransfers"]

    # Projects -------------------------------------------------------------

    def get_project(self, project_id: str) -> Optional[dict]:
        data = self._query(
            f"query GetProject($id: ID!) {{ project(id: $id) {{ {_PROJECT_FIELDS} }} }}", {"id": str(project_id)}
        )
        return data.get("project")

    def get_projects(
        self,
        first: int = 100,
        skip: int = 0,
        order_by: str = "createdAt",
        order_direction: str = "desc",
        watcher_id: Optional[str] = None,
        energy_type_id: Optional[str] = None,
        registered: Optional[bool] = None,
    ) -> PageResult:
        where: Dict[str, Any] = {}
        if watcher_id is not None:
            where["watcher"] = str(watcher_id)
        if registered is not None:
            where["registered"] = registered
        if energy_type_id is not None:
            # consumer projects carry a null energyType in the subgraph
            where["energyType"] = None if str(energy_type_id) == "0" else str(energy_type_id)
        data = self._query(
            f"""query GetProjects($first: Int, $skip: Int, $orderBy: Project_orderBy, $orderDirection: OrderDirection, $where: Project_filter) {{
              projects(first: $first, skip: $skip, orderBy: $orderBy, orderDirection: $orderDirection, where: $where) {{ {_PROJECT_FIELDS} }}
            }}""",
            {"first": first + 1, "skip": skip, "orderBy": order_by, "orderDirection": order_direction, "where": where},
        )
        return self._page(data["projects"], first)

    def iterate_projects(self, first: int = 100, **filters) -> Iterator[dict]:
        skip = 0
        while True:
            page = self.get_projects(first=first, skip=skip, **filters)
            yield from page.items
            if not page.has_more:
                return
            skip += first

    # Attestations ---------------------------------------------------------

    def get_attestation(self, uid: str) -> Optional[dict]:
        data = self._query(
            f"query GetAttestation($id: ID!) {{ energyAttestation(id: $id) {{ {_ATTESTATION_FIELDS} }} }}",
            {"id": uid},
        )
        return data.get("energyAttestation")

    def get_attestations(
        self,
        first: int = 100,
        skip: int = 0,
        order_by: str = "fromTimestamp",
        order_direction: str = "asc",
        project_id: Optional[str] = None,
        project_ids: Optional[Sequence[str]] = None,
        attester: Optional[str] = None,
        replaced: Optional[bool] = None,
        from_timestamp_gte: Optional[str] = None,
        from_timestamp_lte: Optional[str] = None,
        to_timestamp_gte: Optional[str] = None,
        to_timestamp_lte: Optional[str] = None,
        energy_type_id: Optional[str] = None,
    ) -> PageResult:
        where: Dict[str, Any] = {}
        if project_id is not None:
            where["project"] = str(project_id)
        elif project_ids is not None:
            where["project_in"] = [str(p) for p in project_ids]
        if attester:
            where["attester"] = attester.lower()
        if replaced is not None:
            where["replaced"] = replaced
        for key, val in (
            ("fromTimestamp_gte", from_timestamp_gte),
            ("fromTimestamp_lte", from_timestamp_lte),
            ("toTimestamp_gte", to_timestamp_gte),
            ("toTimestamp_lte", to_timestamp_lte),
        ):
            if val:
                where[key] = str(val)
        if energy_type_id is not None:
            where["energyType"] = None if str(energy_type_id) == "0" else str(energy_type_id)
        data = self._query(
            f"""query GetAttestations($first: Int, $skip: Int, $orderBy: EnergyAttestation_orderBy, $orderDirection: OrderDirection, $where: EnergyAttestation_filter) {{
              energyAttestations(first: $first, skip: $skip, orderBy: $orderBy, orderDirection: $orderDirection, where: $where) {{ {_ATTESTATION_FIELDS} }}
            }}""",
            {"first": first + 1, "skip": skip, "orderBy": order_by, "orderDirection": order_direction, "where": where},
        )
        return self._page(data["energyAttestations"], first)

    def iterate_attestations(self, first: int = 100, **filters) -> Iterator[dict]:
        skip = 0
        while True:
            page = self.get_attestations(first=first, skip=skip, **filters)
            yield from page.items
            if not page.has_more:
                return
            skip += first

    # Daily snapshots ------------------------------------------------------

    def get_daily_snapshots(
        self,
        project_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        first: int = 365,
        skip: int = 0,
        order_direction: str = "asc",
    ) -> List[dict]:
        where: Dict[str, Any] = {}
        if project_id is not None:
            where["project"] = str(project_id)
        if date_from:
            where["date_gte"] = date_from
        if date_to:
            where["date_lte"] = date_to
        data = self._query(
            """query GetDailySnapshots($first: Int, $skip: Int, $orderDirection: OrderDirection, $where: DailyEnergySnapshot_filter) {
              dailyEnergySnapshots(first: $first, skip: $skip, orderBy: date, orderDirection: $orderDirection, where: $where) {
                id date timestamp generatedWh consumedWh attestationCount project { id name }
              }
            }""",
            {"first": first, "skip": skip, "orderDirection": order_direction, "where": where},
        )
        return data["dailyEnergySnapshots"]

    def iterate_daily_snapshots(self, first: int = 365, **filters) -> Iterator[dict]:
        skip = 0
        while True:
            items = self.get_daily_snapshots(first=first + 1, skip=skip, **filters)
            has_more = len(items) > first
            yield from (items[:first] if has_more else items)
            if not has_more:
                return
            skip += first

    # Attesters ------------------------------------------------------------

    def get_project_attesters(
        self, project_id: Union[str, Sequence[str]], first: int = 100, skip: int = 0, active: Optional[bool] = None
    ) -> List[dict]:
        if isinstance(project_id, (list, tuple)):
            where: Dict[str, Any] = {"project_in": [str(p) for p in project_id]}
        else:
            where = {"project": str(project_id)}
        if active is not None:
            where["active"] = active
        data = self._query(
            """query GetProjectAttesters($first: Int, $skip: Int, $where: ProjectAttester_filter) {
              projectAttesters(first: $first, skip: $skip, where: $where) { id attester active addedAt addedAtBlock project { id name } }
            }""",
            {"first": first, "skip": skip, "where": where},
        )
        return data["projectAttesters"]

    def get_watcher_attesters(
        self, watcher_id: str, first: int = 100, skip: int = 0, active: Optional[bool] = None
    ) -> List[dict]:
        where: Dict[str, Any] = {"watcher": str(watcher_id)}
        if active is not None:
            where["active"] = active
        data = self._query(
            """query GetWatcherAttesters($first: Int, $skip: Int, $where: WatcherAttester_filter) {
              watcherAttesters(first: $first, skip: $skip, where: $where) { id attester active addedAt addedAtBlock watcher { id name } }
            }""",
            {"first": first, "skip": skip, "where": where},
        )
        return data["watcherAttesters"]
