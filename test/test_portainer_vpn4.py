from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PORTAINER_COMPOSE = ROOT / "portainer-vpn4" / "docker-compose.yml"


def load_portainer_compose():
    """Load the Task 1 service contract from its Compose file."""
    assert PORTAINER_COMPOSE.exists(), "portainer-vpn4/docker-compose.yml phai ton tai"
    data = yaml.safe_load(PORTAINER_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Compose phai la mot YAML mapping"
    return data


def test_portainer_compose_exists_and_is_valid_yaml():
    compose = load_portainer_compose()
    assert isinstance(compose.get("services"), dict)
    assert set(compose["services"]) == {"portainer"}, (
        "Stack quan tri Docker nay chi duoc co service portainer; them service "
        "thu hai co the mo port/privileged mount hoac vuot security contract."
    )


def test_portainer_service_is_private_and_persistent():
    service = load_portainer_compose()["services"]["portainer"]

    assert service["image"] == "portainer/portainer-ce:lts"
    assert service["command"] == ["--http-enabled"]
    assert service["container_name"] == "portainer"
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"] == "256m"
    assert not service.get("ports")
    assert service["volumes"] == [
        "/var/run/docker.sock:/var/run/docker.sock",
        "portainer_data:/data",
    ]


def test_portainer_uses_only_the_external_edge_network():
    compose = load_portainer_compose()
    service = compose["services"]["portainer"]

    assert service["networks"] == ["edge"]
    assert compose["networks"] == {"edge": {"external": True, "name": "edge"}}


def test_portainer_declares_its_named_data_volume():
    compose = load_portainer_compose()
    assert compose["volumes"] == {"portainer_data": None}


def test_portainer_does_not_declare_an_unsupported_image_healthcheck():
    """Portainer LTS does not document an in-image HTTP probe utility.

    A `CMD-SHELL curl ...` or guessed Portainer CLI flag would report a false
    health state. Readiness is instead verified by the deploy workflow through
    the publicly terminated TLS route and Portainer's `/api/status` endpoint.
    """
    service = load_portainer_compose()["services"]["portainer"]
    assert "healthcheck" not in service


def test_portainer_uses_existing_json_log_rotation_convention():
    logging = load_portainer_compose()["services"]["portainer"]["logging"]
    assert logging == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }
