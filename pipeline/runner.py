"""The agentic workflow, in about a hundred lines of plain Python.

Read this file first. It is the project.

    chunks  ->  facts  ->  plan  ->  write  ->  critique  ->  repair

The loop is a for loop over the outputs the planner chose, and a while loop
that sends a draft back to the writer until the critic is satisfied. There is
no graph library, no state machine, no hidden magic: the state is one dict,
and every step appends a row to the trace so you can prove what happened.

Nothing here raises on a bad output. A failed quiz should not cost you the
summary you already have, so each output fails on its own and the run is
marked "partial" instead of dying.
"""

import time
import uuid
from datetime import UTC, datetime

from . import agents, config, ingest, llm, schemas

MAX_CONTEXT_CHARS = 7000  # what the writers actually see


def run(
    doc_name: str,
    text: str,
    outputs: list[str] | None = None,
    depth: str | None = None,
    translate_to: str | None = None,
    call=llm.chat,
    translate_fn=llm.translate,
    on_event=None,
) -> dict:
    """Transform one document into content. Returns the run record as a dict.

    outputs      force a list, skipping the planner (used by tests and the CLI)
    translate_to add a translation of the summary into this language code
    call         the model function; swap it for a fake in tests
    on_event     optional callback, called with {"step","message"} for the UI
    """
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    trace: list[dict] = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "cost_inr": 0.0}

    def emit(step: str, message: str) -> None:
        """Report progress to the caller, if anyone is listening."""
        if on_event:
            on_event({"step": step, "message": message})

    def record(step: str, model: str, ms: int, usage: dict, note: str) -> None:
        """Append one row to the trace and add its tokens to the total."""
        usage_total["prompt_tokens"] += usage.get("prompt_tokens", 0)
        usage_total["completion_tokens"] += usage.get("completion_tokens", 0)
        usage_total["cost_inr"] = round(
            usage_total["cost_inr"] + usage.get("cost_inr", 0.0), 6
        )
        trace.append(
            {
                "step": step,
                "model": usage.get("model", model),
                "ms": ms,
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "note": note,
            }
        )

    # --- Step 1: split the document ---------------------------------------
    emit("chunk", "Splitting the document")
    chunks = ingest.chunk_text(text)
    if not chunks:
        raise ValueError("there is no text to work with")
    words = ingest.word_count(text)
    record("chunk", "-", 0, {}, f"{len(chunks)} chunks, {words} words")

    # --- Step 2: reduce the document to facts (the map half) ---------------
    # Groups of chunks, not one call per chunk: a short document then costs one
    # call instead of twenty, which matters on a free tier's rate limit.
    groups = group_chunks(chunks)
    facts: list[str] = []
    numbers: list[str] = []
    for index, chunk in enumerate(groups, start=1):
        emit("extract", f"Reading part {index} of {len(groups)}")
        step_started = time.perf_counter()
        try:
            result, usage = agents.extract(chunk, index, len(groups), call=call)
            facts.extend(result["facts"])
            numbers.extend(result["numbers"])
            record(
                f"extract {index}/{len(groups)}",
                "fast",
                _ms(step_started),
                usage,
                f"{len(result['facts'])} facts",
            )
        except Exception as exc:  # noqa: BLE001 - a bad step must not end the run
            # Losing one chunk's facts is survivable; losing the run is not.
            record(
                f"extract {index}/{len(groups)}",
                "fast",
                _ms(step_started),
                {},
                f"skipped: {exc}",
            )

    context = build_context(chunks, facts, numbers)

    # --- Step 3: plan ------------------------------------------------------
    emit("plan", "Planning the outputs")
    step_started = time.perf_counter()
    allowed = outputs or list(config.DEFAULT_OUTPUTS)
    if outputs:
        plan = {
            "outputs": outputs,
            "depth": depth or "standard",
            "reason": "outputs were chosen by the caller",
        }
        record("plan", "-", 0, {}, "skipped, outputs were given")
    else:
        try:
            plan, usage = agents.plan(doc_name, chunks, allowed, call=call)
            plan["depth"] = depth or plan["depth"]
            record("plan", "fast", _ms(step_started), usage, plan["reason"][:120])
        except Exception as exc:  # noqa: BLE001 - a bad step must not end the run
            plan = {
                "outputs": allowed,
                "depth": depth or "standard",
                "reason": f"planner unavailable, producing all outputs ({exc})",
            }
            record("plan", "fast", _ms(step_started), {}, "fallback: all outputs")

    # --- Step 4: write, critique, repair - once per output -----------------
    results: dict[str, dict] = {}
    for output in plan["outputs"]:
        emit(output, f"Writing the {output}")
        results[output] = _produce(
            output=output,
            context=context,
            depth=plan["depth"],
            call=call,
            record=record,
            emit=emit,
        )

    # --- Step 5: translation, if asked for --------------------------------
    translation = None
    if translate_to:
        emit("translate", f"Translating into {translate_to}")
        step_started = time.perf_counter()
        source_text = _translation_source(results, text)
        try:
            translated = translate_fn(source_text, target_language=translate_to)
            ok, problems = schemas.validate(
                "translation", {"language": translate_to, "text": translated}
            )
            translation = {
                "language": translate_to,
                "text": translated,
                "status": "ok" if ok else "failed",
                "error": None if ok else "; ".join(problems),
            }
            record(
                "translate",
                config.TRANSLATE_MODEL,
                _ms(step_started),
                {},
                f"{len(translated)} characters",
            )
        except Exception as exc:  # noqa: BLE001 - never kill a run
            translation = {
                "language": translate_to,
                "text": "",
                "status": "failed",
                "error": str(exc),
            }
            record("translate", config.TRANSLATE_MODEL, _ms(step_started), {}, f"failed: {exc}")

    # --- Step 6: package ---------------------------------------------------
    # Judge the run on what the user can actually use, not on the critic's
    # opinion: a draft that shipped flagged is still a draft they can read.
    produced = [name for name, r in results.items() if r["object"] is not None]
    clean = [name for name, r in results.items() if r["status"] == "ok"]
    if not produced:
        status = "failed"
    elif len(clean) != len(results) or (translation and translation["status"] != "ok"):
        status = "partial"
    else:
        status = "ok"

    run_record = {
        "id": run_id,
        "doc_name": doc_name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "words": words,
        "chunks": len(chunks),
        "plan": plan,
        "outputs": results,
        "translation": translation,
        "trace": trace,
        "usage": {
            "prompt_tokens": usage_total["prompt_tokens"],
            "completion_tokens": usage_total["completion_tokens"],
            "cost_inr": usage_total["cost_inr"],
            "calls": len([row for row in trace if row["model"] not in ("-", "")]),
        },
        "duration_ms": _ms(started),
        "status": status,
    }

    emit("done", f"Finished with status: {status}")
    return run_record


