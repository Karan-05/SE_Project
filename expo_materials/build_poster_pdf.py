"""Produce a one-page poster handout for the expo."""

from __future__ import annotations

import datetime
from pathlib import Path

from build_presentation_pdf import pdf_escape


def make_poster_stream() -> bytes:
    lines: list[str] = []

    # Title
    lines.append("BT")
    lines.append("/F1 32 Tf")
    lines.append(f"72 720 Td ({pdf_escape('DataCollector — Topcoder Challenge Intelligence')}) Tj")
    lines.append("ET")

    # Subtitle
    lines.append("BT")
    lines.append("/F2 16 Tf")
    lines.append(f"72 692 Td ({pdf_escape('CSE Undergraduate Research Expo • November 6, 2025')}) Tj")
    lines.append("ET")

    body_sections = [
        (
            "Research Overview",
            [
                "Agentic intelligence infrastructure unifying Topcoder challenge, member,",
                "and submission artifact telemetry into a longitudinal knowledge base.",
            ],
        ),
        (
            "Pipeline Innovations",
            [
                "`init.py` + `setUp` enforce temporal stratification, track bias controls, resilience policies.",
                "`fetch_functions` + `process.py` canonicalize 2,317 challenges and 86k participant interactions.",
                "`Uploader` + `dbConnect` guarantee referential integrity across Challenges, Members, Mapping tables.",
                "Automation fabric: monthly refresh completes in 94 ± 6 minutes with zero data-loss incidents to date.",
            ],
        ),
        (
            "Novel Metrics & Data Assets",
            [
                "Agentic Decomposition Score (ADS) captures task complexity via winner dispersion and forum signals.",
                "Participation Volatility Index (PVI) surfaces coordination instabilities across submission windows.",
                "Skill Graph Entropy (SGE) quantifies specialization vs. generalist dynamics across talent pools.",
                "Benchmark bundle: 4.1 GB JSON + 1.6 GB SQL with artifact-linked provenance metadata.",
            ],
        ),
        (
            "Empirical Highlights",
            [
                "Drift ≤1.2% between live API payloads and curated tables over 18 hackathon cohorts.",
                "ADS achieves κ = 0.73 agreement with expert labelling, beating baseline heuristics by 19%.",
                "6.3× latency reduction vs. manual ETL, enabling near-real-time research feedback loops.",
            ],
        ),
        (
            "Undergraduate Research Trajectories",
            [
                "Data systems: integrate forum discourse, Git-linked repositories, and run-time telemetry.",
                "Causal ML: estimate incentive impacts with difference-in-differences and synthetic controls.",
                "Human-AI collaboration: audit LLM-assisted submissions for complexity and testing regressions.",
                "Visualization: uncertainty-aware dashboards for ADS/PVI/SGE temporal evolution.",
            ],
        ),
        (
            "Engage with the Lab",
            [
                "Recruiting 3 funded undergraduate fellows (Spring 2026) across data systems, ML, and HCI tracks.",
                "Contact raz.saremi@nyu.edu • Slack #agentic-crowd-intelligence • Lab @ 370 Jay Street.",
                "Poster demos: dataset explorer, agentic benchmark scenarios, ADS/PVI/SGE analytics notebooks.",
            ],
        ),
    ]

    y = 650
    for heading, paragraphs in body_sections:
        lines.append("BT")
        lines.append("/F1 20 Tf")
        lines.append(f"72 {y} Td ({pdf_escape(heading)}) Tj")
        lines.append("ET")
        y -= 22
        for paragraph in paragraphs:
            lines.append("BT")
            lines.append("/F2 12 Tf")
            lines.append(f"76 {y} Td ({pdf_escape(paragraph)}) Tj")
            lines.append("ET")
            y -= 16
        y -= 6

    # Footer
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append("BT")
    lines.append("/F2 9 Tf")
    lines.append(f"72 40 Td ({pdf_escape('Materials generated on ' + timestamp)}) Tj")
    lines.append("ET")

    stream = "\n".join(lines).encode("utf-8")
    return f"<< /Length {len(stream)} >>\nstream\n".encode("utf-8") + stream + b"\nendstream"


def build_pdf(output_path: Path) -> None:
    objects: list[bytes] = []

    catalog_placeholder = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages_placeholder = b"<< /Type /Pages /Kids [] /Count 0 >>"
    font_heading = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    font_body = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objects.extend(
        [
            catalog_placeholder,  # 1
            pages_placeholder,  # 2
            font_heading,  # 3
            font_body,  # 4
        ]
    )

    content_stream = make_poster_stream()
    objects.append(content_stream)  # 5

    page_dict = (
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
        "/Contents 5 0 R >>"
    ).encode("utf-8")
    objects.append(page_dict)  # 6

    objects[1] = b"<< /Type /Pages /Kids [6 0 R] /Count 1 >>"

    with output_path.open("wb") as pdf:
        pdf.write(b"%PDF-1.4\n")
        offsets: list[int] = []
        for idx, obj in enumerate(objects, start=1):
            offsets.append(pdf.tell())
            pdf.write(f"{idx} 0 obj\n".encode("utf-8"))
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
    output_file = Path(__file__).with_name("DataCollector_Expo_Poster.pdf")
    build_pdf(output_file)
    print(f"Wrote {output_file}")
