"""
Deterministic concept extraction and cue-phrase relations (brief §9, §25).

The graph must be built by classical algorithms, not by an LLM, so these tests
use fixed study text and assert on exact concepts and typed relations.
"""

from services.concept_extractor import (
    collect_candidates,
    extract_relations,
    filter_relations_to_labels,
)


def _pages(text: str):
    return [(1, text)]


def test_acronym_and_phrase_concepts():
    candidates = collect_candidates(
        _pages(
            "BCNF requires that every determinant is a superkey. "
            "Functional Dependency decides the candidate key. "
            "BCNF is stricter than 3NF."
        )
    )
    labels = {candidate.label for candidate in candidates}
    assert "BCNF" in labels
    assert "3NF" in labels
    bcnf = next(candidate for candidate in candidates if candidate.label == "BCNF")
    assert bcnf.pages == [1]
    assert bcnf.occurrences >= 2


def test_concepts_point_back_to_pages():
    candidates = collect_candidates(
        [
            (1, "Introduction to TCP. TCP uses a congestion window."),
            (2, "TCP congestion control builds on the congestion window idea."),
            (3, "Unrelated page about history."),
        ]
    )
    tcp = next(candidate for candidate in candidates if candidate.label == "TCP")
    assert tcp.pages == [1, 2], "a concept must record every page it appears on"


def test_definition_detection():
    candidates = collect_candidates(
        _pages("BCNF is a normal form where every determinant is a superkey. " * 3)
    )
    bcnf = next(candidate for candidate in candidates if candidate.label == "BCNF")
    assert bcnf.definition, "definition sentences must be captured as evidence"


def test_minimum_occurrences_filters_noise():
    candidates = collect_candidates(_pages("Only one mention of Quixotica exists here."))
    assert "Quixotica" not in {candidate.label for candidate in candidates}


def test_requires_cue_phrase_relation():
    candidates = collect_candidates(
        _pages(
            "BCNF requires knowledge of 3NF. BCNF also requires candidate keys. "
            "BCNF and 3NF are both normal forms."
        )
        * 2
    )
    relations = extract_relations(_pages("BCNF requires knowledge of 3NF. " * 2), candidates)
    requires_edges = [rel for rel in relations if rel.relation == "requires"]
    assert requires_edges, "cue phrases must produce typed edges"
    assert all(rel.method == "cue_phrase" for rel in requires_edges)
    for rel in relations:
        assert rel.relation in (
            "related_to", "prerequisite_of", "part_of", "explains",
            "requires", "example_of", "contrasts_with",
        ), "only the brief's vocabulary may be used"


def test_cooccurrence_relation_with_evidence():
    candidates = collect_candidates(
        _pages(
            "TCP and Routing appear together in networks. "
            "TCP and Routing are taught with packets. "
            "Separate sentence about gardens."
        )
        * 2
    )
    relations = extract_relations(
        _pages(
            "TCP and Routing appear together in networks. "
            "TCP and Routing are taught with packets. "
        )
        * 2,
        candidates,
    )
    co = [rel for rel in relations if rel.method == "cooccurrence"]
    assert co, "repeated co-occurrence must produce related_to edges"
    assert co[0].page_number == 1


def test_relations_filtered_to_kept_labels():
    from services.concept_extractor import RelationCandidate

    relations = [
        RelationCandidate(source="BCNF", target="3NF", relation="requires"),
        RelationCandidate(source="BCNF", target="Ghost", relation="requires"),
    ]
    kept = filter_relations_to_labels(relations, ["BCNF", "3NF"])
    assert len(kept) == 1
    assert kept[0].target == "3NF"


# ---------------------------------------------------------------------------
# Concept quality gates — every case below was observed on a real uploaded PDF.
# ---------------------------------------------------------------------------
def _labels(pages):
    return {candidate.label for candidate in collect_candidates(pages)}


def _lower_labels(pages):
    return {label.lower() for label in _labels(pages)}