def _produce(output: str, context: str, depth: str, call, record, emit) -> dict:
    """Write one output, then let the critic send it back until it passes.

    Returns {"object", "score", "defects", "rounds", "status", "error"}.
    """
    step_started = time.perf_counter()
    rounds = 0
    feedback = ""
    best: dict | None = None
    best_score = 0
    defects: list[str] = []

    try:
        draft, usage = agents.write(
            output=output,
            chunk=context,
            part=1,
            parts=1,
            depth=depth,
            feedback="",
            call=call,
        )
        record(output, schemas.spec(output)["model"], _ms(step_started), usage, "first draft")
    except Exception as exc:  # noqa: BLE001 - a bad step must not end the run
        return _failed(output, f"writer failed: {exc}")

    while True:
        # Our own shape check runs first: a draft that breaks the schema cannot
        # be fixed by a critic that only reads prose.
        ok, problems = schemas.validate(output, draft)
        if not ok:
            defects = problems
            record(output, "schema", 0, {}, f"invalid shape: {problems[0]}")
        else:
            step_started = time.perf_counter()
            try:
                verdict, usage = agents.critique(output, draft, context, call=call)
                defects = verdict["defects"]
                score = verdict["score"]
                record(
                    output,
                    "critique",
                    _ms(step_started),
                    usage,
                    f"score {score}/5, {len(defects)} defects",
                )
            except Exception as exc:  # noqa: BLE001 - a bad step must not end the run
                # No critic available: ship the draft, but say so honestly.
                record(output, "critique", _ms(step_started), {}, f"unavailable: {exc}")
                return {
                    "object": draft,
                    "score": None,
                    "defects": [],
                    "rounds": rounds,
                    "status": "unverified",
                    "error": f"critic unavailable: {exc}",
                }

            if score > best_score:
                best, best_score = draft, score
            if score >= config.PASS_SCORE:
                return {
                    "object": draft,
                    "score": score,
                    "defects": [],
                    "rounds": rounds,
                    "status": "ok",
                    "error": None,
                }

        if rounds >= config.MAX_REPAIRS:
            # Out of repairs. Ship the best draft, flagged, never silently.
            emit(output, f"{output}: stopping after {rounds} repairs")
            return {
                "object": best or draft,
                "score": best_score or None,
                "defects": defects,
                "rounds": rounds,
                "status": "flagged",
                "error": "below the quality bar after repairs; review before use",
            }

        rounds += 1
        emit(output, f"{output}: repairing, round {rounds}")
        step_started = time.perf_counter()
        feedback = "\n".join(f"- {d}" for d in defects) or "- the shape was invalid"
        try:
            draft, usage = agents.write(
                output=output,
                chunk=context,
                part=1,
                parts=1,
                depth=depth,
                feedback=feedback,
                call=call,
            )
            record(output, schemas.spec(output)["model"], _ms(step_started), usage, f"round {rounds}")
        except Exception as exc:  # noqa: BLE001 - a bad step must not end the run
            if best:
                return {
                    "object": best,
                    "score": best_score,
                    "defects": defects,
                    "rounds": rounds,
                    "status": "flagged",
                    "error": f"repair failed, shipping the best draft: {exc}",
                }
            return _failed(output, f"repair failed: {exc}")


