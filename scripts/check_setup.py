"""Is this machine set up correctly? Run this before anything else.

    python scripts/check_setup.py

It answers five questions, in order, and stops being useful only when all five
are yes:

    1. Is there a .env file where the code expects one?
    2. Does it contain a key that is not empty, quoted or padded with spaces?
    3. Does Sarvam accept that key?
    4. Which model ids can this key use?
    5. Are the output and database paths absolute, so a run from any folder works?

It never prints the key itself. Every check is something that has actually gone
wrong at least once, on Windows more often than not: Notepad saving ".env.txt",
a byte-order mark turning the first variable name into "\ufeffSARVAM_API_KEY",
and a key pasted with its surrounding quotes.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import config, llm  # noqa: E402

OK = "[ok]"
WARN = "[!!]"
FAIL = "[XX]"

problems = 0


def say(status: str, message: str) -> None:
    print(f"{status} {message}")


def check_env_file() -> Path:
    """1. The file must exist, and be called exactly .env."""
    global problems
    env = ROOT / ".env"
    if env.exists():
        say(OK, f"found {env}")
        return env

    problems += 1
    say(FAIL, f"no .env at {env}")
    for neighbour in sorted(ROOT.glob(".env*")) + sorted(ROOT.glob("*.env")):
        if neighbour.name in (".env.example", ".env.sample"):
            continue  # that is the template, not a mistake
        say(WARN, f"but there is a {neighbour.name} - rename it to .env exactly")
    say(WARN, "fix: copy .env.example to .env, then paste your key into it")
    return env


def check_encoding(env: Path) -> None:
    """2a. A byte-order mark silently breaks the first variable name."""
    if not env.exists():
        return
    raw = env.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        say(FAIL, ".env starts with a UTF-8 byte-order mark (Notepad does this).")
        say(WARN, "fix: open it in Notepad, File > Save as, Encoding = UTF-8 "
                  "(not 'UTF-8 with BOM'), or delete and recreate the file")
    elif b"\r\n" in raw:
        say(OK, ".env uses Windows line endings, which is fine")
    else:
        say(OK, ".env has no byte-order mark")


def check_key() -> str:
    """2b. The key must be non-empty and clean."""
    global problems
    key = config.SARVAM_API_KEY

    if not key:
        problems += 1
        say(FAIL, "SARVAM_API_KEY is empty or was not read")
        say(WARN, "fix: open .env and paste the key after SARVAM_API_KEY=, with "
                  "no quotes and no spaces")
        return ""

    if key != key.strip():
        problems += 1
        say(FAIL, "the key has leading or trailing whitespace")
        say(WARN, "fix: remove the spaces around it in .env")
    if key[:1] in "'\"" or key[-1:] in "'\"":
        problems += 1
        say(FAIL, "the key is wrapped in quotes")
        say(WARN, "fix: SARVAM_API_KEY=your-key-here, with no quote marks")

    say(OK, f"key loaded: {len(key)} characters, starts {key[:4]}...")
    if len(key) < 20:
        problems += 1
        say(FAIL, "that is shorter than any real key - did you paste all of it?")
    return key


def check_models() -> None:
    """3 and 4. Does the key work, and what can it use?"""
    global problems
    try:
        models = llm.list_models()
    except llm.LLMError as error:
        problems += 1
        text = str(error)
        say(FAIL, f"Sarvam rejected the request: {text[:160]}")
        if "403" in text or "401" in text:
            say(WARN, "that is an authentication failure, not a network one:")
            say(WARN, "  - the key is wrong, expired, or from a different account")
            say(WARN, "  - or .env was not read (check the two lines above)")
            say(WARN, "  - get a fresh key from dashboard.sarvam.ai > API keys")
        return

    say(OK, f"Sarvam accepted the key: {len(models)} model ids available")
    for model in models:
        print(f"       {model}")

    for role, wanted in (("LLM_MODEL_STRONG", config.MODEL_STRONG),
                         ("LLM_MODEL_FAST", config.MODEL_FAST)):
        if wanted in models:
            say(OK, f"{role}={wanted} is available")
        else:
            problems += 1
            say(FAIL, f"{role}={wanted} is not in the list above")
            say(WARN, f"fix: set {role} in .env to one of the ids above")


def check_auth_variants(key: str) -> None:
    """Try the key three ways, to separate a bad key from a bad header.

    Our client sends both headers at once. If the key is good but one of the
    headers upsets the gateway, this is the test that shows it: exactly one of
    these three lines will come back 200.
    """
    import requests

    print("header variants against GET /v2/models:")
    variants = {
        "api-subscription-key only": {"api-subscription-key": key},
        "Authorization: Bearer only": {"Authorization": f"Bearer {key}"},
        "both (what the app sends)": {
            "api-subscription-key": key,
            "Authorization": f"Bearer {key}",
        },
    }
    for label, headers in variants.items():
        try:
            response = requests.get(config.MODELS_URL, headers=headers, timeout=30)
            detail = ""
            if response.status_code != 200:
                detail = "  " + response.text[:90].replace("\n", " ")
            print(f"  {response.status_code}  {label}{detail}")
        except requests.RequestException as exc:
            print(f"  ---  {label}  (network: {exc})")


def check_paths() -> None:
    """5. Relative paths in .env broke a run on Windows; make sure they are not."""
    global problems
    for name, path in (("OUTPUT_DIR", config.OUTPUT_DIR), ("DB_PATH", config.DB_PATH)):
        if path.is_absolute():
            say(OK, f"{name} = {path}")
        else:
            problems += 1
            say(FAIL, f"{name} = {path} is relative - pull the latest code")


def main() -> int:
    raw = "--raw" in sys.argv
    print("Content Forge - setup check\n")
    env = check_env_file()
    check_encoding(env)
    print()
    key = check_key()
    print()
    if key and raw:
        check_auth_variants(key)
        print()
    if key:
        check_models()
    print()
    check_paths()

    print()
    if problems == 0:
        print("Everything checks out. Next: python scripts/cli.py <your-document.pdf> --trace")
        return 0
    print(f"{problems} problem(s) above. Fix them and run this again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
