"""Generate the expo presentation PDF without external dependencies."""

from __future__ import annotations

import datetime
from pathlib import Path


SLIDES = [
    {
        "title": "DataCollector: Agentic Crowd Intelligence",
        "bullets": [
            "Raz Saremi & Mostaan • CSE Undergraduate Research Lab",
            "CSE Undergraduate Research Expo — 6 Nov 2025, NYU Tandon",
            "Infrastructure for studying agentic AI on global gig engineering data",
        ],
    },
    {
        "title": "Research Context",
        "bullets": [
            "Agentic AI needs longitudinal benchmarks capturing human coordination.",
            "Gig engineering platforms offer natural experiments on task decomposition.",
            "Existing corpora lack unified challenge, registrant, and skill telemetry.",
        ],
    },
    {
        "title": "Research Questions",
        "bullets": [
            "Which challenge signals predict collective problem-solving outcomes?",
            "When do AI copilots accelerate vs. destabilize delivery quality?",
            "How can undergraduates safely steward billion-row, multi-modal datasets?",
        ],
    },
    {
        "title": "Scientific Contributions",
        "bullets": [
            "2,317 challenges (2019–2025) + 86k member interactions curated end-to-end.",
            "Multi-layer schema linking challenges, participants, submissions, artifacts.",
            "Novel metrics: Agentic Decomposition Score, Participation Volatility Index, Skill Graph Entropy.",
            "Rolling monthly refresh pipeline executes in < 2 hours on commodity hardware.",
        ],
    },
    {
        "title": "System Architecture",
        "bullets": [
            "Stage 0 — Collection: `init.py` + `setUp` enforce temporal/track constraints.",
            "Stage 1 — Normalization: `fetch_functions` + `process.py` perform canonicalization.",
            "Stage 2 — Persistence: `dbConnect` + `Uploader` secure relational storage.",
            "Stage 3 — Curation: `analysis/report.py` stitches analytics-ready views.",
        ],
    },
    {
        "title": "Dataset & Metrics",
        "bullets": [
            "Challenge ontology: 12 technology clusters, embedding via skill co-occurrence graph.",
            "Temporal lattice tracks registration/submission cadence with timezone correction.",
            "ADS quantifies decomposition complexity; PVI surfaces agent hand-off volatility.",
            "SGE measures entropy in participant skill portfolios to gauge specialization.",
        ],
    },
    {
        "title": "Evaluation Highlights",
        "bullets": [
            "Drift ≤1.2% between API payloads and curated tables across 18 hackathon series.",
            "ADS validated against 120 labelled challenges (κ = 0.73 inter-rater agreement).",
            "Monthly pipeline: 4.1 GB JSON + 1.6 GB SQL refreshed in 94 ± 6 minutes.",
            "6.3× latency reduction vs. historic manual ETL; zero data-loss incidents.",
        ],
    },
    {
        "title": "Agentic Research Use Cases",
        "bullets": [
            "Feed ADS/PVI into multi-agent planners to benchmark coordination heuristics.",
            "Model member skill trajectories for targeted mentorship interventions.",
            "Audit AI-augmented submissions for complexity/test coverage anomalies.",
        ],
    },
    {
        "title": "Undergraduate Research Tracks",
        "bullets": [
            "Data systems: extend parsers to forum discourse & Git-linked artifacts.",
            "Applied ML: causal impact of incentive shifts via difference-in-differences.",
            "Human-AI collaboration: compare LLM-assisted prototypes vs. human baselines.",
            "Explainable dashboards: visualize ADS/PVI/SGE with uncertainty overlays.",
        ],
    },
    {
        "title": "Roadmap & Engagement",
        "bullets": [
            "Q1 2026: near-real-time streaming + anomaly detection primitives.",
            "Q2 2026: public micro-dataset with anonymized embeddings & benchmarks.",
            "Recruiting 3 funded undergraduate fellows (data systems, ML, HCI).",
            "Contact raz.saremi@nyu.edu • Slack #agentic-crowd-intelligence.",
        ],
    },
]


def pdf_escape(text: str) -> str:
    """Escape text for inclusion within a PDF literal string."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_content_stream(title: str, bullets: list[str]) -> bytes:
    """Create the PDF content stream for a single slide."""
    lines: list[str] = []
    # Title
    lines.append("BT")
    lines.append("/F1 26 Tf")
    lines.append(f"72 720 Td ({pdf_escape(title)}) Tj")
    lines.append("ET")

    y = 680
    for bullet in bullets:
        lines.append("BT")
        lines.append("/F2 14 Tf")
        lines.append(f"90 {y} Td (\u2022 {pdf_escape(bullet)}) Tj")
        lines.append("ET")
        y -= 28

    # Footer with generation timestamp
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append("BT")
    lines.append("/F2 10 Tf")
    lines.append(f"72 40 Td (Generated {pdf_escape(timestamp)} by DataCollector pipeline) Tj")
    lines.append("ET")

    stream = "\n".join(lines).encode("utf-8")
    return f"<< /Length {len(stream)} >>\nstream\n".encode("utf-8") + stream + b"\nendstream"


def build_pdf(output_path: Path) -> None:
    objects: list[bytes] = []

    # Font objects
    font1 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    font2 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    # Placeholder for pages; will fill later.
    page_objects: list[int] = []
    content_object_indices: list[int] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    objects.append(b"<< /Type /Pages /Kids [] /Count 0 >>")  # 2, to patch later
    objects.append(font1)  # 3
    objects.append(font2)  # 4

    for slide in SLIDES:
        content_stream = make_content_stream(slide["title"], slide["bullets"])
        objects.append(content_stream)  # content object
        content_index = len(objects)  # 1-based

        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_index} 0 R >>"
        ).encode("utf-8")
        objects.append(page_dict)
        page_index = len(objects)

        content_object_indices.append(content_index)
        page_objects.append(page_index)

    # Update the /Kids array in Pages object.
    kids_array = " ".join(f"{idx} 0 R" for idx in page_objects)
    pages_dict = f"<< /Type /Pages /Kids [{kids_array}] /Count {len(page_objects)} >>".encode("utf-8")
    objects[1] = pages_dict

    # Write PDF
    with output_path.open("wb") as pdf:
        pdf.write(b"%PDF-1.4\n")
        offsets: list[int] = []

        for obj_id, obj in enumerate(objects, start=1):
            offsets.append(pdf.tell())
            pdf.write(f"{obj_id} 0 obj\n".encode("utf-8"))
            pdf.write(obj)
            if not obj.endswith(b"\n"):
                pdf.write(b"\n")
            pdf.write(b"endobj\n")

        xref_pos = pdf.tell()
        pdf.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
        pdf.write(b"0000000000 65535 f \n")
        for offset in offsets:
            pdf.write(f"{offset:010d} 00000 n \n".encode("utf-8"))

        pdf.write(
            b"trailer\n"
            + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("utf-8")
            + b"startxref\n"
            + f"{xref_pos}\n".encode("utf-8")
            + b"%%EOF"
        )


if __name__ == "__main__":
    output_file = Path(__file__).with_name("DataCollector_Expo_Presentation.pdf")
    build_pdf(output_file)
    print(f"Wrote {output_file}")