def _failed(output: str, error: str) -> dict:
    """The record for an output that never got produced."""
    return {
        "object": None,
        "score": None,
        "defects": [],
        "rounds": 0,
        "status": "failed",
        "error": error,
    }


def group_chunks(
    chunks: list[str],
    window: int | None = None,
    max_groups: int | None = None,
) -> list[str]:
    """Pack chunks into a few big groups for extraction.

    One call per chunk is wasteful on a short document: 3,000 words fit in a
    single call. Groups are packed up to "window" characters, and if there are
    still more than "max_groups" of them, evenly spaced groups are kept so the
    beginning, middle and end of a long document are all represented.
    """
    window = window or config.EXTRACT_WINDOW
    max_groups = max_groups or config.MAX_EXTRACT_CALLS

    groups: list[str] = []
    current = ""
    for chunk in chunks:
        candidate = f"{current}\n\n{chunk}" if current else chunk
        if len(candidate) <= window:
            current = candidate
        else:
            if current:
                groups.append(current)
            current = chunk
    if current:
        groups.append(current)

    if len(groups) > max_groups and max_groups > 1:
        # Evenly spaced picks, always including the first and the last group,
        # so a long document never loses its conclusion.
        last = len(groups) - 1
        picks = [round(index * last / (max_groups - 1)) for index in range(max_groups)]
        groups = [groups[index] for index in dict.fromkeys(picks)]

    return groups


def build_context(chunks: list[str], facts: list[str], numbers: list[str]) -> str:
    """What the writers see: the facts first, then as much raw text as fits.

    Facts come first so that if the text is truncated, the evidence survives
    the cut and the writer is still grounded.
    """
    parts: list[str] = []
    if facts:
        parts.append("FACTS FROM THE DOCUMENT:\n" + "\n".join(f"- {f}" for f in facts))
    if numbers:
        parts.append("NUMBERS, EXACTLY AS WRITTEN:\n" + "\n".join(f"- {n}" for n in numbers))
    parts.append("SOURCE TEXT:\n" + "\n\n".join(chunks))

    context = "\n\n".join(parts)
    return context[:MAX_CONTEXT_CHARS]


def _translation_source(results: dict, text: str) -> str:
    """Translate the summary if there is one, otherwise the document itself."""
    summary = results.get("summary", {}).get("object")
    if summary and summary.get("summary"):
        return str(summary["summary"])
    return text[:2000]


def _ms(started: float) -> int:
    """Milliseconds since a perf_counter reading, rounded."""
    return int((time.perf_counter() - started) * 1000)
