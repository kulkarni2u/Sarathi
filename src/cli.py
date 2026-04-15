"""CLI implementation for Sarathi."""
import argparse
import sys
from pathlib import Path

from sarathi.src.init import InitWorkflow
from sarathi.src.validate import PolicyValidator


def main() -> None:
    parser = argparse.ArgumentParser(prog="sarathi", description="Sarathi CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new Sarathi task")
    init_parser.add_argument(
        "target_path",
        nargs="?",
        default=".",
        help="Target path for initialization (default: .)",
    )
    init_parser.add_argument(
        "--engine",
        default="markdown",
        help="Engine to use (default: markdown)",
    )

    validate_parser = subparsers.add_parser("validate", help="Validate a policy pack")
    validate_parser.add_argument(
        "policy_pack",
        help="Path to the policy pack to validate",
    )

    run_parser = subparsers.add_parser("run", help="Run a task")
    run_parser.add_argument(
        "task_file",
        help="Path to the task file",
    )
    run_parser.add_argument(
        "--policy-pack",
        help="Policy pack to use",
    )

    args = parser.parse_args()

    if args.command == "init":
        workflow = InitWorkflow()
        result = workflow.inspect()
        print(f"Initialized at {args.target_path} with engine {args.engine}")
        print(f"Workflow result: {result}")
        del workflow

    elif args.command == "validate":
        validator = PolicyValidator()
        required_list = validator.load_required_list()
        policy_claims = validator.load_policy_claims()
        result = validator.validate(required_list, policy_claims)
        print(f"Validation result: {result.status.value}")
        del validator

    elif args.command == "run":
        print("Run not yet implemented")


if __name__ == "__main__":
    main()