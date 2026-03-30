#!/usr/bin/env python3
"""
Classify extracted questions into 6 Areas of Study using keyword matching.
Reads raw_questions.json, outputs questions.json.

Priority order (first match wins):
  1. Probability and Statistics
  2. Complex Numbers
  3. Vectors (strong signals checked BEFORE calculus to prevent particle/i/j/k misclassification)
  4. Sketch/graph → Functions (only if no real calculus operations)
  5. Logic and Proof
  6. Calculus
  7. Functions, Relations and Graphs (positive signal required)
  8. Unsorted (fallback — never guess)

Key improvements over v1:
  - strip_header(): discards copyright header text before "Question N"
  - has_vector_ijk(): detects j/k unit vectors → prevents false Complex triggers
  - Particle disambiguation: particle + "straight line" → Calculus; particle alone → Vectors
  - VECTORS_STRONG_KW checked before Calculus
  - Unsorted (aos=0) is the fallback instead of Functions
  - Manually reviewed publisher/year sets are preserved from existing questions.json
"""

import json
import re
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("--subject", choices=["specialist", "methods"], required=True,
                    help="Which subject to classify")
args = parser.parse_args()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RAW_JSON = os.path.join(BASE, f"raw_questions_{args.subject}.json")
OUT_JSON = os.path.join(BASE, "questions.json" if args.subject == "specialist" else "methods_questions.json")
EXISTING_JSON = OUT_JSON  # same file — we load before overwriting

# Publisher/year sets that have been manually reviewed — preserve their classifications (specialist only)
MANUALLY_REVIEWED = {
    ("Sequoia", 2025),
    ("Heffernan", 2025),
    ("MAV", 2025),
}

SPECIALIST_AOS = {
    0: "Unsorted",
    1: "Logic and Proof",
    2: "Functions, Relations and Graphs",
    3: "Complex Numbers",
    4: "Calculus",
    5: "Vectors, Lines and Planes",
    6: "Probability and Statistics",
    7: "Pseudocode",
}

METHODS_AOS = {
    0: "Unsorted",
    1: "Algebra and Functions",
    2: "Differentiation",
    3: "Integration",
    4: "Discrete Probability",
    5: "Continuous Probability",
    6: "Core Content",                # Exam 2 only
    7: "Probability and Statistics",  # Exam 2 only
    8: "Pseudocode",                  # Exam 1 only
}

AOS = SPECIALIST_AOS if args.subject == "specialist" else METHODS_AOS

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

PSEUDOCODE_KW = [
    r"pseudocode",
    r"written in pseudocode",
    r"the following pseudocode",
    r"the following algorithm",
    r"consider the following algorithm",
    r"consider\s+the\s+algorithm",  # "Consider the algorithm implemented with..."
    r"declare\s+integer",    # pseudocode variable declarations
    r"←\s*\w",              # assignment arrow common in pseudocode
    r"\bfor\s+\w+\s+from\b", # "for n from 1 to 3" pseudocode loop
    r"\bwhile\s+\w+\s*[<>]", # while loop pseudocode
]

PROB_STATS_KW = [
    r"hypothesis", r"null\s+hypothesis", r"p[\-\s]?value",
    r"confidence\s+interval", r"confidence\s+level",
    r"margin\s+of\s+error",
    r"normally\s+distributed", r"normal\s+distribution",
    r"standard\s+deviation", r"probability\s+density",
    r"continuous\s+random", r"discrete\s+random",
    r"binomial", r"probability\s+distribution",
    r"random\s+variable", r"sample\s+mean",
    r"population\s+mean", r"standard\s+error",
    r"level\s+of\s+significance", r"significance\s+level",
    r"sampling\s+distribution",
    r"z[\-\s]?score", r"expected\s+value",
    r"e\s*\(\s*x\s*\)", r"var\s*\(",
    r"\bprobability\b",
    # removed: proportion, survey (too broad — fire on DE/modelling questions)
]

