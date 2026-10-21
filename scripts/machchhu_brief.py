"""Hand-written, source-checked brief: 'Machchhu: The River That Took Morbi Twice'.

Why by hand: the generated script (2026-10-15) put the dam failure at dawn (it
struck around 3:30 pm), invented "the storm of 2022", gave the bridge toll as
135 (at least 141), called both disasters one cause ("neglected maintenance"),
and retold the reconstruction five times. Every claim below comes from the
Wikipedia articles "1979 Machchhu dam failure" and "2022 Morbi bridge collapse"
(fetched 2026-10-15); the link between the two is the PLACE, never the cause.

    python scripts/machchhu_brief.py   -> data/briefs/machchhu-...-handwritten.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data/briefs/machchhu-the-river-that-took-morbi-twice-2026-10-15.json"
OUT = ROOT / "data/briefs/machchhu-the-river-that-took-morbi-twice-2026-10-15-handwritten.json"

BEATS = [
    ("On the eleventh of August, 1979, a wall of water came through the town of Morbi, in Gujarat. "
     "Forty-three years later, on the same river, a bridge fell with hundreds of people on it. "
     "Two disasters. Two different causes. One river. This is the story of the Machchhu.",
     "Machchhu river Morbi Gujarat aerial, river through town"),
    ("Saurashtra is dry country. Droughts here are not rare events. They are history. "
     "So when engineers planned dams on the Machchhu, the question they were answering was simple. "
     "How do you keep water? Not, how do you survive too much of it.",
     "dry farmland Gujarat drought cracked earth"),
    ("The first dam, Machchhu One, was built in 1959. "
     "Downstream, in 1972, came a second. Machchhu Two. "
     "An earthfill dam, with a masonry spillway two hundred and six metres wide and eighteen sluice gates. "
     "Long earthen embankments ran out on both sides. Altogether, close to four kilometres of wall.",
     "earthfill dam embankment spillway sluice gates India"),
    ("It was designed as an irrigation scheme. Water supply came first. Flood control came second. "
     "The spillway was built to pass about five thousand six hundred cubic metres of water every second. "
     "On paper, that was the most the river would ever send.",
     "dam spillway water flowing, irrigation canal"),
    ("In August 1979, the rain did not stop. "
     "The flow that reached Machchhu Two was later measured at over sixteen thousand cubic metres per second. "
     "Nearly three times what the dam was designed for.",
     "heavy monsoon rain flooding river India"),
    ("The water could not get out fast enough. So it went over, and through, the earth. "
     "The earthen walls began to disintegrate. "
     "About seven hundred and sixty metres of the left embankment collapsed. "
     "And about three hundred and sixty-five metres of the right.",
     "earth dam breach erosion floodwater"),
    ("Morbi sat five kilometres below the dam. An industrial town. "
     "Around three thirty in the afternoon, the flood reached it. "
     "Within twenty minutes, low-lying areas were under twelve to thirty feet of water.",
     "flooded town streets India 1979 archive"),
    ("In the next fifteen minutes the water rose to thirty feet. "
     "Some low parts of the city stayed under twenty feet of water for six hours. "
     "There was nowhere to go but up.",
     "flood water rooftops people stranded"),
    ("People climbed onto rooftops and ran for the hills. "
     "More than a hundred took shelter in the Vajepar Ram Mandir, a temple. "
     "The flood submerged them, along with the temple itself.",
     "temple in flood India, water rising around temple"),
    ("Survivors later described mothers forced to let go of their children in the current. "
     "Families separated in seconds. "
     "Much of what we know about those hours comes from accounts like these.",
     "flood survivors archive photograph India"),
    ("How many people died is still not known. "
     "Estimates range from about one thousand eight hundred to twenty-five thousand. "
     "That gap is its own part of the story. A disaster this size, and no settled number.",
     "memorial candles names list"),
    ("For years, the Guinness Book of Records listed it as the worst dam burst in the world. "
     "That changed only in 2005, when the true death toll of China's Banqiao dam failure, from 1975, was declassified.",
     "Banqiao dam China, record book"),
    ("Officially, the disaster was framed as an act of God. "
     "A book by Tom Wooten and Utpal Sandesara, No One Had A Tongue To Speak, argues otherwise. "
     "It points to structural and communication failures that led to the disaster and made it worse.",
     "book pages, investigation documents"),
    ("When Machchhu Two was rebuilt, its spillway capacity was increased four times over, "
     "to about twenty-one thousand cubic metres per second. "
     "Built, this time, for the river that actually exists.",
     "rebuilt dam spillway concrete gates"),
    ("In Morbi, over the same river, hung an older structure. "
     "The Jhulto Pul. A pedestrian suspension bridge, two hundred and thirty metres long, "
     "just over a metre wide, fifteen metres above the water. "
     "It dated from the nineteenth century, and once allowed only fifteen people at a time.",
     "Jhulto Pul Morbi suspension bridge"),
    ("In 2022 the bridge was closed for six months of repairs, under a private maintenance contract. "
     "It reopened on the twenty-sixth of October, for the Gujarati New Year. "
     "Its stated capacity was now one hundred and twenty-five people.",
     "bridge renovation reopening crowd festival"),
    ("Five days later, on the evening of the thirtieth, more than five hundred people were on it. "
     "Security footage shows the bridge shaking violently. People grabbing the cables. "
     "At six forty, the walkway split at its midpoint.",
     "suspension bridge cables crowd evening"),
    ("At least one hundred and forty-one people died. More than one hundred and eighty were rescued. "
     "Many of the dead were women, elderly people and children. The youngest was eighteen months old.",
     "rescue boats river night search"),
    ("A forensic report presented in court found the bridge could not carry the weight of its new, heavy flooring. "
     "The cables were rusted. Anchors were broken. Bolts were loose. "
     "Reports said it had reopened without a fitness certificate from the municipality.",
     "rusted cable bolts close up, forensic investigation"),
    ("So these were two different failures. "
     "In 1979, a dam built for drought met a flood three times its design. "
     "In 2022, a repaired bridge, carrying four times its stated limit, gave way. "
     "Different engineering. Different decisions.",
     "concrete dam and river bridge"),
    ("What they share is the river, and the town on its banks. "
     "And a question every engineer is supposed to ask first. "
     "Not, what is this built to do. "
     "But, what will actually happen to it.",
     "Machchhu river calm today, Morbi skyline"),
]


def main():
    gen = json.loads(GEN.read_text(encoding="utf-8"))
    words = sum(len(t.split()) for t, _ in BEATS)
    brief = {
        "title": gen["title"],
        # Leads with stock-searchable words: format-render anchors every footage
        # query on the topic's first two content words ("dam flood").
        "topic": "dam flood India monsoon, the 1979 Machchhu dam failure in Morbi",
        "format_slug": "engineering-failures",
        "alt_titles": gen.get("alt_titles", []),
        "hook": BEATS[0][0],
        "substance": [
            {"claim": "Machchhu-2 failed on 11 August 1979; observed flow 16,307 m3/s, about three times the 5,663 m3/s spillway design.", "source": "Wikipedia: 1979 Machchhu dam failure", "needs_check": False},
            {"claim": "Flood reached Morbi around 3:30 pm; 12-30 ft within 20 minutes; some areas under 20 ft for 6 hours.", "source": "Wikipedia: 1979 Machchhu dam failure", "needs_check": False},
            {"claim": "Death toll estimates range from 1,800 to 25,000.", "source": "Wikipedia: 1979 Machchhu dam failure", "needs_check": False},
            {"claim": "Rebuilt spillway capacity increased four times, to about 21,000 m3/s.", "source": "Wikipedia: 1979 Machchhu dam failure", "needs_check": False},
            {"claim": "Morbi bridge collapsed 30 Oct 2022 at 6:40 pm with 500+ on it (capacity 125); at least 141 dead.", "source": "Wikipedia: 2022 Morbi bridge collapse", "needs_check": False},
        ],
        "beats": [{"beat": i + 1, "narration": t, "visual": v,
                   "seconds": round(len(t.split()) / 2.6, 1)} for i, (t, v) in enumerate(BEATS)],
        "description": ("On 11 August 1979 the Machchhu-2 dam failed and flooded Morbi, Gujarat; estimates of the dead "
                        "range from 1,800 to 25,000. In 2022 a suspension bridge over the same river collapsed, killing at "
                        "least 141. Two disasters, two different causes, one river.\n\nSources: Wikipedia, '1979 Machchhu dam "
                        "failure' and '2022 Morbi bridge collapse'; Wooten & Sandesara, 'No One Had A Tongue To Speak'."),
        "tags": ["Machchhu dam", "Morbi", "dam failure", "Morbi bridge collapse", "engineering disaster", "Gujarat"],
        "hashtags": ["#engineering", "#history", "#india"],
        "thumbnail_text": gen.get("thumbnail_text", "SAME RIVER"),
        "end_screen_followup": gen.get("end_screen_followup", ""),
        "handwritten": True,
        "word_count": words,
    }
    OUT.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT.name, words, "words,", len(BEATS), "beats")


if __name__ == "__main__":
    main()
