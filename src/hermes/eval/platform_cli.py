"""Platform CLI — the operator-facing entry for matrix / ops / extensions.

R7 deliverable (b, separate CLI module). The platform CLI is a SEPARATE
module from ``src/hermes/cli.py`` — it does not import it, does not
subclass it, and does not register anything with it. Operators reach
the matrix / ops / extensions surfaces through this module:

* ``python -m hermes.eval.platform_cli matrix`` — run the adversarial
  matrix, print a machine-readable report, exit nonzero on any red;
* ``python -m hermes.eval.platform_cli auth`` — exercise the auth
  surface (smoke test the operator-credential boundary);
* ``python -m hermes.eval.platform_cli extensions`` — list the
  frozen extension points;
* ``python -m hermes.eval.platform_cli verify-backup <path> <sha256>``
  — verify a backup artifact.

The CLI is **pure evaluation + enforcement** — it never opens SQLite,
never opens a socket, never holds a clock, never reads a model. Every
refusal it surfaces is in the frozen vocabulary; every action it
performs is a pure function of its arguments.

This module is the SEPARATE CLI mandated by R7. It does **not** import
``hermes.cli`` (or any of its private submodules); the surface of the
two is intentionally independent so the spine's R-round CLIs do not
become a vector for the eval plane (or vice versa).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Sequence

from hermes.eval.extensions import (
    EXTENSION_POINTS,
    describe_extension,
    list_extensions,
)
from hermes.eval.matrix import build_matrix, render_report, run_matrix
from hermes.eval.ops import (
    BackupManifest,
    authenticate,
    verify_backup,
)

__all__ = [
    "cmd_auth",
    "cmd_extensions",
    "cmd_matrix",
    "cmd_redact_demo",
    "cmd_verify_backup",
    "main",
]


def cmd_matrix(argv: Sequence[str]) -> int:
    """``platform_cli matrix [...]`` — run the adversarial matrix."""
    parser = argparse.ArgumentParser(
        prog="hermes.eval.platform_cli matrix",
        description="Run the adversarial matrix (one command, all planes).")
    parser.add_argument("--plane", action="append", default=None,
                        help="restrict to one or more planes")
    parser.add_argument("--report-path", default=None,
                        help="write the report to this path (stdout if omitted)")
    parser.add_argument("--no-pinned-test", action="store_true",
                        help="skip the pinned-test invocation (inline-only)")
    parser.add_argument("--format", choices=("json", "human"), default="json")
    args = parser.parse_args(list(argv))
    cases = build_matrix()
    if args.plane:
        wanted = set(args.plane)
        cases = tuple(c for c in cases if c.plane in wanted)
    report = run_matrix(cases, invoke_pinned_tests=not args.no_pinned_test)
    text = render_report(report, as_json=(args.format == "json"))
    if args.report_path:
        with open(args.report_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
    return 0 if report.is_clean() else 1


def cmd_auth(argv: Sequence[str]) -> int:
    """``platform_cli auth ...`` — exercise the auth surface."""
    parser = argparse.ArgumentParser(
        prog="hermes.eval.platform_cli auth",
        description="Authenticate a token against the ops surface (smoke test).")
    parser.add_argument("--actor", required=True, help="the operator's actor name")
    parser.add_argument("--token", required=True, help="the token to verify")
    parser.add_argument("--project-id", default="", help="the project scope")
    parser.add_argument("--scopes", action="append", default=[],
                        help="scope (repeat for multiple)")
    parser.add_argument("--lifetime-seconds", type=float, default=3600.0,
                        help="the credential's lifetime")
    parser.add_argument("--format", choices=("json", "human"), default="json")
    args = parser.parse_args(list(argv))
    outcome = authenticate(
        actor=args.actor, token=args.token,
        project_id=args.project_id, scopes=tuple(args.scopes),
        lifetime_seconds=args.lifetime_seconds)
    if outcome.is_refusal():
        refusal = outcome.refusal
        assert refusal is not None  # type-invariant: is_refusal() ↔ refusal set
        if args.format == "json":
            print(json.dumps(refusal.as_dict(), sort_keys=True))
        else:
            print(f"REFUSED {refusal.code}: {refusal.detail}")
        return 1
    ctx = outcome.value
    body = {
        "actor": ctx.actor,
        "token_digest": ctx.token_digest,
        "issued_at": ctx.issued_at,
        "expires_at": ctx.expires_at,
        "scopes": list(ctx.scopes),
        "project_id": ctx.project_id,
    }
    if args.format == "json":
        print(json.dumps(body, sort_keys=True))
    else:
        for key, value in sorted(body.items()):
            print(f"{key}: {value}")
    return 0


def cmd_extensions(argv: Sequence[str]) -> int:
    """``platform_cli extensions [name]`` — list or describe extension points."""
    parser = argparse.ArgumentParser(
        prog="hermes.eval.platform_cli extensions",
        description="List (or describe) the frozen extension points.")
    parser.add_argument("name", nargs="?", default=None,
                        help="the extension point to describe (default: list all)")
    parser.add_argument("--format", choices=("json", "human"), default="human")
    args = parser.parse_args(list(argv))
    if args.name is None:
        items = list_extensions()
        if args.format == "json":
            print(json.dumps({"extensions": [
                {"name": n, "summary": EXTENSION_POINTS[n].summary}
                for n in items
            ]}, indent=2))
        else:
            print("Frozen extension points:")
            for n in items:
                print(f"  - {n}: {EXTENSION_POINTS[n].summary}")
        return 0
    if args.name not in EXTENSION_POINTS:
        print(json.dumps({"error": "unknown_extension",
                          "name": args.name,
                          "available": list(EXTENSION_POINTS)}, indent=2))
        return 2
    print(describe_extension(args.name, as_json=(args.format == "json")))
    return 0


def cmd_verify_backup(argv: Sequence[str]) -> int:
    """``platform_cli verify-backup <path> <sha256> <byte_size>``."""
    parser = argparse.ArgumentParser(
        prog="hermes.eval.platform_cli verify-backup",
        description="Verify a backup artifact's digest against its manifest.")
    parser.add_argument("path", help="the backup file path")
    parser.add_argument("sha256", help="the declared SHA-256 hex digest")
    parser.add_argument("byte_size", type=int,
                        help="the declared byte size (required; it is "
                             "enforced, never skipped)")
    args = parser.parse_args(list(argv))
    manifest = BackupManifest(path=args.path, sha256_hex=args.sha256,
                              byte_size=int(args.byte_size))
    outcome = verify_backup(manifest)
    if outcome.is_refusal():
        refusal = outcome.refusal
        assert refusal is not None  # type-invariant
        print(json.dumps(refusal.as_dict(), sort_keys=True))
        return 1
    print(json.dumps({
        "verified": True,
        "path": args.path,
        "sha256_hex": args.sha256,
        "byte_size": int(args.byte_size),
    }, sort_keys=True))
    return 0


def cmd_redact_demo(argv: Sequence[str]) -> int:
    """``platform_cli redact-demo`` — show the redactor on a fixture payload."""
    parser = argparse.ArgumentParser(
        prog="hermes.eval.platform_cli redact-demo",
        description="Run a redactor demo on a fixture payload.")
    parser.add_argument("--format", choices=("json", "human"), default="json")
    args = parser.parse_args(list(argv))
    from hermes.eval.ops import redact
    payload: Mapping[str, Any] = {
        "actor": "op-1",
        "actor_token": "op_AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "bearer": "Bearer AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "headers": {"authorization": "Bearer XXXXXXXXXXXXXXXXXXXX"},
        "nested": {"api_key": "sk-1234567890abcdef", "value": 42},
        "list": [{"token": "abc"}, {"safe": "hello"}],
    }
    redacted = redact(payload)
    if args.format == "json":
        print(json.dumps(redacted, indent=2, default=str))
    else:
        for key, value in sorted(redacted.items()):
            print(f"{key}: {value!r}")
    return 0


_COMMANDS = {
    "matrix": cmd_matrix,
    "auth": cmd_auth,
    "extensions": cmd_extensions,
    "verify-backup": cmd_verify_backup,
    "redact-demo": cmd_redact_demo,
}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry — ``python -m hermes.eval.platform_cli <cmd> [...]``.

    The CLI is a thin dispatcher: the global parser only knows about
    the subcommand name, and the rest of ``argv`` is forwarded to the
    subcommand's own parser. This is what keeps the parent and the
    subcommand's ``--format`` choices independent.
    """
    raw = list(argv) if argv is not None else None
    if not raw:
        # argparse will print the help message and return 2; that's
        # the desired behaviour for an empty invocation.
        parser = argparse.ArgumentParser(
            prog="hermes.eval.platform_cli",
            description=("Platform CLI (matrix / ops / extensions). "
                         "This is a SEPARATE module from src/hermes/cli.py."),
        )
        parser.add_argument("command", choices=sorted(_COMMANDS),
                            help="the subcommand to run")
        parser.parse_args([])
        return 2
    command = raw[0]
    rest = raw[1:]
    if command not in _COMMANDS:
        print(f"unknown command: {command!r}; available: "
              f"{sorted(_COMMANDS)}", file=sys.stderr)
        return 2
    cmd = _COMMANDS[command]
    return cmd(rest)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
