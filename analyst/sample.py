"""Synthetic fixtures only. These are not India EV market facts."""

from analyst.models import Claim, Extraction, Plan, Report, Validation

SAMPLE_QUESTION = (
    "Compare the fictional Northstar and Meridian electric vehicle companies."
)


def sample_sources():
    docs = [
        (
            "Ssample1",
            "Northstar — synthetic annual statement",
            "northstar.example",
            "Northstar reported 12000 electric passenger car deliveries in the fictional market in 2024. Northstar reported 15000 electric passenger car deliveries in the fictional market in 2025.",
        ),
        (
            "Ssample2",
            "Meridian — synthetic annual statement",
            "meridian.example",
            "Meridian reported 9000 electric passenger car deliveries in the fictional market in 2025.",
        ),
        (
            "Ssample3",
            "Trade register — synthetic estimate",
            "register.example",
            "Meridian reported 11000 electric passenger car deliveries in the fictional market in 2025.",
        ),
    ]
    return [
        {
            "id": sid,
            "title": title,
            "publisher": publisher,
            "url": "https://" + publisher,
            "retrieved_at": "Synthetic fixture",
            "published_at": "Synthetic fixture",
            "text": text,
            "tables": [],
            "kind": "sample",
            "source_tier": "other",
            "source_quality": "unclassified",
        }
        for sid, title, publisher, text in docs
    ]


class SampleProviders:
    llm_calls = 0
    search_calls = 0

    async def close(self):
        pass

    async def generate(self, role, instructions, data, schema):
        if schema is Plan:
            return Plan(
                scope="Synthetic EV passenger-car market, 2024–2025. Demonstration only.",
                assumptions=[
                    "All companies, sources, and figures in this sample are fictional."
                ],
                questions=[
                    "How do deliveries compare?",
                    "What growth is supported?",
                    "Which estimates conflict?",
                ],
                queries=["synthetic EV company deliveries"],
            )
        if schema is Extraction:
            claims = []
            for source in data["sources"]:
                for sentence in source["text"].split(". "):
                    sentence = sentence.rstrip(".") + "."
                    tokens = sentence.split()
                    claims.append(
                        Claim(
                            id="temporary",
                            statement=sentence,
                            source_id=source["id"],
                            quote=sentence,
                            entity=tokens[0],
                            metric="deliveries",
                            value=float(tokens[2]),
                            unit="vehicles",
                            period=tokens[-1].strip("."),
                            geography="fictional market",
                            segment="electric passenger cars",
                        )
                    )
            return Extraction(claims=claims)
        if schema is Validation:
            north = [c for c in data["claims"] if c["entity"] == "Northstar"]
            return Validation(
                assessments=[],
                follow_up_queries=[],
                calculations=[
                    {
                        "operation": "growth",
                        "input_claim_ids": [c["id"] for c in north],
                        "years": 1,
                        "label": "Northstar delivery growth, 2024–2025",
                    }
                ],
            )
        if schema is Report:
            claims = data["claims"]
            north = [c["id"] for c in claims if c["entity"] == "Northstar"]
            meridian = [c["id"] for c in claims if c["entity"] == "Meridian"]
            return Report(
                title="A growing leader. An unresolved challenger.",
                sections=[
                    {
                        "heading": "Executive summary",
                        "findings": [
                            {
                                "text": "In this fictional example, Northstar's reported deliveries increased between 2024 and 2025. Meridian's 2025 deliveries remain disputed.",
                                "claim_ids": north + meridian,
                            }
                        ],
                    },
                    {
                        "heading": "Competitive landscape",
                        "findings": [
                            {
                                "text": "Northstar reports 15,000 deliveries in 2025; the two Meridian sources report 9,000 and 11,000. The Meridian estimates should not be averaged into a verified figure.",
                                "claim_ids": [north[-1]] + meridian,
                            }
                        ],
                    },
                    {
                        "heading": "Strategic implications",
                        "findings": [
                            {
                                "text": "Analyst interpretation: reconcile Meridian's reporting methodology before making a comparison-based investment or operating decision.",
                                "claim_ids": meridian,
                            }
                        ],
                    },
                ],
                limitations=[
                    "Synthetic demonstration only; no live search or model calls occurred.",
                    "This sample does not analyze India's actual EV market.",
                ],
            )
        raise ValueError("Unknown sample schema")
