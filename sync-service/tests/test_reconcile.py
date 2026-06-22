"""Tests for the reconcile orchestration and credential Secret provisioning."""

from __future__ import annotations

import pytest

from kaos_sync.config import Settings
from kaos_sync.main import run_once
from kaos_sync.projection import project
from kaos_sync.reconcile import credential_secret_name, reconcile


class FakeAIB:
    """In-memory AIB admin double with create-or-get idempotency and credential minting."""

    def __init__(self):
        self.collections: dict[str, dict[str, dict]] = {}
        self.mint_calls: list[str] = []
        self.revoke_calls: list[str] = []
        self.delete_calls: list[tuple[str, str]] = []
        self._next = 0

    def _by_id(self, collection: str) -> dict[str, dict]:
        return {item["id"]: item for item in self.collections.get(collection, {}).values()}

    def list(self, collection):
        return [dict(item, id=item["id"]) for item in self.collections.get(collection, {}).values()]

    def get(self, collection, resource_id):
        return self._by_id(collection).get(resource_id)

    def create_or_get(self, collection, match_field, match_value, body):
        store = self.collections.setdefault(collection, {})
        if match_value in store:
            return store[match_value]["id"]
        self._next += 1
        item_id = f"{collection}-{self._next}"
        store[match_value] = {"id": item_id, match_field: match_value, "body": body}
        return item_id

    def delete(self, collection, resource_id):
        self.delete_calls.append((collection, resource_id))
        store = self.collections.get(collection, {})
        for key, item in list(store.items()):
            if item["id"] == resource_id:
                del store[key]
                return True
        return False

    def mint_credentials(self, agent_id):
        self.mint_calls.append(agent_id)
        return {"client_id": f"cid-{agent_id}", "client_secret": f"secret-{agent_id}"}

    def revoke_credentials(self, agent_id):
        self.revoke_calls.append(agent_id)
        return True


class FakeSecrets:
    def __init__(self):
        self.store: dict[tuple[str, str], dict[str, str]] = {}

    def get(self, namespace, name):
        return self.store.get((namespace, name))

    def upsert(self, namespace, name, string_data):
        self.store[(namespace, name)] = dict(string_data)

    def list(self, namespaces):
        if not namespaces:
            return list(self.store.keys())
        return [(ns, name) for (ns, name) in self.store if ns in namespaces]

    def delete(self, namespace, name):
        return self.store.pop((namespace, name), None) is not None


class FakeLister:
    def __init__(self, resources):
        self._resources = resources

    def list_resources(self, namespaces):
        return self._resources


def _mcpserver(name, namespace="demo"):
    return {"kind": "MCPServer", "metadata": {"name": name, "namespace": namespace}}


def _agent(name, mcp_servers, namespace="demo"):
    return {
        "kind": "Agent",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"mcpServers": mcp_servers},
    }


def test_credential_secret_name():
    assert credential_secret_name("kaos-aib", "researcher") == "kaos-aib-researcher"


