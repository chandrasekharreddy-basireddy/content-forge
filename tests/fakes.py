"""A fake model, so the whole pipeline can be tested without an API key.

It reads the messages it is given and returns a plausible reply for that
agent. It is not trying to be clever - it is trying to be deterministic, so a
test that passes today passes tomorrow and on the examiner's laptop.

This file is also the honest answer to "how do you know the critic loop works
if you have no key?" - you run it against this.
"""

import json


class FakeModel:
    """A stand-in for llm.chat with the same signature."""

    def __init__(self, scores: list[int] | None = None, fail_outputs: tuple = ()):
        """
        scores         the critic's scores, handed out in order. Default
                       [3, 5] - reject once, then accept, which is exactly
                       the behaviour the loop is meant to show.
        fail_outputs   output names whose writer should raise, to prove that
                       one bad output does not kill the run.
        """
        self.scores = list(scores or [3, 5])
        self.fail_outputs = fail_outputs
        self.calls: list[dict] = []

    def __call__(self, messages, model=None, json_schema=None, **kwargs):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        self.calls.append({"model": model, "system": system[:60], "user": user[:120]})

        if "You extract evidence" in system:
            return json.dumps(
                {
                    "facts": [
                        "The document has three parts.",
                        "Cost fell in the second half of the year.",
                        "The team shipped a working prototype.",
                    ],
                    "numbers": ["14%", "2025"],
                }
            ), _usage(model, 400, 90)

        if "You are the planner" in system:
            return json.dumps(
                {
                    "outputs": ["summary", "quiz", "flashcards"],
                    "depth": "standard",
                    "reason": "A short factual document supports study material.",
                }
            ), _usage(model, 500, 60)

        if "You are an evaluator" in system:
            return json.dumps(
                {
                    "faithfulness": 4,
                    "coverage": 3,
                    "concision": 5,
                    "reason": "Covers the main points without inventing anything.",
                }
            ), _usage(model, 700, 60)

        if "You are the critic" in system:
            score = self.scores.pop(0) if self.scores else 5
            verdict = "pass" if score >= 4 else "revise"
            defects = (
                []
                if verdict == "pass"
                else ["the second bullet restates the first", "one claim is unsupported"]
            )
            return json.dumps(
                {"score": score, "verdict": verdict, "defects": defects, "reason": "ok"}
            ), _usage(model, 600, 70)

        if "You are the writer" in system:
            output = _output_type(user)
            if output in self.fail_outputs:
                raise RuntimeError(f"writer exploded on {output}")
            return json.dumps(_object_for(output)), _usage(model, 800, 300)

        return json.dumps({"note": "unrecognised prompt"}), _usage(model, 10, 5)


def _output_type(user: str) -> str:
    """The writer prompt states the output type on its own line."""
    for line in user.splitlines():
        if line.startswith("Output type:"):
            return line.split(":", 1)[1].strip()
    return "summary"


def _object_for(output: str) -> dict:
    """A valid object for each output type."""
    if output == "summary":
        return {
            "summary": "A short document describing three things: its own "
            "structure, a fall in cost, and a working prototype.",
            "bullets": [
                "The document is organised in three parts.",
                "Cost fell by 14% in 2025.",
                "A working prototype was shipped.",
                "The team reported results honestly.",
            ],
            "key_terms": ["prototype", "cost", "2025"],
        }
    if output == "quiz":
        return {
            "questions": [
                {
                    "question": "By how much did cost fall?",
                    "options": ["14%", "41%", "4%", "0%"],
                    "answer_index": 0,
                    "explanation": "The document states a 14% fall in 2025.",
                },
                {
                    "question": "What was shipped?",
                    "options": ["A prototype", "A report", "A patent", "A website"],
                    "answer_index": 0,
                    "explanation": "A working prototype is named in the text.",
                },
            ]
        }
    if output == "flashcards":
        return {
            "cards": [
                {"front": "How much did cost fall?", "back": "14% in 2025."},
                {"front": "What was shipped?", "back": "A working prototype."},
            ]
        }
    if output == "report":
        return {
            "title": "Findings",
            "sections": [
                {"heading": "Background", "body": "The document has three parts."},
                {"heading": "Findings", "body": "Cost fell by 14% in 2025."},
            ],
        }
    if output == "slides":
        return {
            "slides": [
                {"title": "Findings", "bullets": ["Cost fell 14%", "Prototype shipped"],
                 "notes": "Two numbers, one conclusion."},
                {"title": "Next", "bullets": ["Measure again", "Report openly"],
                 "notes": "Close on the method."},
            ]
        }
    return {"note": "no fake for this output"}


def _usage(model: str | None, prompt_tokens: int, completion_tokens: int) -> dict:
    """The same usage shape llm.chat returns."""
    return {
        "model": model or "fake",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_inr": round(prompt_tokens / 1_000_000 * 10 + completion_tokens / 1_000_000 * 25, 6),
    }


class FakeTranslator:
    """Stands in for llm.translate: marks the text so a test can see it ran."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, text, target_language="hi-IN", **kwargs):
        self.calls.append({"chars": len(text), "target": target_language})
        return f"[{target_language}] {text}"