LOGIC_PROOF_KW = [
    r"mathematical\s+induction", r"prove\s+by\s+induction",
    r"\binduction\b", r"inductive\s+step", r"base\s+case",
    r"\bcontradiction\b", r"proof\s+by\s+contradiction",
    r"prove.*irrational",
    r"contrapositive", r"contra[\-\s]?positive",
    r"prove\s+that", r"\bproof\b", r"divisib",
    r"if\s+and\s+only\s+if", r"\bconverse\b",
    r"for\s+all\s+integers", r"for\s+all\s+positive",
    r"for\s+all\s+natural",
    r"truth\s+table", r"tautology",
    r"counter[\-\s]?example",
    r"logical\s+equivalen",
    r"necessary\s+and\s+sufficient",
    r"direct\s+proof",
    r"consider\s+the\s+following\s+statement",
    r"consider\s+the\s+following\s+claim",
    r"negation\s+of\s+the\s+statement",  # "The negation of the statement '...' is"
    r"for\s+all\s+n\s*[∈]",        # "for all n ∈ Z" — induction/proof language
    r"let\s+n\s+be\s+an?\s+integer",
    r"n\s+is\s+an?\s+integer",
]

# Strong, unambiguous complex number signals
COMPLEX_STRONG_KW = [
    r"complex\s+number", r"complex\s+plane",
    r"argand", r"de\s+moivre", r"demoivre",
    r"roots\s+of\s+unity", r"nth\s+root.*complex",
    r"complex\s+root", r"complex\s+conjugate",
    r"polar\s+form", r"modulus[\-\s]+argument",
    r"\bcis\s*\(",
    r"\|z\|", r"principal\s+argument",
    r"locus", r"loci",
    r"factor.*over\s+c", r"factoris.*over\s+c",
    r"imaginar",
    r"\bz\s*=\s*x\s*\+\s*y\s*i",
    r"rectangular\s+form",
    r"\bz\s*[∈]\s*c",
    r",\s*z\s*∈\s*c",
    r"where\s+z\s+c\b",
    r"\bz\s*c\s*[,.]",
    r"polynomial.*\bz\b",
    r"\bp\s*\(\s*z\s*\)",
    r"\barg\s*\(",                 # arg(z) — complex argument function
    r"x\s*\+\s*i\s*y\b",          # "x + iy" form (common alternative to a + bi)
]

# Weaker complex signals — only used when NO vector i/j/k context is present
COMPLEX_WEAK_KW = [
    r"\d\s*i\b",               # "3i", "2i"
    r"[+-]\s*\d*i\b",          # "+2i", "-i"
    r"a\s*\+\s*b\s*i\b",      # "a + bi"
    r"a\s*[+-]\s*bi\b",        # "a+bi", "a-bi"
    r"form\s+.*[+-].*i\b",    # "in the form ... + ... i"
    r"real\s+part",
    r"\bz\b",                   # standalone z → likely complex variable
    r"\bz\b.*\bi\b.*[+-]",
    r"[+-].*\bi\b.*\bz\b",
]

# Strong vector signals — checked BEFORE calculus
VECTORS_STRONG_KW = [
    r"position\s+vector", r"unit\s+vector",
    r"dot\s+product", r"scalar\s+product",
    r"cross\s+product", r"vector\s+product",
    r"magnitude.*vector", r"vector.*magnitude",
    r"scalar\s+resolute", r"vector\s+resolute",
    r"equation\s+of.*plane", r"cartesian\s+equation.*plane",
    r"normal\s+to.*plane",
    r"intersection.*plane", r"angle.*between.*plane",
    r"skew\s+lines", r"direction\s+vector",
    r"perpendicular.*vector", r"projection.*vector",
    r"parallel.*vector",
    r"linear.*independent", r"linear.*dependent",
    r"parametric.*equation.*line",
    r"\bi\s*[\+\-].*\bj\b",    # "2i + 3j" — vector component form
    r"\bj\s*[\+\-].*\bk\b",    # "j + k"
    r"angle\s+between\s+.*vectors?",    # "angle between the vectors"
    r"area\s+of\s+(?:the\s+)?triangle", # cross product to find triangle area with 3D vertices
]

# Plane-specific keywords — checked BEFORE Complex weak to prevent z-variable false trigger.
# Must be specific enough not to fire on Complex questions that mention "plane".
PLANES_KW = [
    r"two\s+planes?",                        # "two planes" — specific to Vectors context
    r"angle\s+between\s+(?:the\s+)?planes?", # "angle between the planes"
    r"distance\s+\w.*\bplane\b",             # "distance from point to plane"
    r"closest\s+\w.*\bplane\b",              # "closest point on the plane"
    r"perpendicular\s+planes?",              # "perpendicular planes"
    r"area\s+of\s+(?:the\s+)?triangle",      # cross-product triangle area (no .* wildcard)
]

# Broader vector signals (used after calculus check)
VECTORS_KW = VECTORS_STRONG_KW + [
    r"\bvectors?\b",            # "vector" or "vectors"
    r"equation\s+of.*line",
]

