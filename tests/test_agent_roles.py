import pytest

from src.runtime import (
    AgentRole,
    clear_registered_agent_roles,
    get_agent_role,
    get_phase_agent_role,
    list_agent_roles,
    list_phase_agent_roles,
    phase_agent_role_artifact,
    register_agent_role,
    registered_agent_roles,
)
from src.runtime.agent_roles import DEFAULT_AGENT_ROLES


def test_default_agent_roles_are_stable_and_named():
    roles = list_agent_roles()

    assert isinstance(roles, tuple)
    assert [role.key for role in roles] == [
        "sarathi",
        "disha",
        "vichara",
        "prajna",
        "pravaha",
        "nirnaya",
        "samanvaya",
        "sahayaka",
        "marga",
        "sutra",
    ]
    assert roles[0] == AgentRole(
        key="sarathi",
        name="Sarathi",
        purpose="orchestrator",
        description="Overall workflow orchestrator for policy-backed Sarathi runs.",
        aliases=("orchestrator",),
    )


def test_agent_role_lookup_accepts_keys_names_and_aliases():
    assert get_agent_role("disha").purpose == "planner"
    assert get_agent_role("Disha").key == "disha"
    assert get_agent_role("planner").name == "Disha"
    assert get_agent_role("validator").name == "Nirnaya"
    assert get_agent_role("message bus").name == "Sutra"


def test_agent_role_lookup_returns_default_for_unknown_role():
    fallback = AgentRole(
        key="custom",
        name="Custom",
        purpose="custom role",
        description="Fallback role.",
    )

    assert get_agent_role("unknown", default=fallback) is fallback


def test_agent_role_lookup_raises_for_unknown_role_without_default():
    with pytest.raises(KeyError, match="Unknown Sarathi agent role"):
        get_agent_role("unknown")


def test_default_agent_role_registry_is_not_mutable_from_callers():
    roles = list_agent_roles()

    assert roles is not DEFAULT_AGENT_ROLES
    assert roles == DEFAULT_AGENT_ROLES


def test_phase_agent_role_mapping_uses_sanskrit_names():
    assert get_phase_agent_role("Route").name == "Marga"
    assert get_phase_agent_role("Plan").name == "Disha"
    assert get_phase_agent_role("Build").name == "Pravaha"
    assert get_phase_agent_role("Review").name == "Nirnaya"
    assert get_phase_agent_role("PhaseLog").name == "Sutra"


def test_phase_agent_role_artifact_is_serializable():
    artifact = phase_agent_role_artifact("TaskTracking")

    assert artifact["phase"] == "TaskTracking"
    assert artifact["name"] == "Samanvaya"
    assert artifact["purpose"] == "coordinator"
    assert artifact["aliases"] == ["coordinator", "coordination"]


def test_list_phase_agent_roles_returns_lifecycle_mapping():
    mappings = list_phase_agent_roles()

    assert mappings[0]["phase"] == "Route"
    assert mappings[0]["name"] == "Marga"
    assert mappings[-1]["phase"] == "Learn"
    assert mappings[-1]["name"] == "Prajna"


# ---------------------------------------------------------------------------
# Registered (user-declared) agent roles
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def _clear_registered_roles():
    """Ensure the user-declared role registry doesn't leak across tests."""
    try:
        yield
    finally:
        clear_registered_agent_roles()


def test_register_and_list_registered_agent_roles(_clear_registered_roles):
    role = AgentRole(
        key="custom-agent",
        name="Custom Agent",
        purpose="custom",
        description="A user-declared agent.",
        aliases=("ca",),
    )

    assert registered_agent_roles() == ()

    register_agent_role(role)

    assert registered_agent_roles() == (role,)


def test_register_agent_role_dedupes_by_key(_clear_registered_roles):
    role = AgentRole(
        key="custom-agent",
        name="Custom Agent",
        purpose="custom",
        description="A user-declared agent.",
        aliases=("ca", "custom-helper"),
    )

    register_agent_role(role)

    assert registered_agent_roles() == (role,)
    # Looking it up by alias and by key both resolve to the same object.
    assert get_agent_role("ca") is role
    assert get_agent_role("custom-agent") is role


def test_get_agent_role_finds_registered_role_by_key_name_and_alias(_clear_registered_roles):
    role = AgentRole(
        key="researcher-x",
        name="Researcher X",
        purpose="custom research role",
        description="Registered research role.",
        aliases=("rx",),
    )
    register_agent_role(role)

    assert get_agent_role("researcher-x") == role
    assert get_agent_role("Researcher X") == role
    assert get_agent_role("rx") == role


def test_clear_registered_agent_roles_removes_lookup(_clear_registered_roles):
    role = AgentRole(
        key="temp-role",
        name="Temp Role",
        purpose="temp",
        description="Temporary.",
    )
    register_agent_role(role)
    assert get_agent_role("temp-role") == role

    clear_registered_agent_roles()

    assert registered_agent_roles() == ()
    with pytest.raises(KeyError):
        get_agent_role("temp-role")


def test_clear_registered_agent_roles_falls_back_to_default(_clear_registered_roles):
    role = AgentRole(
        key="temp-role-2",
        name="Temp Role 2",
        purpose="temp2",
        description="Temporary 2.",
    )
    register_agent_role(role)

    clear_registered_agent_roles()

    fallback = AgentRole(key="fb", name="Fallback", purpose="fb", description="fb")
    assert get_agent_role("temp-role-2", default=fallback) is fallback
