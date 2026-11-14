"""Fix letter-only MCQ options — part B (validation + prompt)."""

import pathlib

BACKEND = pathlib.Path("/Users/aryanchaubey/Desktop/KnowGraph-AI/backend")


def patch(path: pathlib.Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"PATTERN NOT FOUND in {path.name}:\n{old[:200]}")
    path.write_text(text.replace(old, new, 1))
    print(f"  patched {path.name}")


quiz = BACKEND / "services" / "quiz_service.py"

# Reject a question at construction time when it cannot be answered.
patch(
    quiz,
    '''        if q_type == "mcq" and len(options) < 2:
            return None''',
    '''        if q_type == "mcq" and not valid_mcq_options(options):
            return None
        if q_type == "mcq" and correct and is_option_letter(correct):
            return None''',
)

# Same rule for anything already stored / coming from the model.
patch(
    quiz,
    '''        return bool(
            question
            and question.get("question")
            and question.get("correct_answer")
            and (question.get("type") != "mcq" or len(question.get("options") or []) >= 2)
        )''',
    '''        if not (question and question.get("question") and question.get("correct_answer")):
            return False
        if question.get("type") == "mcq":
            if not valid_mcq_options(question.get("options")):
                return False
            if is_option_letter(question.get("correct_answer")):
                return False
        return True''',
)

# Prompt: stop the model copying the schema shorthand.
patch(
    BACKEND / "services" / "llm" / "prompts.py",
    "For short_answer questions use an empty options array and a one-line correct_answer.",
    "For short_answer questions use an empty options array and a one-line correct_answer.\n"
    "RULES FOR mcq options - read carefully:\n"
    "1. options MUST be full answer texts, NEVER single letters like [\"A\", \"B\", \"C\", \"D\"].\n"
    "2. correct_answer MUST be the full text of the correct option, NEVER a bare letter like \"C\".\n"
    "3. Do NOT prefix options with letters (\"A. ...\"): write the plain texts.",
)

print("part B applied")
