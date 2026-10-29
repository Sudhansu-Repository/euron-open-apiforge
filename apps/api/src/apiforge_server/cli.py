"""Command line: ``apiforge-server <command>``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from apiforge_server.core.config import get_settings


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "apiforge_server.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        proxy_headers=True,
        # Only trust X-Forwarded-For from the load balancer's network (the VPC CIDR on AWS).
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
        # Longer than a load balancer's idle timeout (60 s on an ALB): otherwise the server
        # may close a kept-alive connection just as the balancer reuses it (a 502).
        timeout_keep_alive=75,
    )


def _worker(_: argparse.Namespace) -> None:
    from apiforge_server.worker import main

    asyncio.run(main())


def _migrate(_: argparse.Namespace) -> None:
    from apiforge_server.migrations.runner import upgrade

    upgrade(get_settings().database_url)
    print("migrations applied")


def _revision(args: argparse.Namespace) -> None:
    from apiforge_server.migrations.runner import revision

    revision(get_settings().database_url, args.message)


async def _create_owner(email: str, name: str, password_hash: str) -> None:
    from sqlalchemy import func, select

    from apiforge_server.core.db import Database
    from apiforge_server.users.models import User

    db = Database(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing:
                existing.role = "owner"
                existing.password_hash = password_hash
                existing.disabled = False
                existing.session_version += 1
                print(f"updated {email} (owner)")
            else:
                session.add(
                    User(
                        email=email.lower(),
                        name=name,
                        role="owner",
                        password_hash=password_hash,
                    )
                )
                print(f"created {email} (owner)")
            await session.commit()
    finally:
        await db.dispose()


def _checked_hash(password: str) -> str:
    from apiforge_server.core.security import hash_password, password_problems

    if problems := password_problems(password):
        sys.exit("password needs " + ", ".join(problems))
    return hash_password(password)


def _owner(args: argparse.Namespace) -> None:
    # A one-off cloud task gets only the hash (APIFORGE_OWNER_PASSWORD_HASH, made locally
    # by `hash-password`): task overrides are visible to anyone who can describe the task.
    given_hash = os.environ.get("APIFORGE_OWNER_PASSWORD_HASH", "")
    if given_hash:
        if not given_hash.startswith("$argon2id$"):
            sys.exit("APIFORGE_OWNER_PASSWORD_HASH must be an argon2id hash from `hash-password`")
        password_hash = given_hash
    else:
        password = os.environ.get("APIFORGE_OWNER_PASSWORD") or getpass.getpass("Password: ")
        password_hash = _checked_hash(password)
    asyncio.run(_create_owner(args.email, args.name, password_hash))


def _hash(_: argparse.Namespace) -> None:
    password = os.environ.get("APIFORGE_OWNER_PASSWORD") or getpass.getpass("Password: ")
    sys.stdout.write(_checked_hash(password) + "\n")


def _seed(args: argparse.Namespace) -> None:
    from apiforge_server.demo.seed import run

    if get_settings().environment == "production":
        raise SystemExit(
            "seed-demo creates well-known demo logins; it refuses ENVIRONMENT=production."
        )

    asyncio.run(run())


def _openapi(_: argparse.Namespace) -> None:
    from apiforge_server.openapi import spec, to_yaml

    sys.stdout.write(to_yaml(spec()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="apiforge-server", description="Euron Open APIForge service"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 the container must listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "4630")))
    # One process per container by default: Prometheus counters and the in-process cache
    # stay exact. Scale with more tasks or replicas, not more workers per task.
    p.add_argument("--workers", type=int, default=int(os.environ.get("WEB_CONCURRENCY", "1")))
    p.set_defaults(fn=_serve)

    sub.add_parser("worker", help="run queued generations").set_defaults(fn=_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=_migrate)
    p = sub.add_parser(
        "revision", help="autogenerate a new migration from the models (against a migrated DB)"
    )
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(fn=_revision)
    sub.add_parser("openapi", help="print the OpenAPI document as YAML").set_defaults(fn=_openapi)

    p = sub.add_parser("create-owner", help="create or reset an owner account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Owner")
    p.set_defaults(fn=_owner)
    sub.add_parser(
        "hash-password",
        help="print the argon2id hash of APIFORGE_OWNER_PASSWORD (or a prompted password)",
    ).set_defaults(fn=_hash)

    sub.add_parser(
        "seed-demo",
        help="demo users, projects from the example specs, spec history and generations",
    ).set_defaults(fn=_seed)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