def test_reconcile_creates_records_and_secret():
    desired = project([_mcpserver("github"), _agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()

    summary = reconcile(desired, aib, secrets, "kaos-aib")

    assert summary.services == 1
    assert summary.permission_sets == 1
    assert len(summary.agents) == 1

    agent = summary.agents[0]
    assert agent.external_id == "kaos://agent/demo/researcher"
    assert agent.secret_namespace == "demo"
    assert agent.secret_name == "kaos-aib-researcher"
    assert agent.credentials_minted is True

    stored = secrets.get("demo", "kaos-aib-researcher")
    assert stored == {
        "client_id": f"cid-{agent.agent_id}",
        "client_secret": f"secret-{agent.agent_id}",
    }


def test_reconcile_binds_agent_to_permission_sets():
    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(desired, aib, secrets)

    agent_body = aib.collections["agents"]["kaos://agent/demo/researcher"]["body"]
    bound_ids = [p["permission_set_id"] for p in agent_body["permission_sets"]]
    ps_id = aib.collections["permission-sets"]["kaos:mcpserver:demo:github:call"]["id"]
    assert bound_ids == [ps_id]
    assert "client_id" not in agent_body


def test_reconcile_is_idempotent_and_does_not_remint():
    desired = project([_mcpserver("github"), _agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()

    first = reconcile(desired, aib, secrets)
    assert first.agents[0].credentials_minted is True
    assert aib.mint_calls  # minted once

    second = reconcile(desired, aib, secrets)
    assert second.services == 1
    assert second.permission_sets == 1
    assert second.agents[0].credentials_minted is False
    assert len(aib.mint_calls) == 1  # not minted again


def test_reconcile_remints_when_secret_missing_credentials():
    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()
    # Secret exists but is empty/incomplete -> credentials must be (re)minted.
    secrets.upsert("demo", "kaos-aib-researcher", {})

    summary = reconcile(desired, aib, secrets)
    assert summary.agents[0].credentials_minted is True
    assert secrets.get("demo", "kaos-aib-researcher")["client_id"]


def test_run_once_projects_and_reconciles():
    resources = [_mcpserver("github"), _mcpserver("slack"), _agent("researcher", ["github"])]
    aib, secrets = FakeAIB(), FakeSecrets()
    summary = run_once(Settings(), FakeLister(resources), aib, secrets)

    # github + slack become services; only the github edge is granted.
    assert summary.services == 2
    assert summary.permission_sets == 1
    assert summary.agents[0].secret_name == "kaos-aib-researcher"


def test_reconcile_does_not_prune_by_default():
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(project([_agent("a", ["github"]), _agent("b", ["slack"])]), aib, secrets, "kaos-aib")

    # Re-reconcile a shrunk desired state without prune: orphans must remain.
    summary = reconcile(project([_agent("a", ["github"])]), aib, secrets, "kaos-aib")

    assert summary.pruned.agents == 0
    assert secrets.get("demo", "kaos-aib-b") is not None
    assert any(i["display_name"] == "kaos://agent/demo/b" for i in aib.list("agents"))


def test_reconcile_prunes_orphaned_records_and_secrets():
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(project([_agent("a", ["github"]), _agent("b", ["slack"])]), aib, secrets, "kaos-aib")
    b_agent_id = aib.collections["agents"]["kaos://agent/demo/b"]["id"]

    summary = reconcile(project([_agent("a", ["github"])]), aib, secrets, "kaos-aib", prune=True)

    # Agent b plus its slack permission set, slack service and credential Secret are removed.
    assert summary.pruned.agents == 1
    assert summary.pruned.permission_sets == 1
    assert summary.pruned.services == 1
    assert summary.pruned.secrets == 1
    assert b_agent_id in aib.revoke_calls

    # Agent a and its records remain intact.
    assert secrets.get("demo", "kaos-aib-a") is not None
    assert secrets.get("demo", "kaos-aib-b") is None
    remaining_agents = {i["display_name"] for i in aib.list("agents")}
    assert remaining_agents == {"kaos://agent/demo/a"}
    remaining_services = {i["client_id"] for i in aib.list("services")}
    assert remaining_services == {"kaos-mcpserver-demo-github"}


def test_prune_leaves_externally_managed_records_untouched():
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(project([_agent("a", ["github"])]), aib, secrets, "kaos-aib")
    # Inject broker records owned by something other than KAOS.
    aib.collections["agents"]["ext"] = {"id": "ext-agent", "display_name": "external-agent"}
    aib.collections["services"]["ext"] = {"id": "ext-svc", "client_id": "vendor-service"}
    aib.collections["permission-sets"]["ext"] = {"id": "ext-ps", "name": "vendor:ps"}

    # Prune against an empty desired state: only KAOS-owned records should go.
    reconcile(project([]), aib, secrets, "kaos-aib", prune=True)

    assert aib.get("agents", "ext-agent") is not None
    assert aib.get("services", "ext-svc") is not None
    assert aib.get("permission-sets", "ext-ps") is not None
    assert "ext-agent" not in aib.revoke_calls
    # The KAOS-owned agent a was pruned.
    assert all(i["display_name"] != "kaos://agent/demo/a" for i in aib.list("agents"))