def test_phrase_is_built_only_from_adjacent_words():
    """
    A table of job labels ("Job A Job B / Job E Job F") used to produce "job job"
    and "job job job" as concepts, because stopwords were stripped *before* the
    n-grams were formed and the words either side then looked adjacent.
    """
    pages = _pages("Job A Job B Job E Job F Job E Job G Job Scheduling runs nightly." * 2)
    labels = _lower_labels(pages)
    assert "job job" not in labels
    assert "job job job" not in labels
    assert "job scheduling" in labels, "real adjacent phrases must still be found"


def test_shouted_ordinary_words_are_not_acronyms():
    """Slides shout table headers and emphasis; that is typography, not an acronym."""
    pages = [
        (1, "TOP HALF Speed Completeness Memory"),
        (2, "The greedy logic fails when confronting a false peak, so the GREEDY choice is myopic."),
        (3, "A breadth-first traversal such as BFS explores the graph level by level for review."),
    ]
    labels = _labels(pages)
    assert not {"TOP", "HALF", "GREEDY", "THE"} & labels
    assert "BFS" in labels, "real acronyms used in running text must still be found"


def test_case_variants_merge_into_one_concept():
    """One concept must not appear twice because two passes found it in different case."""
    pages = _pages(
        "Hill Climbing is a greedy local search algorithm that always moves uphill. "
        "The hill climbing method is memory efficient and simple to implement."
    )
    matching = [label for label in _labels(pages) if label.lower() == "hill climbing"]
    assert matching == ["Hill Climbing"], "the best-cased form must win, once"


def test_running_footer_is_not_a_concept():
    """A footer stamped on every page was previously the highest scoring concept."""

    def page(number, body):
        return (number, f"{body}\nGemini Notebook")

    pages = [
        page(1, "Greedy optimization picks the best immediate step at every stage."),
        page(2, "Greedy optimization can stall on a plateau and needs a restart."),
        page(3, "A plateau is flat terrain where greedy optimization sees no gain."),
        page(4, "Greedy optimization is fast but incomplete on hard instances."),
    ]
    labels = _lower_labels(pages)
    assert "gemini notebook" not in labels
    assert any("greedy" in label for label in labels), "the body text must survive"


def test_heading_label_is_not_a_concept():
    """A section title ("The Upgrade: ...") is a caption, not an explained concept."""
    pages = _pages(
        "The Upgrade: Random-Restart Hill Climbing restarts from new start states.\n"
        "The Upgrade: Simulated Annealing is a probabilistic variant of local search.\n"
        "Random-Restart Hill Climbing keeps the best result found so far."
    )
    labels = _labels(pages)
    assert "Upgrade" not in labels
    assert "Hill Climbing" in labels, "a concept in the same heading must survive"


def test_definition_found_mid_sentence_across_wrapped_lines():
    """
    Definitions were missed entirely before: the old code gave up on the first
    mentioning sentence and only matched a term at the *start* of a sentence.
    """
    pages = [
        (
            2,
            "The Advantage: Unlike systematic search\nalgorithms (A* or BFS), "
            "Hill Climbing is incredibly\nmemory efficient.\n"
            "Hill Climbing never stores a search tree, so it needs very little memory.",
        )
    ]
    candidate = next(c for c in collect_candidates(pages) if c.label == "Hill Climbing")
    assert candidate.definition, "a mid-sentence definition must be captured"
    assert "memory efficient" in candidate.definition
    assert candidate.definition.startswith("Unlike"), "the slide heading prefix is trimmed"


def test_fragment_of_a_longer_phrase_is_pruned():
    """'third normal' and 'third normal form' are one concept, not two nodes."""
    pages = _pages(
        "Third Normal Form is a normal form that removes transitive dependencies. " * 3
    )
    labels = _lower_labels(pages)
    assert "third normal form" in labels
    assert "third normal" not in labels
