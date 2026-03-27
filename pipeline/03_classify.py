#!/usr/bin/env python3
"""
Classify extracted questions into 6 Areas of Study using keyword matching.
Reads raw_questions.json, outputs questions.json.

Priority order (first match wins):
  1. Probability and Statistics
  2. Complex Numbers (anything involving imaginary i, z ∈ C, argand, etc.)
  3. Sketch/graph → Functions (only if the instruction is to sketch a graph)
  4. Logic and Proof
  5. Calculus (takes precedence if ANY calculus is involved, including kinematics)
  6. Vectors, Lines and Planes
  7. Functions, Relations and Graphs (fallback)

Special rules:
  - Complex numbers: anything involving imaginary number i → Complex
  - Sketch the graph / axes provided → Functions (unless explicit calculus operations)
  - Finding gradient, implicit differentiation → Calculus (not Functions)
  - Kinematics, speed, distance/time → Calculus
  - Volume, arc length, surface area → Calculus
  - Calculus always takes precedence over Vectors when both present
"""

import json
import re

RAW_JSON = "/home/ubuntu/webpage/raw_questions.json"
OUT_JSON = "/home/ubuntu/webpage/questions.json"

AOS = {
    1: "Logic and Proof",
    2: "Functions, Relations and Graphs",
    3: "Complex Numbers",
    4: "Calculus",
    5: "Vectors, Lines and Planes",
    6: "Probability and Statistics",
}

# --- Keyword sets ---

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
    r"proportion", r"survey",
]

LOGIC_PROOF_KW = [
    r"mathematical\s+induction", r"prove\s+by\s+induction",
    r"induction", r"inductive\s+step", r"base\s+case",
    r"contradiction", r"prove.*irrational",
    r"contrapositive", r"contra[\-\s]?positive",
    r"prove\s+that", r"\bproof\b", r"divisib",
    r"if\s+and\s+only\s+if", r"\bconverse\b",
    r"for\s+all\s+integers", r"for\s+all\s+positive",
    r"for\s+all\s+natural",
    r"truth\s+table", r"tautology",
    r"counter[\-\s]?example",
    r"logical\s+equivalen",
    r"necessary\s+and\s+sufficient",
]

COMPLEX_KW = [
    r"complex\s+number", r"complex\s+plane",
    r"argand", r"de\s+moivre", r"demoivre",
    r"roots\s+of\s+unity", r"nth\s+root.*complex",
    r"complex\s+root", r"complex\s+conjugate",
    r"polar\s+form", r"modulus[\-\s]+argument",
    r"arg\s*\(", r"\bcis\s*\(",
    r"\|z\|", r"principal\s+argument",
    r"locus", r"loci",
    r"factor.*over\s+c", r"factoris.*over\s+c",
    r"imaginar", r"real\s+part",
    r"\bz\s*=\s*x\s*\+\s*y\s*i",
    r"\bz\b.*\bc\b.*conjugate",
    r"rectangular\s+form",
    # Detect imaginary unit i in math expressions from PDF extraction
    r"\d\s*i\b",               # "3i", "2i", "2 i" (number followed by i)
    r"[+-]\s*\d*i\b",          # "+2i", "-i", "+i"
    r"a\s*\+\s*b\s*i\b",      # "a + bi", "a + b i"
    r"a\s*[+-]\s*bi\b",       # "a+bi", "a-bi"
    r"form\s+.*[+-].*i\b",    # "in the form ... + ... i"
    r"\bz\s*[∈]\s*c",         # "z ∈ c" (z in C)
    r",\s*z\s*∈\s*c",         # ", z ∈ C"
    r"z\s+c\s+[∈]",           # alternative ordering
    r"\bz\b.*\bc\s*∈",        # "z ... C ∈" (messy extraction)
    r"where\s+z\s+c\b",       # "where z C" (∈ lost in extraction)
    r"\bz\s*c\s*[,.]",        # "z C," or "z C." (∈ lost)
    r"polynomial.*\bz\b",     # polynomial in z
    r"\bp\s*\(\s*z\s*\)",     # p(z)
    r"roots.*\bp\s*\(",       # roots of p(
    r"\bz\b.*\bi\b.*[+-]",    # z with i and arithmetic (complex expression)
    r"[+-].*\bi\b.*\bz\b",    # i with z and arithmetic
]

# Graph-feature keywords: these appear naturally in "sketch the graph" questions
# and should NOT prevent a sketch-graph question from being classified as Functions.
GRAPH_FEATURE_KW = [
    r"stationary\s+point", r"turning\s+point",
    r"maximum.*minimum", r"inflection", r"concav",
    r"asymptote",
]