# Graph-feature keywords that appear naturally in sketch-graph questions
# and should NOT alone push a question into Calculus
GRAPH_FEATURE_KW = [
    r"stationary\s+point", r"turning\s+point",
    r"maximum.*minimum", r"inflection", r"concav",
]

CALCULUS_KW = [
    r"differentiat", r"derivative", r"dy\s*/\s*dx", r"dy\s*dx",
    r"\bgradient\b",
    r"integra", r"∫", r"anti[\-\s]?derivat",
    r"\bdx\b",
    r"\bevaluate\b",                       # "evaluate the integral"
    r"chain\s+rule", r"product\s+rule", r"quotient\s+rule",
    r"implicit.*differentiat", r"related\s+rate",
    r"rate\s+of\s+change",
    r"tangent\s+line", r"tangent\s+to",
    r"normal\s+to.*curve",
    *GRAPH_FEATURE_KW,
    r"differential\s+equation",
    r"euler.*method", r"slope\s+field", r"direction\s+field",
    r"particular\s+solution", r"general\s+solution",
    r"logistic", r"separab",
    r"velocity", r"accelerat",  # covers acceleration, accelerates, accelerating
    r"moving\s+in\s+a\s+straight\s+line",  # unambiguous 1D kinematics
    r"rectilinear\s+motion",
    r"\bspeed\b", r"distance\s+travel", r"travel.*distance",
    r"metres?\s+per\s+second", r"km\s*/\s*h", r"m\s*/\s*s",
    r"area\s+between", r"area\s+under", r"area\s+bound",
    r"volume\s+of\s+revolution", r"rotat\w*\s+(about|around)",  # rotating/rotated about/around
    r"about\s+the\s+[xy][\-\s]?axis",  # "about the y-axis" even when formula splits "rotating"
    r"surface\s+area\s+of\s+revolution",
    r"arc\s+length",
    r"newton.*method",
    r"limit\b", r"l'h.pital",
    r"rate\s+at\s+which",       # "rate at which the surface area increases" (related rates)
    r"with\s+respect\s+to\s+time",  # dV/dt, dh/dt problems
    r"suitable\s+substitution", # integration by substitution
    # removed: partial fraction (fires on Logic questions), volume alone (too broad),
    #          surface area alone (too broad), displacement (fires on Vectors 2D/3D)
]

# "Core" calculus — excludes graph-feature words so sketch-graph → Functions
CALCULUS_CORE_KW = [kw for kw in CALCULUS_KW if kw not in GRAPH_FEATURE_KW]

