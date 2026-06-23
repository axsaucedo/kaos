"""Tests for the reconcile orchestration and credential Secret provisioning."""

from __future__ import annotations

import pytest

from kaos_sync.config import Settings
from kaos_sync.main import run_once
from kaos_sync.projection import project
from kaos_sync.reconcile import ProblemCategory, credential_secret_name, reconcile


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
        self.annotations: dict[tuple[str, str], dict[str, str]] = {}

    def get(self, namespace, name):
        return self.store.get((namespace, name))

    def upsert(self, namespace, name, string_data, annotations=None):
        self.store[(namespace, name)] = dict(string_data)
        if annotations is not None:
            self.annotations[(namespace, name)] = dict(annotations)

    def get_annotation(self, namespace, name, key):
        return self.annotations.get((namespace, name), {}).get(key)

    def list(self, namespaces):
        if not namespaces:
            return list(self.store.keys())
        return [(ns, name) for (ns, name) in self.store if ns in namespaces]

    def delete(self, namespace, name):
        self.annotations.pop((namespace, name), None)
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


def test_mint_stamps_rotation_annotation():
    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()

    reconcile(desired, aib, secrets)

    from kaos_sync.reconcile import CREDENTIAL_ROTATED_AT_ANNOTATION

    stamp = secrets.get_annotation("demo", "kaos-aib-researcher", CREDENTIAL_ROTATED_AT_ANNOTATION)
    assert stamp  # mint records when the credential was issued


def test_reconcile_rotates_a_stale_credential():
    from kaos_sync.reconcile import CREDENTIAL_ROTATED_AT_ANNOTATION

    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(desired, aib, secrets)
    assert len(aib.mint_calls) == 1

    # Backdate the rotation stamp so the credential is past its rotation interval.
    secrets.annotations[("demo", "kaos-aib-researcher")][
        CREDENTIAL_ROTATED_AT_ANNOTATION
    ] = "2000-01-01T00:00:00+00:00"

    summary = reconcile(desired, aib, secrets, credential_rotation_seconds=1)
    agent = summary.agents[0]
    assert agent.credentials_rotated is True
    assert agent.credentials_minted is False
    assert len(aib.mint_calls) == 2  # re-minted for rotation
    refreshed = secrets.get_annotation(
        "demo", "kaos-aib-researcher", CREDENTIAL_ROTATED_AT_ANNOTATION
    )
    assert refreshed != "2000-01-01T00:00:00+00:00"


def test_reconcile_does_not_rotate_a_fresh_credential():
    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(desired, aib, secrets)

    summary = reconcile(desired, aib, secrets, credential_rotation_seconds=3600)
    assert summary.agents[0].credentials_rotated is False
    assert len(aib.mint_calls) == 1  # still fresh, no re-mint


def test_rotation_disabled_by_default_ignores_stale_credentials():
    from kaos_sync.reconcile import CREDENTIAL_ROTATED_AT_ANNOTATION

    desired = project([_agent("researcher", ["github"])])
    aib, secrets = FakeAIB(), FakeSecrets()
    reconcile(desired, aib, secrets)
    secrets.annotations[("demo", "kaos-aib-researcher")][
        CREDENTIAL_ROTATED_AT_ANNOTATION
    ] = "2000-01-01T00:00:00+00:00"

    summary = reconcile(desired, aib, secrets)  # credential_rotation_seconds defaults to 0
    assert summary.agents[0].credentials_rotated is False
    assert len(aib.mint_calls) == 1


def test_run_once_projects_and_reconciles():
    resources = [_mcpserver("github"), _mcpserver("slack"), _agent("researcher", ["github"])]
    aib, secrets = FakeAIB(), FakeSecrets()
    summary = run_once(Settings(), FakeLister(resources), aib, secrets)

    # github + slack become services; only the github edge is granted.
    assert summary.services == 2
    assert summary.permission_sets == 1
    assert summary.agents[0].secret_name == "kaos-aib-researcher"


class FakeStatusWriter:
    def __init__(self):
        self.patches: list[tuple[str, str, str, dict]] = []

    def patch_annotations(self, kind, namespace, name, annotations):
        self.patches.append((kind, namespace, name, dict(annotations)))
        return True


def test_run_once_writes_back_sync_annotations():
    from kaos_sync.reconcile import (
        AIB_EXTERNAL_ID_ANNOTATION,
        AIB_SYNC_STATUS_ANNOTATION,
        AIB_SYNCED_AT_ANNOTATION,
    )

    resources = [_mcpserver("github"), _agent("researcher", ["github"])]
    aib, secrets, writer = FakeAIB(), FakeSecrets(), FakeStatusWriter()

    run_once(Settings(), FakeLister(resources), aib, secrets, writer)

    patched = {(kind, name): ann for kind, _ns, name, ann in writer.patches}
    assert ("MCPServer", "github") in patched
    assert ("Agent", "researcher") in patched
    agent_ann = patched[("Agent", "researcher")]
    assert agent_ann[AIB_SYNC_STATUS_ANNOTATION] == "ok"
    assert agent_ann[AIB_EXTERNAL_ID_ANNOTATION] == "kaos://agent/demo/researcher"
    assert agent_ann[AIB_SYNCED_AT_ANNOTATION]
    # Write-back is additive: only annotation keys, never spec.
    assert all(key.startswith("kaos.dev/aib-") for key in agent_ann)


def test_run_once_skips_write_back_when_disabled():
    resources = [_mcpserver("github"), _agent("researcher", ["github"])]
    aib, secrets, writer = FakeAIB(), FakeSecrets(), FakeStatusWriter()
    settings = Settings(status_annotations_enabled=False)

    run_once(settings, FakeLister(resources), aib, secrets, writer)
    assert writer.patches == []