CALCULUS_KW = [
    r"differentiat", r"derivative", r"dy\s*/\s*dx", r"dy\s*dx",
    r"\bgradient\b",           # "find the gradient" = calculus
    r"integra", r"∫", r"anti[\-\s]?derivat",
    r"\bdx\b",                 # integral marker (∫ often lost in extraction)
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
    r"velocity", r"acceleration", r"displacement",
    r"kinematics", r"particle\s+mov", r"particle\s+travel",
    r"rectilinear\s+motion",
    r"\bspeed\b", r"distance\s+travel", r"travel.*distance",
    r"\btime\b.*\bposition\b", r"position.*\btime\b",
    r"metres?\s+per\s+second", r"km\s*/\s*h", r"m\s*/\s*s",
    r"area\s+between", r"area\s+under", r"area\s+bound",
    r"\bvolume\b",
    r"arc\s+length", r"surface\s+area",
    r"newton.*method",
    r"partial\s+fraction",
    r"limit\b", r"l'h.pital",
]

# "Real" calculus operations — excludes graph-feature words that naturally
# appear when describing a graph to sketch (stationary point, inflection, etc.)
CALCULUS_CORE_KW = [kw for kw in CALCULUS_KW if kw not in GRAPH_FEATURE_KW]

VECTORS_KW = [
    r"\bvector\b", r"dot\s+product", r"scalar\s+product",
    r"cross\s+product", r"vector\s+product",
    r"position\s+vector", r"unit\s+vector",
    r"magnitude.*vector", r"vector.*magnitude",
    r"linear.*independent", r"linear.*dependent",
    r"scalar\s+resolute", r"vector\s+resolute",
    r"equation\s+of.*plane", r"equation\s+of.*line",
    r"parametric.*equation.*line",
    r"normal\s+to.*plane", r"cartesian\s+equation.*plane",
    r"intersection.*plane", r"angle.*between.*plane",
    r"skew\s+lines", r"direction\s+vector",
    r"perpendicular.*vector", r"projection.*vector",
    r"parallel.*vector",
]

FUNCTIONS_KW = [
    r"asymptote", r"rational\s+function",
    r"inverse\s+function", r"one[\-\s]?to[\-\s]?one",
    r"transformation", r"dilation", r"translation",
    r"domain\b", r"range\b",
    r"composite\s+function",
    r"graph\s+of", r"sketch.*graph",
    r"modulus\s+function", r"absolute\s+value",
    r"piecewise", r"hybrid\s+function",
    r"ellipse", r"hyperbola",
    r"parametric",
    r"trigonometric\s+identit", r"trig.*identit",
    r"double\s+angle", r"compound\s+angle",
]


def has_match(text, keywords):
    for kw in keywords:
        if re.search(kw, text):
            return True
    return False


def classify_question(text):
    if not text:
        return 2, AOS[2]

    t = text.lower()

    # 1. Probability and Statistics (very distinct domain — always highest priority)
    if has_match(t, PROB_STATS_KW):
        return 6, AOS[6]

    # 2. Complex Numbers — anything involving imaginary i, z ∈ C, argand, etc.
    #    Complex takes priority because these questions are distinctly about complex numbers.
    if has_match(t, COMPLEX_KW):
        return 3, AOS[3]

    # 3. Sketch/graph → Functions, unless real calculus operations are involved
    #    "Sketch the graph and label stationary points" → Functions
    #    "Sketch the graph and find the derivative" → Calculus
    is_graph = bool(re.search(r"sketch.*graph|graph.*sketch|sketch.*curve", t))
    if is_graph and not has_match(t, CALCULUS_CORE_KW):
        return 2, AOS[2]

    # 4. Logic and Proof
    if has_match(t, LOGIC_PROOF_KW):
        if has_match(t, CALCULUS_KW):
            return 4, AOS[4]
        if has_match(t, VECTORS_KW):
            return 5, AOS[5]
        return 1, AOS[1]

    # 5. Calculus (takes precedence over vectors and functions)
    if has_match(t, CALCULUS_KW):
        return 4, AOS[4]

    # 6. Vectors
    if has_match(t, VECTORS_KW):
        return 5, AOS[5]

    # 7. Functions, Relations and Graphs (fallback)
    if has_match(t, FUNCTIONS_KW):
        return 2, AOS[2]

    return 2, AOS[2]


def main():
    with open(RAW_JSON) as f:
        raw = json.load(f)

    print(f"Classifying {len(raw)} questions...")

    from collections import Counter
    aos_counts = Counter()

    for q in raw:
        # Merge Insight and Insight Publications
        if "Insight" in q.get("publisher", ""):
            q["publisher"] = "Insight"
            q["id"] = q["id"].replace("insight_publications_", "insight_")

        aos_num, aos_name = classify_question(q.get("extracted_text", ""))
        q["aos"] = aos_num
        q["aos_name"] = aos_name
        q.pop("topic", None)
        aos_counts[f"{aos_num}. {aos_name}"] += 1

        # Exam 1 is always short answer
        if q.get("exam_type") == 1:
            q["section"] = "short_answer"

    # Remove extracted_text and source_pdf from output
    output = []
    for q in raw:
        out = {k: v for k, v in q.items() if k not in ("extracted_text", "source_pdf")}
        output.append(out)

    with open(OUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nBy Area of Study:")
    for k, v in sorted(aos_counts.items()):
        print(f"  {k}: {v}")

    print(f"\nTotal: {len(output)} questions")
    print(f"Saved to {OUT_JSON}")


if __name__ == "__main__":
    main()
