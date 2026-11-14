"""Fix letter-only MCQ options — part A (module helpers + alignment call).

Root cause proven from the live DB: the local model sometimes returns
options: ['A','B','C','D'] with correct: 'C' — copying the schema shorthand in
the prompt. Validation only counted options, so the garbage was stored and the UI
faithfully rendered four empty choices.
"""

import pathlib

BACKEND = pathlib.Path("/Users/aryanchaubey/Desktop/KnowGraph-AI/backend")


def patch(path: pathlib.Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"PATTERN NOT FOUND in {path.name}:\n{old[:200]}")
    path.write_text(text.replace(old, new, 1))
    print(f"  patched {path.name}")


quiz = BACKEND / "services" / "quiz_service.py"

OLD_ALIGN = '''            # Align correct_answer with the stripped options: it may arrive as
            # "B. Consistency" (letter prefix) or as the raw option text.
            letter_match = re.match(r"^([A-Ja-j])[.)]\\s+(.*)$", correct)
            if letter_match:
                letter = letter_match.group(1).upper()
                for original, cleaned in zip(raw_options, cleaned_options):
                    original_letter = re.match(r"^([A-Ja-j])[.)]", original)
                    if original_letter and original_letter.group(1).upper() == letter:
                        correct = cleaned
                        break
                else:
                    correct = letter_match.group(2)
            else:
                for original, cleaned in zip(raw_options, cleaned_options):
                    if original != cleaned and (correct in original or original in correct):
                        correct = cleaned
                        break
'''

NEW_ALIGN = '''            correct = align_mcq_answer(raw_options, cleaned_options, correct)
            if q_type == "mcq" and not valid_mcq_options(cleaned_options):
                # The model sent labels instead of answer texts (or nothing).
                # Reject it so `generate()` backfills a deterministic question.
                logger.info("Rejecting malformed MCQ options: %r", raw_options[:4])
                return None
'''

patch(quiz, OLD_ALIGN, NEW_ALIGN)

HELPERS = '''#: A single letter is an option *label*, never option *content*.
OPTION_LETTER = re.compile(r"^[A-Ja-j]$")


def is_option_letter(text) -> bool:
    """True when a string is just an option label like "A" or "c"."""
    return bool(OPTION_LETTER.match(str(text or "").strip()))


def align_mcq_answer(raw_options, cleaned_options, correct: str) -> str:
    """Align `correct_answer` with the cleaned option list.

    Handles every shape a small local model produces: letter prefixes on the
    options ("B. Consistency"), a bare-letter answer ("B") with full-text
    options (mapped onto the matching option), and already-clean input.
    """
    options_text = [str(option).strip() for option in cleaned_options]
    correct = (correct or "").strip()

    letter_match = re.match(r"^([A-Ja-j])[.)]\\s+(.*)$", correct)
    if letter_match:
        letter = letter_match.group(1).upper()
        for original, cleaned in zip(raw_options, options_text):
            original_letter = re.match(r"^([A-Ja-j])[.)]", str(original).strip())
            if original_letter and original_letter.group(1).upper() == letter:
                return cleaned
        return letter_match.group(2).strip()

    if len(correct) == 1 and correct.isalpha():
        index = ord(correct.upper()) - ord("A")
        if 0 <= index < len(options_text):
            return options_text[index]
        return correct

    for original, cleaned in zip(raw_options, options_text):
        if original != cleaned and (correct in str(original) or str(original) in correct):
            return cleaned
    return correct


def valid_mcq_options(options) -> bool:
    """An MCQ option list is usable only when it holds real answer texts."""
    texts = [str(option).strip() for option in (options or [])]
    return len(texts) >= 2 and any(len(text) > 3 for text in texts)


'''

anchor = "#: Excerpts per generation call (prompt size guard).\nMAX_EXCERPTS = 8"
patch(quiz, anchor, HELPERS + anchor)

print("part A applied")