def test_run_once_writes_error_status_for_failed_agent():
    from kaos_sync.reconcile import AIB_SYNC_MESSAGE_ANNOTATION, AIB_SYNC_STATUS_ANNOTATION

    # The broker fails to create the agent -> its write-back carries an error status.
    resources = [_mcpserver("github"), _agent("researcher", ["github"])]
    aib = _AgentCreateFailsAIB("kaos://agent/demo/researcher")
    secrets, writer = FakeSecrets(), FakeStatusWriter()

    run_once(Settings(), FakeLister(resources), aib, secrets, writer)
    agent_patch = next(ann for kind, _ns, name, ann in writer.patches if kind == "Agent")
    assert agent_patch[AIB_SYNC_STATUS_ANNOTATION] == "error"
    assert agent_patch[AIB_SYNC_MESSAGE_ANNOTATION]


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


class _AgentCreateFailsAIB(FakeAIB):
    def __init__(self, fail_display):
        super().__init__()
        self._fail_display = fail_display

    def create_or_get(self, collection, match_field, match_value, body):
        if collection == "agents" and match_value == self._fail_display:
            raise RuntimeError("broker unreachable")
        return super().create_or_get(collection, match_field, match_value, body)


class _ServiceCreateFailsAIB(FakeAIB):
    def __init__(self, fail_client_id):
        super().__init__()
        self._fail_client_id = fail_client_id

    def create_or_get(self, collection, match_field, match_value, body):
        if collection == "services" and match_value == self._fail_client_id:
            raise RuntimeError("service create failed")
        return super().create_or_get(collection, match_field, match_value, body)


class _IncompleteMintAIB(FakeAIB):
    def mint_credentials(self, agent_id):
        self.mint_calls.append(agent_id)
        return {"client_id": "", "client_secret": ""}


class _DeleteFailsAIB(FakeAIB):
    def delete(self, collection, resource_id):
        if collection == "agents":
            raise RuntimeError("delete failed")
        return super().delete(collection, resource_id)


def test_failure_on_one_agent_is_isolated_from_others():
    desired = project([_agent("a", ["github"]), _agent("b", ["slack"])])
    aib = _AgentCreateFailsAIB(fail_display="kaos://agent/demo/a")
    secrets = FakeSecrets()

    summary = reconcile(desired, aib, secrets, "kaos-aib")

    assert summary.ok is False
    by_id = {a.external_id: a for a in summary.agents}
    assert by_id["kaos://agent/demo/a"].ok is False
    assert by_id["kaos://agent/demo/b"].ok is True
    # The failed agent never gets a credential Secret; the healthy one does.
    assert secrets.get("demo", "kaos-aib-a") is None
    assert secrets.get("demo", "kaos-aib-b") is not None
    assert [p.category for p in summary.problems] == [ProblemCategory.AIB_UNREACHABLE]


def test_unavailable_service_skips_dependent_edge_and_agent_fail_closed():
    desired = project([_agent("a", ["github"]), _agent("b", ["slack"])])
    aib = _ServiceCreateFailsAIB(fail_client_id="kaos-mcpserver-demo-github")
    secrets = FakeSecrets()

    summary = reconcile(desired, aib, secrets, "kaos-aib")

    categories = {p.category for p in summary.problems}
    assert ProblemCategory.UNSUPPORTED_EDGE in categories
    by_id = {a.external_id: a for a in summary.agents}
    # Agent a depends on the failed service and is skipped fail-closed (no credentials).
    assert by_id["kaos://agent/demo/a"].ok is False
    assert by_id["kaos://agent/demo/a"].credentials_minted is False
    assert secrets.get("demo", "kaos-aib-a") is None
    # Agent b is unaffected.
    assert by_id["kaos://agent/demo/b"].ok is True
    assert secrets.get("demo", "kaos-aib-b") is not None


def test_incomplete_credentials_are_reported_and_not_stored():
    desired = project([_agent("a", ["github"])])
    aib = _IncompleteMintAIB()
    secrets = FakeSecrets()

    summary = reconcile(desired, aib, secrets, "kaos-aib")

    assert summary.agents[0].ok is False
    assert summary.agents[0].credentials_minted is False
    assert secrets.get("demo", "kaos-aib-a") is None
    assert [p.category for p in summary.problems] == [ProblemCategory.MISSING_CREDENTIALS]


def test_prune_delete_failure_is_reported_and_pass_continues():
    aib = _DeleteFailsAIB()
    secrets = FakeSecrets()
    reconcile(project([_agent("a", ["github"]), _agent("b", ["slack"])]), aib, secrets, "kaos-aib")

    summary = reconcile(project([_agent("a", ["github"])]), aib, secrets, "kaos-aib", prune=True)

    assert summary.pruned.agents == 0  # the agent delete failed
    assert any(p.category == ProblemCategory.PRUNE_FAILED for p in summary.problems)
    # Permission sets and services still get pruned despite the agent delete failure.
    assert summary.pruned.services == 1


def test_prune_skips_malformed_external_id_as_drift():
    aib = FakeAIB()
    secrets = FakeSecrets()
    reconcile(project([_agent("a", ["github"])]), aib, secrets, "kaos-aib")
    # Inject a KAOS-prefixed agent whose external id cannot be parsed into ns/name.
    aib.collections["agents"]["kaos://agent/onlyone"] = {
        "id": "malformed",
        "display_name": "kaos://agent/onlyone",
    }

    summary = reconcile(project([]), aib, secrets, "kaos-aib", prune=True)

    assert any(p.category == ProblemCategory.STALE_EXTERNAL_ID for p in summary.problems)
    # The malformed record is left in place rather than blindly deleted.
    assert aib.get("agents", "malformed") is not None
