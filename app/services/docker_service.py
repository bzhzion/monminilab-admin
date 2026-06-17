import time

import docker
from docker.errors import NotFound, APIError

from app.config import settings

_client = None


def _get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def _container_name(slug: str) -> str:
    return f"wp-{slug}"


def create_wp_container(
    slug: str,
    port: int,
    db_name: str,
    db_user: str,
    db_pass: str,
    mariadb_host: str,
    smtp_user: str,
    smtp_pass: str,
) -> None:
    client = _get_client()
    name = _container_name(slug)

    site_dir = f"{settings.SITES_DATA_DIR}/{slug}"

    env = {
        "WORDPRESS_DB_HOST": mariadb_host,
        "WORDPRESS_DB_NAME": db_name,
        "WORDPRESS_DB_USER": db_user,
        "WORDPRESS_DB_PASSWORD": db_pass,
        "WORDPRESS_TABLE_PREFIX": "wp_",
        "SMTP_HOST": "smtp.forwardemail.net",
        "SMTP_PORT": "465",
        "SMTP_USER": smtp_user,
        "SMTP_PASS": smtp_pass,
        "SMTP_FROM": smtp_user,
        "SMTP_FROM_NAME": slug,
    }

    client.containers.run(
        image=settings.WP_IMAGE,
        name=name,
        detach=True,
        restart_policy={"Name": "always"},
        ports={"80/tcp": ("127.0.0.1", port)},
        environment=env,
        network=settings.DOCKER_NETWORK,
        volumes={site_dir: {"bind": "/var/www/html", "mode": "rw"}},
        mem_limit="128m",
        labels={
            "com.centurylinklabs.watchtower.enable": "true",
            "monminilab.slug": slug,
        },
    )

def check_wordpress_ready(slug: str) -> bool:
    """Retourne True si WordPress répond (non-5xx) via le réseau Docker interne."""
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen(f"http://wp-{slug}/", timeout=3)
        return True
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def install_wordpress(slug: str, admin_password: str, admin_email: str) -> None:
    url = f"https://{slug}.{settings.BASE_DOMAIN}"
    exec_wp_cli(slug, [
        "wp", "core", "install",
        f"--url={url}",
        f"--title={slug}",
        f"--admin_user={slug}",
        f"--admin_password={admin_password}",
        f"--admin_email={admin_email}",
        "--skip-email",
    ])


def update_smtp_env(slug: str, smtp_pass: str) -> None:
    """Recrée le container WP avec un nouveau SMTP_PASS (conserve tous les autres paramètres)."""
    client = _get_client()
    name = _container_name(slug)
    container = client.containers.get(name)
    attrs = container.attrs

    env_list = attrs["Config"].get("Env") or []
    env = {}
    for e in env_list:
        k, _, v = e.partition("=")
        env[k] = v
    env["SMTP_PASS"] = smtp_pass

    image = attrs["Config"]["Image"]

    port_bindings = attrs["HostConfig"].get("PortBindings") or {}
    ports = {}
    for container_port, bindings in port_bindings.items():
        if bindings:
            b = bindings[0]
            ports[container_port] = (b.get("HostIp", "127.0.0.1"), int(b["HostPort"]))

    # Utilise Mounts (structuré) plutôt que Binds (string à parser manuellement)
    volumes = {
        m["Source"]: {"bind": m["Destination"], "mode": m.get("Mode", "rw")}
        for m in attrs.get("Mounts", [])
        if m.get("Type") == "bind"
    }

    network = list(attrs["NetworkSettings"]["Networks"].keys())[0]
    labels = attrs["Config"].get("Labels") or {}

    container.stop(timeout=10)
    container.remove(force=True)

    client.containers.run(
        image=image, name=name, detach=True,
        restart_policy={"Name": "always"},
        ports=ports, environment=env,
        network=network, volumes=volumes,
        labels=labels, mem_limit="128m",
    )


def remove_wp_container(slug: str) -> None:
    client = _get_client()
    name = _container_name(slug)
    try:
        container = client.containers.get(name)
        container.stop(timeout=10)
        container.remove(force=True)
    except NotFound:
        pass
    except APIError as e:
        raise RuntimeError(f"Docker error removing container {name}: {e}") from e


def exec_wp_cli(slug: str, args: list) -> str:
    """Exécute une commande WP-CLI dans le container. args doit être une liste (pas de bash -c)."""
    client = _get_client()
    name = _container_name(slug)
    try:
        container = client.containers.get(name)
        result = container.exec_run(cmd=args, user="www-data")
        return result.output.decode("utf-8", errors="replace")
    except NotFound:
        raise RuntimeError(f"Container {name} not found")
    except APIError as e:
        raise RuntimeError(f"Docker exec error: {e}") from e


def get_container_status(slug: str) -> str:
    client = _get_client()
    name = _container_name(slug)
    try:
        container = client.containers.get(name)
        return container.status
    except NotFound:
        return "not_found"


def get_container_logs(slug: str, tail: int = 300) -> str:
    client = _get_client()
    name = _container_name(slug)
    try:
        container = client.containers.get(name)
        raw = container.logs(tail=tail, timestamps=True, stdout=True, stderr=True)
        return raw.decode("utf-8", errors="replace")
    except NotFound:
        return f"Container wp-{slug} introuvable."
    except APIError as e:
        return f"Erreur Docker : {e}"


def get_app_logs(container_name: str = "monminilab-admin", tail: int = 500) -> str:
    client = _get_client()
    try:
        container = client.containers.get(container_name)
        raw = container.logs(tail=tail, timestamps=True, stdout=True, stderr=True)
        return raw.decode("utf-8", errors="replace")
    except NotFound:
        return f"Container {container_name} introuvable."
    except APIError as e:
        return f"Erreur Docker : {e}"
