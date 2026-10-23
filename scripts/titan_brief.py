"""Hand-written, source-checked brief: 'Titanic Sub: Six Warnings They Ignored'.

Topic chosen THROUGH the recognition gate this time (hook 'Titanic' = GO, 5,864
views/day), not by overriding it. Angle that differs from the 1.3M rival: not
"what happened" but every documented warning, in order, ending in the bang.

Every claim is from Wikipedia "Titan submersible implosion" (fetched 2026-10-23)
except the single line that the 1912 warnings were about ice (RMS Titanic,
well documented). OceanGate's defence is included where the record has it.

    python scripts/titan_brief.py   -> data/briefs/titanic-sub-six-warnings-2026-10-23.json
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/briefs/titanic-sub-six-warnings-2026-10-23.json"

TITLE = "Titanic Sub: Six Warnings They Ignored"

# Separate cold open. The Machchhu brief reused beat 1 as the hook, so the
# video narrated its opening paragraph twice in the first 40 seconds.
HOOK = ("At 10:47 in the morning, more than three thousand metres under the North Atlantic, "
        "a submarine sends a text to the ship above. Three words. Dropped two weights. "
        "On that ship, people have already heard a bang. "
        "Five years earlier, someone had put this in writing. "
        "And he was not the only one.")
HOOK_PHOTOS = ["OceanGate Titan submersible", "Polar Prince ship"]

# (narration, stock-video visual cue, exact Commons photo queries)
BEATS = [
    ("The submarine was called Titan. The company was OceanGate. "
     "And for the price of a ticket, it would take you to the most famous shipwreck on Earth. "
     "The Titanic. Nearly four thousand metres down. "
     "Each dive carried a pilot, a guide, and three paying passengers.",
     "deep ocean dark water descending",
     ["RMS Titanic wreck bow", "OceanGate Titan submersible"]),
    ("Titan was not built like other deep-diving subs. "
     "Its body was a tube of wound carbon fibre, capped at both ends with titanium domes. "
     "Its CEO, Stockton Rush, knew that was unusual. In 2021 he said it himself. "
     "The carbon fibre and titanium, there's a rule you don't do that. Well, I did.",
     "carbon fiber material close up",
     ["Stockton Rush"]),
    ("No agency ever certified Titan as safe. It never had to be. "
     "It dived in international waters and did not carry passengers from a port. "
     "Passengers signed a waiver calling it experimental. One said the waiver mentioned death three times on page one. "
     "In 2019, the classification society Lloyd's Register refused to class it.",
     "legal document signature waiver",
     []),
    ("The first warning arrives in March 2018. "
     "A Boeing engineer who had worked on the preliminary designs analyses the hull, and emails the CEO directly. "
     "We think you are at high risk of a significant failure at or before you reach four thousand meters. "
     "He attaches a graph. At the four thousand metre line, he has drawn a skull and crossbones.",
     "engineer reviewing graph on screen",
     []),
    ("That same month comes warning number two. "
     "Rob McCallum, a deep sea exploration specialist, emails too. He asks the CEO to be very, very conservative. "
     "The reply: he is tired of industry players who try to use a safety argument to stop innovation. "
     "McCallum writes back once more, and this time he names the ghost. "
     "In your race to Titanic, he writes, you are mirroring that famous catch cry. She is unsinkable. "
     "OceanGate's lawyers threatened him with legal action.",
     "ocean waves dark storm ship",
     ["Titanic iceberg 1912"]),
    ("The third warning comes from inside the company. "
     "Its director of marine operations, David Lochridge, writes a safety report. "
     "He wants the hull scanned for hidden flaws. He says he is told that cannot be done, the hull is too thick. "
     "And the viewport, he warns, is only certified to thirteen hundred metres. A third of the way to Titanic. "
     "OceanGate says Lochridge is not an engineer, and that its own testing beats any outside check. "
     "It sues him. He sues back. They settle.",
     "office report papers desk lamp",
     []),
    ("Later in 2018, warning four. A group from the submarine industry drafts a letter. "
     "Their words: unanimous concern. An experimental approach that could end in outcomes from minor to catastrophic. "
     "The letter is never formally sent, but the CEO reads it, and calls the man who organised it. "
     "Industry standards, he tells him, are stifling innovation.",
     "letter envelope desk",
     []),
    ("Number five does not come from a person. It comes from the hull. "
     "The first carbon fibre hull cracks, after fifty dives. A new one is built in 2021. "
     "Scale models of the new design implode in a university lab, so the curing method is changed, "
     "and the full-size hull passes a pressure test. "
     "The titanium rings from the old hull are not replaced. They are reused.",
     "pressure test laboratory equipment",
     []),
    ("July the fifteenth, 2022. Dive eighty. Warning six. "
     "Titan is coming back up from the wreck when the passengers hear a loud bang. "
     "The sub's own sensors record it. Afterwards, the hull's strain readings have permanently shifted. "
     "Investigators later concluded that bang was the carbon fibre delaminating. Its layers coming apart. "
     "Titan keeps diving.",
     "underwater bubbles deep sea darkness",
     []),
    ("That same year, the CEO told CBS News what he thought about safety. "
     "At some point, safety just is pure waste. "
     "If you just want to be safe, don't get out of bed.",
     "empty bedroom morning light",
     ["Stockton Rush OceanGate"]),
    ("June the eighteenth, 2023. Dive eighty-eight. Five people climb inside. "
     "Stockton Rush, the CEO, is the pilot. With him, Paul-Henri Nargeolet, a French deep-sea explorer and Titanic expert. "
     "Hamish Harding, a British businessman. Shahzada Dawood, and his son, Suleman. "
     "The hatch is bolted shut. It can only be opened from the outside.",
     "submarine hatch bolts close up",
     ["Polar Prince", "OceanGate Titan"]),
    ("At 9:18 Titan begins its descent. Every fifteen minutes, a text. Every few seconds, an automatic ping. "
     "At about two thousand two hundred metres: all good here. "
     "At 10:47, deeper than three thousand three hundred metres: dropped two weights. "
     "The last ping arrives six seconds later.",
     "deep sea descent dark blue water",
     []),
    ("On the ship above, people had heard a loud bang. "
     "It was later determined to be the sound of Titan imploding. Death was instant. "
     "James Cameron believes they had dropped their weights and were coming up, trying to manage an emergency.",
     "dark ocean surface night ship",
     []),
    ("For four days, the world watched a search for survivors. "
     "But a US Navy system had already picked up an acoustic signal consistent with an implosion. "
     "On June the twenty-second, a robot found the debris. "
     "About five hundred metres from the bow of the Titanic.",
     "search and rescue ship ocean",
     ["Titan submersible debris Coast Guard", "Titan submersible debris"]),
    ("James Cameron directed the film Titanic, and has dived to the real wreck thirty-three times. "
     "He said he was struck by the similarity. Both disasters, he said, seemed preventable. "
     "Both were caused by someone ignoring safety warnings from others. "
     "In 1912, the warnings were about ice. In 2023, they were emails, a report, a letter, and a bang on dive eighty.",
     "iceberg dark ocean",
     ["James Cameron director", "Titanic iceberg 1912"]),
    ("In August 2025, the US Coast Guard published its findings. The word it used was preventable. "
     "It pointed to an uncertified carbon fibre hull, a failure to investigate earlier problems, "
     "and a culture that suppressed employees' concerns. "
     "It concluded the loss of five lives could have been avoided.",
     "official report documents",
     ["United States Coast Guard"]),
    ("Every one of those warnings is on the record. The emails. The report. The letter. The bang. "
     "Titan did not fail without warning. It failed after six of them.",
     "deep ocean darkness fade",
     ["RMS Titanic wreck"]),
]


# Designed cards per beat (index into BEATS). Every quote and number is copied
# verbatim from the Wikipedia source; these are the shots that carry information.
CARDS = {
    1: [{"kind": "quote", "text": "There's a rule you don't do that. Well, I did.",
         "by": "Stockton Rush, OceanGate CEO, 2021"}],
    2: [{"kind": "quote", "text": "...could result in physical injury, disability, emotional trauma or death.",
         "by": "Titan passenger waiver"}],
    3: [{"kind": "title", "text": "WARNING", "sub": "1 / 6"},
        {"kind": "email", "from": "Mark Negley", "to": "Stockton Rush", "date": "March 2018",
         "subject": "Titan hull analysis",
         "body": "We think you are at high risk of a significant failure at or before you reach 4,000 meters. We do not think you have any safety margin.",
         "highlight": "high risk of a significant failure"}],
    4: [{"kind": "title", "text": "WARNING", "sub": "2 / 6"},
        {"kind": "quote", "text": "In your race to Titanic you are mirroring that famous catch cry: She is unsinkable.",
         "by": "Rob McCallum, email to Stockton Rush, 2018"}],
    5: [{"kind": "title", "text": "WARNING", "sub": "3 / 6"},
        {"kind": "stat", "value": "1,300 m", "label": "viewport certified depth"}],
    6: [{"kind": "title", "text": "WARNING", "sub": "4 / 6"},
        {"kind": "quote", "text": "Unanimous concern regarding the development of TITAN.",
         "by": "Draft letter, submarine industry, 2018"}],
    7: [{"kind": "title", "text": "WARNING", "sub": "5 / 6"},
        {"kind": "stat", "value": "50 dives", "label": "until the first hull cracked"}],
    8: [{"kind": "title", "text": "WARNING", "sub": "6 / 6"},
        {"kind": "stat", "value": "DIVE 80", "label": "15 July 2022: the loud bang"}],
    9: [{"kind": "quote", "text": "At some point, safety just is pure waste.",
         "by": "Stockton Rush, CBS News, 2022"}],
    11: [{"kind": "stat", "value": "3,346 m", "label": "last ping, 10:47:33"}],
    15: [{"kind": "title", "text": "PREVENTABLE", "sub": "US COAST GUARD, 2025"}],
}


def main():
    words = len(HOOK.split()) + sum(len(t.split()) for t, _, _ in BEATS)
    brief = {
        "title": TITLE,
        "alt_titles": ["Titan: Every Warning Before the Titanic Dive", "The Titanic Sub Was Warned Six Times"],
        "topic": "deep sea submersible ocean, the 2023 Titan submersible implosion",
        "format_slug": "engineering-failures",
        "hook": HOOK,
        "hook_photos": HOOK_PHOTOS,
        "substance": [
            {"claim": "March 2018: a Boeing engineer emailed Rush: high risk of failure at or before 4,000 m.", "source": "Wikipedia: Titan submersible implosion"},
            {"claim": "McCallum emailed: 'In your race to Titanic you are mirroring that famous catch cry: She is unsinkable'.", "source": "Wikipedia: Titan submersible implosion"},
            {"claim": "Dive 80 (15 Jul 2022) loud acoustic event; USCG found it was the carbon fibre delaminating.", "source": "Wikipedia: Titan submersible implosion"},
            {"claim": "Final text 'dropped two wts' at 10:47:27; last ping 10:47:33 at ~3,346 m.", "source": "Wikipedia: Titan submersible implosion"},
            {"claim": "USCG Aug 2025 report called it 'preventable'.", "source": "Wikipedia: Titan submersible implosion"},
        ],
        "beats": [{"beat": i + 1, "narration": t, "visual": v, "photos": ph, "cards": CARDS.get(i, []),
                   "seconds": round(len(t.split()) / 2.6, 1)} for i, (t, v, ph) in enumerate(BEATS)],
        "description": ("Titan imploded on 18 June 2023 on its way to the Titanic. Before that dive, there was a Boeing "
                        "engineer's email, a specialist's 'she is unsinkable' warning, an internal safety report, an "
                        "industry letter, a cracked hull, and a bang on dive 80. The US Coast Guard later called it "
                        "preventable.\n\nSource: Wikipedia, 'Titan submersible implosion', and the sources it cites."),
        "tags": ["Titan submersible", "Titanic", "OceanGate", "engineering failure", "Stockton Rush"],
        "hashtags": ["#titanic", "#engineering", "#oceangate"],
        "thumbnail_text": "THEY WERE WARNED",
        "handwritten": True,
        "word_count": words,
        "gate": {"passed": True},
    }
    OUT.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT.name, words, "words,", len(BEATS), "beats")


if __name__ == "__main__":
    main()
