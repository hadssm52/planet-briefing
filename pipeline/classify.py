"""Free mode: sort stories into regions and topics with keyword rules, and
use each outlet's own feed summary instead of AI-written bullets.

To improve the sorting, add words to the lists below. Lists are keyed by the
`slug` of each region/topic in config.yaml. Matching ignores case, except
for the short UPPERCASE abbreviations in CASE_SENSITIVE.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

REGION_WORDS = {
    "europe": """
        europe european eu brussels britain british england english scotland scottish wales welsh
        london france french paris macron germany german berlin merz italy italian rome meloni spain
        spanish madrid portugal portuguese lisbon netherlands dutch amsterdam belgium belgian switzerland
        swiss geneva austria austrian vienna poland polish warsaw ukraine ukrainian kyiv zelensky russia
        russian moscow kremlin putin sweden swedish norway norwegian denmark danish finland finnish
        ireland irish dublin greece greek athens hungary hungarian orban czech prague romania romanian
        bulgaria bulgarian serbia serbian croatia bosnia kosovo albania albanian moldova belarus
        lithuania latvia estonia baltic iceland slovakia slovenia starmer sarkozy nato
    """,
    "north-america": """
        america american americans washington white_house trump congress senate pentagon new_york
        california texas florida chicago los_angeles biden canada canadian ottawa toronto vancouver
        quebec carney federal_reserve wall_street thanksgiving
    """,
    "latin-america": """
        latin_america south_america mexico mexican brazil brazilian lula bolsonaro argentina argentine argentinian
        milei buenos_aires colombia colombian bogota venezuela venezuelan maduro caracas chile chilean
        santiago peru peruvian lima ecuador bolivia paraguay uruguay cuba cuban havana haiti dominican
        guatemala honduras el_salvador nicaragua costa_rica panama caribbean rio sao_paulo puerto_rico
        jamaica amazon
    """,
    "asia-pacific": """
        asia asian asean china chinese beijing shanghai xi_jinping hong_kong taiwan taipei japan japanese
        tokyo korea korean seoul pyongyang india indian delhi new_delhi mumbai modi pakistan pakistani
        islamabad bangladesh dhaka hasina sri_lanka nepal afghanistan afghan taliban kabul myanmar
        thailand thai bangkok vietnam vietnamese cambodia laos malaysia singapore indonesia jakarta
        philippines philippine manila australia australian sydney melbourne canberra new_zealand
        auckland pacific fiji papua mongolia kazakhstan uzbekistan
    """,
    "middle-east": """
        middle_east israel israeli gaza hamas west_bank palestinian palestinians netanyahu jerusalem
        tel_aviv iran iranian tehran iraq iraqi baghdad kurdish kurdistan syria syrian damascus lebanon
        lebanese beirut hezbollah jordan saudi riyadh emirates dubai abu_dhabi qatar doha kuwait bahrain
        oman yemen yemeni houthi houthis aden turkey turkish ankara istanbul erdogan egypt egyptian cairo
        gulf
    """,
    "africa": """
        africa african nigeria nigerian lagos abuja kenya kenyan nairobi south_africa johannesburg joburg
        cape_town pretoria durban ethiopia ethiopian addis_ababa sudan sudanese khartoum somalia
        mogadishu congo congolese kinshasa rwanda uganda tanzania ghana senegal mali niger burkina_faso
        chad cameroon ivory_coast morocco moroccan algeria tunisia libya libyan tripoli zimbabwe zambia
        mozambique angola namibia botswana malawi madagascar sahel afcon gambia eritrea liberia
        sierra_leone guinea benin togo gabon ethekwini
    """,
}

TOPIC_WORDS = {
    "sport": """
        sport sports football soccer cricket rugby tennis golf olympic olympics world_cup cup_final
        premier_league champions_league europa_league la_liga serie_a bundesliga nations_league fifa uefa f1 formula_one grand_prix nba nfl match tournament coach
        striker goalkeeper medal wimbledon marathon boxing cycling athlete stadium championship afcon
        quarter-final semi-final
    """,
    "conflict": """
        war wars military troops army soldier soldiers missile missiles drone drones airstrike air_strike
        airstrikes bomb bombing bombs explosion shelling ceasefire truce rebels militants insurgents
        hamas hezbollah houthi houthis isis terror terrorist gunmen invasion warship warplanes weapons
        artillery frontline hostage hostages killed retaliation attack attacks sabotage
    """,
    "environment": """
        climate cop31 cop30 emissions carbon net_zero renewable solar wind_power flood floods flooding
        wildfire wildfires drought heatwave heat-linked storm hurricane typhoon cyclone earthquake tsunami
        volcano landslide weather rainfall pollution deforestation biodiversity wildlife species ocean
        oceans glacier environment environmental conservation endangered
    """,
    "science-technology": """
        science scientists scientific researchers study research space nasa rocket satellite satellites
        astronaut astronauts moon mars ai artificial_intelligence chatbot tech technology nvidia apple
        google microsoft openai chip chips semiconductor cyber hack hackers software internet smartphone
        robot quantum vaccine virus disease health hospital medical medicine cancer outbreak dna
    """,
    "economics": """
        economy economic markets market stocks shares investors inflation interest_rate interest_rates
        central_bank bank banks gdp recession trade tariff tariffs exports imports company companies ceo
        profit profits revenue jobs unemployment wages prices oil currency dollar budget tax taxes debt
        bonds business merger acquisition startup industry manufacturing airline airlines boeing retail
    """,
    "culture": """
        film movie cinema music album singer concert festival art artist museum exhibition book novel
        author theatre television celebrity fashion royal king queen prince princess pope church religion
        religious christmas food chef heritage award awards oscar oscars grammy culture cultural
    """,
    "politics": """
        election elections vote voters president prime_minister minister government parliament congress
        senate lawmakers party opposition campaign policy law court judge trial supreme_court protest
        protests diplomat diplomatic ambassador summit sanctions treaty referendum mayor governor
        corruption police immigration migrants coalition
    """,
}

CASE_SENSITIVE = {
    "US": "north-america", "U.S.": "north-america", "USA": "north-america",
    "UK": "europe", "EU": "europe", "NATO": "europe",
    "UAE": "middle-east", "DRC": "africa", "ANC": "africa",
}

# When two topics score the same, the more specific one wins.
TOPIC_PRIORITY = ["sport", "conflict", "environment", "science-technology", "economics", "culture", "politics"]


def _compile(words: str) -> re.Pattern:
    phrases = sorted((w.replace("_", " ") for w in words.split()), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.IGNORECASE)


REGION_RE = {slug: _compile(words) for slug, words in REGION_WORDS.items()}
TOPIC_RE = {slug: _compile(words) for slug, words in TOPIC_WORDS.items()}
UPPER_RE = re.compile(r"(?<![\w.])(" + "|".join(re.escape(k) for k in CASE_SENSITIVE) + r")(?![\w])")


def _score(patterns: dict, title: str, description: str) -> Counter:
    """Keyword hits per slug; headline words count double."""
    scores: Counter = Counter()
    for slug, pattern in patterns.items():
        scores[slug] += 2 * len(pattern.findall(title)) + len(pattern.findall(description))
    return scores


def classify_region(story: dict, slug_to_name: dict) -> str:
    title, desc = story["title"], story.get("description", "")
    # "Latin America" must not count as "America".
    title_na = title.replace("Latin America", "")
    desc_na = desc.replace("Latin America", "")
    scores = _score(REGION_RE, title, desc)
    scores["north-america"] = 2 * len(REGION_RE["north-america"].findall(title_na)) + len(
        REGION_RE["north-america"].findall(desc_na))
    for text, weight in ((title, 2), (desc, 1)):
        for match in UPPER_RE.findall(text):
            scores[CASE_SENSITIVE[match]] += weight
    best = _best(scores, prefer=story.get("region_hint_slug"))
    if best and best in slug_to_name:
        return slug_to_name[best]
    hint = story.get("region_hint")
    return hint if hint in slug_to_name.values() else "Global"


def classify_topic(story: dict, slug_to_name: dict) -> str:
    hint = story.get("topic_hint")
    if hint in slug_to_name.values():
        return hint  # topic feeds (e.g. BBC Sport) are reliable
    scores = _score(TOPIC_RE, story["title"], story.get("description", ""))
    best = _best(scores, order=TOPIC_PRIORITY)
    if best and best in slug_to_name:
        return slug_to_name[best]
    return slug_to_name.get("politics", next(iter(slug_to_name.values())))


def _best(scores: Counter, prefer: Optional[str] = None, order: Optional[list] = None) -> Optional[str]:
    top = max(scores.values(), default=0)
    if top == 0:
        return None
    tied = [slug for slug, n in scores.items() if n == top]
    if prefer in tied:
        return prefer
    if order:
        tied.sort(key=lambda s: order.index(s) if s in order else len(order))
    return tied[0]


# ---------------------------------------------------------------- summaries


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘“])")


def excerpt(description: str, limit: int = 320) -> str:
    """The first one or two sentences of the outlet's own summary."""
    sentences = SENTENCE_RE.split(description.strip())
    text = ""
    for s in sentences[:2]:
        if text and len(text) + len(s) > limit:
            break
        text = f"{text} {s}".strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def free_summarise(stories: list[dict], cfg: dict):
    """Free alternative to summarise.summarise: no API calls, no cost.
    Returns (stories, top story ids, usage) in the same shape."""
    from .summarise import Usage

    region_names = {r["slug"]: r["name"] for r in cfg["regions"]}
    topic_names = {t["slug"]: t["name"] for t in cfg["topics"]}
    name_to_slug = {v: k for k, v in region_names.items()}

    results = []
    for s in stories:
        out = dict(s)
        out["region_hint_slug"] = name_to_slug.get(s.get("region_hint"))
        out["region"] = classify_region(out, region_names)
        out["topic"] = classify_topic(out, topic_names)
        out["headline"] = s["title"]
        out["bullets"] = []
        text = excerpt(s.get("description", ""))
        out["excerpt"] = {"text": text, "source": s["sources"][0]["name"]} if text else None
        # More outlets covering it = more significant.
        out["significance"] = min(10, 1 + 2 * len(s["sources"]) + (1 if text else 0))
        out.pop("region_hint_slug")
        results.append(out)

    top_ids = pick_top_free(results)
    usage = Usage(cfg["claude"]["input_price_per_mtok"], cfg["claude"]["output_price_per_mtok"])
    return results, top_ids, usage


def pick_top_free(stories: list[dict], count: int = 10, per_region: int = 3) -> list[int]:
    """Most widely covered stories, at most `per_region` from any one region."""
    ranked = sorted(stories, key=lambda s: (len(s["sources"]), bool(s.get("excerpt")),
                                            s.get("published") or ""), reverse=True)
    picked, per = [], Counter()
    for s in ranked:
        if per[s["region"]] < per_region:
            picked.append(s["id"])
            per[s["region"]] += 1
        if len(picked) == count:
            break
    return picked
