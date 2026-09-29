"""Run a bounded investigator: offline by default; explicit --live for a selected provider."""

import argparse
import asyncio
import getpass
import os
import sys

from .anthropic_model import AnthropicMessagesModel
from .cases import BANK_CASE_ID, CASE_ID, TIMING_CASE_ID
from .investigation import InvestigationError, render_investigation
from .investigator import run_mcp_investigation
from .openai_model import OpenAIResponsesModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=[CASE_ID, BANK_CASE_ID, TIMING_CASE_ID], default=CASE_ID)
    parser.add_argument("--live", action="store_true", help="Send synthetic case data to the selected paid model API.")
    parser.add_argument("--provider", choices=("openai", "anthropic"), help="Live provider; defaults to openai for compatibility.")
    parser.add_argument("--model", help="Explicit provider model ID; or set RECONFORGE_MODEL.")
    parser.add_argument("--json", action="store_true", help="Print the structured run and its execution trace.")
    args = parser.parse_args()
    model = None
    try:
        if args.live:
            provider = args.provider or "openai"
            model_id = args.model or os.environ.get("RECONFORGE_MODEL")
            if not model_id:
                parser.error("--live requires --model MODEL_ID or RECONFORGE_MODEL; no model is chosen automatically.")
            if provider == "openai":
                key_name, label, model_type = "OPENAI_API_KEY", "OpenAI", OpenAIResponsesModel
            else:
                key_name, label, model_type = "ANTHROPIC_API_KEY", "Anthropic", AnthropicMessagesModel
            api_key = os.environ.get(key_name)
            if not api_key:
                if not sys.stdin.isatty():
                    parser.error(f"Run interactively for a hidden API-key prompt, or set {key_name} locally.")
                api_key = getpass.getpass(f"{label} API key (hidden; not saved): ")
            model = model_type(api_key, model_id)
            print(f"Live mode: sending synthetic case data to {label}; at most 6 requests, no automatic retries.", file=sys.stderr)
        elif args.model or args.provider:
            parser.error("--model and --provider are only used with --live.")
        run = asyncio.run(run_mcp_investigation(args.case_id, model))
        print(run.model_dump_json(indent=2) if args.json else render_investigation(run), end="\n" if args.json else "")
    except InvestigationError as exc:
        print(f"Investigation stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("Investigation cancelled.", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception:
        # Raw transport exceptions can contain source text. Keep the CLI boundary
        # concise; no traceback, API key, prompt, or raw provider response is printed.
        print("Investigation stopped because the local MCP connection or response was invalid.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