FUNCTIONS_KW = [
    r"asymptote", r"rational\s+function",
    r"inverse\s+function", r"one[\-\s]?to[\-\s]?one",
    r"transformation", r"dilation", r"translation",
    r"\bdomain\b", r"\brange\b",
    r"composite\s+function",
    r"graphs?\s+of", r"sketch.*graph", r"sketch.*curve",  # "graph of" or "graphs of"
    r"modulus\s+function", r"absolute\s+value",
    r"piecewise", r"hybrid\s+function",
    r"ellipse", r"hyperbola",
    r"trigonometric\s+identit", r"trig.*identit",
    r"double\s+angle", r"compound\s+angle",
    r"parametric",
    r"\bsolve\s+the\s+equation\b",  # trig equation solve questions
    r"\bcosec\b", r"\bcsc\b",       # reciprocal trig — common in Functions questions
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def strip_header(text):
    """
    Remove publisher copyright header that precedes "Question N".
    Returns the trimmed text, or the original if no question marker found.
    """
    m = re.search(r"\bquestion\s+\d+\b", text, re.IGNORECASE)
    if m:
        return text[m.start():]
    return text


def has_match(text, keywords):
    for kw in keywords:
        if re.search(kw, text):
            return True
    return False


def has_vector_ijk(text):
    """
    Returns True if the text contains vector unit vector notation (j or k),
    which indicates this is a Vectors question, not a Complex Numbers question.
    The imaginary unit i is also used in vectors as a unit vector.
    """
    # \bj\b or \bk\b appearing as a variable (not in words like "just", "keep")
    if re.search(r"\bj\b", text):
        return True
    if re.search(r"\bk\b", text):
        return True
    # explicit vector notation: "i + j", "2i - 3j + k", etc.
    if re.search(r"\bi\b.*\bj\b|\bj\b.*\bi\b", text):
        return True
    return False


def classify_question(text):
    if not text or not text.strip():
        return 0, AOS[0]

    # Strip publisher copyright header before classifying
    text = strip_header(text)
    t = text.lower()

    # 0. Pseudocode — detected first, very distinct question type
    if has_match(t, PSEUDOCODE_KW):
        return 7, AOS[7]

    # 1. Probability and Statistics
    if has_match(t, PROB_STATS_KW):
        return 6, AOS[6]

    # 2. Complex Numbers
    #    Strong signals always win; weak signals (numeric i, standalone z) only win
    #    if there is no vector i/j/k context.
    if has_match(t, COMPLEX_STRONG_KW):
        return 3, AOS[3]
    # Plane keywords checked BEFORE complex weak — a z variable in a plane equation
    # (e.g. "2x + 3y + z = 8") must not trigger the \bz\b complex weak keyword.
    # Exclude questions that are primarily Logic/Proof (multi-part questions may mention
    # triangle area in a sub-part but the question is fundamentally about proof).
    if has_match(t, PLANES_KW) and not has_match(t, LOGIC_PROOF_KW):
        return 5, AOS[5]
    is_vector_ijk = has_vector_ijk(t)
    if not is_vector_ijk and has_match(t, COMPLEX_WEAK_KW):
        return 3, AOS[3]

    # 3. Strong vector signals — checked BEFORE calculus so that questions about
    #    particles in 2D/3D, position vectors, etc. are not stolen by Calculus.
    if has_match(t, VECTORS_STRONG_KW):
        return 5, AOS[5]

    # 4. Particle disambiguation
    #    "particle moving in a straight line" → Calculus (1D kinematics)
    #    "particle" alone (2D/3D context) → Vectors
    if re.search(r"\bparticle\b", t):
        if re.search(r"straight\s+line|rectilinear", t):
            return 4, AOS[4]
        else:
            return 5, AOS[5]

    # 5. Displacement / position — check for 2D/3D context → Vectors
    #    Only send to Calculus if clearly 1D (straight-line motion)
    if re.search(r"\bdisplacement\b", t):
        if re.search(r"straight\s+line|rectilinear|1d\b|one.dimension", t):
            return 4, AOS[4]
        if is_vector_ijk:
            return 5, AOS[5]
        # ambiguous displacement — fall through to keyword matching below

    # 6. Sketch/graph → Functions (unless real calculus operations are involved)
    is_graph = bool(re.search(r"sketch.*graph|graph.*sketch|sketch.*curve", t))
    if is_graph and not has_match(t, CALCULUS_CORE_KW):
        return 2, AOS[2]

    # 7. Logic and Proof
    if has_match(t, LOGIC_PROOF_KW):
        # If calculus/vectors also present, those win
        if has_match(t, CALCULUS_CORE_KW):
            return 4, AOS[4]
        if has_match(t, VECTORS_KW):
            return 5, AOS[5]
        return 1, AOS[1]

    # 8. Calculus
    if has_match(t, CALCULUS_KW):
        return 4, AOS[4]

    # 9. Vectors (broader signals)
    if has_match(t, VECTORS_KW):
        return 5, AOS[5]

    # 9b. i/j/k unit vector notation present but no keyword matched — likely a
    #     Vectors question with garbled PDF text (e.g. formulae split across lines).
    #     Only trigger when BOTH j and k are present (single k could be a constant).
    if re.search(r"\bj\b", t) and re.search(r"\bk\b", t):
        return 5, AOS[5]

    # 10. Functions (positive signal required — no longer a fallback)
    if has_match(t, FUNCTIONS_KW):
        return 2, AOS[2]

    # 11. Unsorted — genuinely unclear, needs manual review
    return 0, AOS[0]


# ---------------------------------------------------------------------------
# Methods keyword sets
# ---------------------------------------------------------------------------

METHODS_CONTINUOUS_PROB_KW = [
    r"continuous\s+random\s+variable",
    r"probability\s+density\s+function",
    r"\bpdf\b",
    r"probability\s+density",
    r"normally\s+distributed",   # "X is normally distributed with mean..."
    r"normal\s+distribution",    # "follows a normal distribution"
    r"standard\s+normal",        # "standard normal distribution"
]

METHODS_DISCRETE_PROB_KW = [
    r"discrete\s+random\s+variable",
    r"binomial\s+distribution",
    r"bernoulli",
    r"probability\s+mass\s+function",
    r"\bpmf\b",
    r"sampling\s+distribution",
    r"confidence\s+interval",
    r"margin\s+of\s+error",
    r"level\s+of\s+significance",
    r"significance\s+level",
    r"hypothesis",
    r"p[\-\s]?value",
    r"\bpr\s*\(",                # Pr(X = k) notation
    r"x\s*[~∼]\s*b\s*\(",       # X ~ B(n, p) notation
    r"\brandom\s+variable\b",   # "a random variable X has..."
]

# General probability — used to detect exam 2 probability questions
METHODS_PROB_GENERAL_KW = METHODS_CONTINUOUS_PROB_KW + METHODS_DISCRETE_PROB_KW + [
    r"\bprobability\b",
    r"random\s+variable",
    r"expected\s+value",
    r"e\s*\(\s*x\s*\)",
    r"var\s*\(",
    r"normally\s+distributed",
    r"normal\s+distribution",
    r"standard\s+deviation",
    r"binomial",
]

METHODS_INTEGRATION_KW = [
    r"indefinite\s+integral",
    r"definite\s+integral",
    r"anti[\-\s]?derivat",
    r"antiderivat",
    r"∫",
    r"\bdx\b",
    r"area\s+under",
    r"area\s+between",
    r"area\s+bound",
    r"total\s+area",                         # "find the total area enclosed by..."
    r"area\s+of\s+(?:the\s+)?region",        # "the area of the region bounded by..."
    r"net\s+(?:area|change|displacement)",   # net area / net change via integration
    r"average\s+value",
    r"hence.*(?:evaluate|find.*integral|antiderivat)",
    r"find.*antiderivat.*hence",
    r"find.*integral",
    r"integrat",
]

METHODS_DIFF_KW = [
    r"differentiat",
    r"\bderivative\b",
    r"\bd\s*/\s*dx\b",
    r"\bdy\s*/\s*dx\b",
    r"stationary\s+point",
    r"turning\s+point",
    r"maximum.*value",
    r"minimum.*value",
    r"local\s+(?:max|min)",
    r"optimis",        # optimise, optimisation
    r"tangent\s+(?:to|at|line)",
    r"normal\s+to",
    r"average\s+rate\s+of\s+change",
    r"instantaneous\s+rate\s+of\s+change",
    r"rate\s+of\s+change",
    r"gradient\s+of.*(?:curve|function|graph)",
    r"d\s*/\s*dx",
    r"chain\s+rule",
    r"product\s+rule",
    r"quotient\s+rule",
    r"\bincreasing\b",           # "f is increasing on (a, b)"
    r"\bdecreasing\b",           # "f is decreasing on (a, b)"
    r"concav",                   # "concave up", "concave down"
    r"inflect",                  # "point of inflection"
    r"f\s*'\s*\(",               # f'(x) notation in text
]

METHODS_FUNCTIONS_KW = [
    r"inverse\s+function",
    r"composite\s+function",
    r"\bdomain\b",
    r"\brange\b",
    r"transformation",
    r"\bdilation\b",
    r"\btranslation\b",
    r"sketch",
    r"graph\s+of",
    r"graphs?\s+of",
    r"\basymptote\b",
    r"inverse.*function",
    r"one[\-\s]?to[\-\s]?one",
    r"solve.*equation",
    r"solving.*equation",
    r"simultaneous",
    r"\bquadratic\b",
    r"\bpolynomial\b",
    r"exponential.*function",
    r"logarithm",
    r"\blog\b",
    r"trigonometric\s+function",
    r"\bsin\b.*\bfunction\b|\bcos\b.*\bfunction\b|\btan\b.*\bfunction\b",
    r"reflection",
    r"vertical.*asymptote",
    r"horizontal.*asymptote",
    r"turning\s+point",   # graph-feature in a sketch context
]


def classify_for_methods(text, section):
    """
    Classify a Methods question. Returns (primary_aos, primary_name, tags_list, tag_names_list).
    section: 'extended_response' | 'multiple_choice' | 'short_answer'
    """
    if not text or not text.strip():
        return 0, METHODS_AOS[0], [0], [METHODS_AOS[0]]

    text = strip_header(text)
    t = text.lower()

    # Extended response only: binary classification — Core Content vs Probability and Statistics
    if section == 'extended_response':
        if has_match(t, METHODS_PROB_GENERAL_KW):
            return 7, METHODS_AOS[7], [7], [METHODS_AOS[7]]
        return 6, METHODS_AOS[6], [6], [METHODS_AOS[6]]

    # Exam 1 (MCQ + short answer): AOS 1–5 + Pseudocode, multi-tag possible

    # Pseudocode — checked first, very distinct question type (reuses Specialist keywords)
    if has_match(t, PSEUDOCODE_KW):
        return 8, METHODS_AOS[8], [8], [METHODS_AOS[8]]

    is_continuous = has_match(t, METHODS_CONTINUOUS_PROB_KW)
    is_discrete = has_match(t, METHODS_DISCRETE_PROB_KW)
    is_integration = has_match(t, METHODS_INTEGRATION_KW)
    is_diff = has_match(t, METHODS_DIFF_KW)
    is_functions = has_match(t, METHODS_FUNCTIONS_KW)

    # Continuous Probability wins over Integration when both are present
    if is_continuous:
        return 5, METHODS_AOS[5], [5], [METHODS_AOS[5]]

    if is_discrete:
        return 4, METHODS_AOS[4], [4], [METHODS_AOS[4]]

    # Integration (primary), possibly multi-tagged with Differentiation
    if is_integration:
        tags = [3]
        if is_diff:
            tags.append(2)
        return 3, METHODS_AOS[3], tags, [METHODS_AOS[n] for n in tags]

    # Differentiation (primary), possibly multi-tagged with Algebra/Functions
    if is_diff:
        tags = [2]
        # Sketch + stationary point → also tag Functions
        is_sketch = bool(re.search(r"sketch|graph\s+of|draw.*graph", t))
        if is_sketch and is_functions:
            tags.append(1)
        return 2, METHODS_AOS[2], tags, [METHODS_AOS[n] for n in tags]

    # Algebra and Functions — any positive signal
    if is_functions:
        return 1, METHODS_AOS[1], [1], [METHODS_AOS[1]]

    # Unsorted
    return 0, METHODS_AOS[0], [0], [METHODS_AOS[0]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def classify_for_subject(text, subject, section='short_answer'):
    if subject == "methods":
        return classify_for_methods(text, section)
    aos_num, aos_name = classify_question(text)
    return aos_num, aos_name, [aos_num], [aos_name]


def main():
    print(f"Subject: {args.subject}")
    print(f"Reading: {RAW_JSON}")

    with open(RAW_JSON) as f:
        raw = json.load(f)

    # Load existing manual classifications to preserve them
    try:
        with open(EXISTING_JSON) as f:
            existing = json.load(f)
        manual = {q["id"]: q for q in existing}
    except (FileNotFoundError, json.JSONDecodeError):
        manual = {}

    preserve_enabled = args.subject == "specialist"
    print(f"Classifying {len(raw)} questions...")
    if preserve_enabled:
        print(f"Preserving manual classifications for: {sorted(MANUALLY_REVIEWED)}")

    from collections import Counter
    aos_counts = Counter()
    preserved = 0
    reclassified = 0

    output = []
    for q in raw:
        # Merge Insight and Insight Publications
        if "Insight" in q.get("publisher", ""):
            q["publisher"] = "Insight"
            q["id"] = q["id"].replace("insight_publications_", "insight_")

        pub = q.get("publisher", "")
        year = q.get("year", 0)
        qid = q["id"]

        out = {k: v for k, v in q.items() if k not in ("extracted_text", "source_pdf")}

        if preserve_enabled and (pub, year) in MANUALLY_REVIEWED and qid in manual:
            # Preserve the manually reviewed classification
            out["aos"] = manual[qid]["aos"]
            out["aos_name"] = manual[qid]["aos_name"]
            if "tags" in manual[qid]:
                out["tags"] = manual[qid]["tags"]
                out["tag_names"] = manual[qid]["tag_names"]
            preserved += 1
        else:
            section = q.get("section", "short_answer")
            aos_num, aos_name, tags, tag_names = classify_for_subject(
                q.get("extracted_text", ""), args.subject, section
            )
            out["aos"] = aos_num
            out["aos_name"] = aos_name
            if args.subject == "methods":
                out["tags"] = tags
                out["tag_names"] = tag_names
            reclassified += 1

        # Exam 1 is always short answer
        if q.get("exam_type") == 1:
            out["section"] = "short_answer"

        out.pop("topic", None)
        aos_counts[f"{out['aos']}. {out['aos_name']}"] += 1
        output.append(out)

    with open(OUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nPreserved (manual): {preserved}")
    print(f"Reclassified (auto): {reclassified}")
    print(f"\nBy Area of Study:")
    for k, v in sorted(aos_counts.items()):
        print(f"  {k}: {v}")
    print(f"\nTotal: {len(output)} questions")
    print(f"Saved to {OUT_JSON}")


if __name__ == "__main__":
    main()
