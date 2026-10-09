"""Sample life-saving rules used to seed the demonstration.

IMPORTANT: this wording is SAMPLE text written so the confirmation flow can be
shown end to end. It is not Renewi's approved rule set and it is not approved
legal wording. Renewi's life-saving rules, and the legal acknowledgement text
agreed with Renewi's legal and privacy team, must replace it before any real use.
The Dutch text is an unreviewed translation of the sample.

Publishing replacement content means adding a new ``LifeSavingRulesVersion``
with a higher version number and marking it current. Earlier versions, and the
confirmations recorded against them, are kept.
"""

from __future__ import annotations

from typing import Any

SAMPLE_RULES_VERSION = 1

SAMPLE_RULES_CONTENT: dict[str, Any] = {
    "is_sample": True,
    "translations": {
        "en": {
            "title": "Life-saving rules",
            "intro": (
                "These rules protect everyone on site. You must follow them at all "
                "times while you are here. Read each rule, then confirm below."
            ),
            "rules": [
                {
                    "title": "Report in and follow instructions",
                    "text": "Register on arrival and follow the instructions of site staff and signage.",
                },
                {
                    "title": "Wear the required protective equipment",
                    "text": "Use the protective equipment required for the area you are in.",
                },
                {
                    "title": "Keep to the marked routes",
                    "text": "Stay on pedestrian and vehicle routes and do not enter restricted areas.",
                },
                {
                    "title": "Drive safely",
                    "text": "Respect speed limits and give way to pedestrians and moving equipment.",
                },
                {
                    "title": "Never work under the influence",
                    "text": "Do not work or drive after using alcohol or drugs.",
                },
                {
                    "title": "Do not enter confined spaces or work at height without authorisation",
                    "text": "Only do this work with a valid permit and the right safeguards in place.",
                },
                {
                    "title": "Stop and report unsafe situations",
                    "text": "If something is unsafe, stop work and tell site staff straight away.",
                },
            ],
            "statement": (
                "I confirm that I have read and understood the life-saving rules above "
                "and that I will follow them while I am on this site."
            ),
        },
        "nl": {
            "title": "Levensreddende regels",
            "intro": (
                "Deze regels beschermen iedereen op het terrein. U moet ze te allen tijde "
                "naleven zolang u hier bent. Lees elke regel en bevestig hieronder."
            ),
            "rules": [
                {
                    "title": "Meld u aan en volg instructies op",
                    "text": "Meld u bij aankomst en volg de instructies van het personeel en de bebording.",
                },
                {
                    "title": "Draag de vereiste beschermingsmiddelen",
                    "text": "Gebruik de beschermingsmiddelen die voor uw werkgebied vereist zijn.",
                },
                {
                    "title": "Blijf op de gemarkeerde routes",
                    "text": "Blijf op de looproutes en rijroutes en ga niet naar verboden gebieden.",
                },
                {
                    "title": "Rijd veilig",
                    "text": "Houd u aan de maximumsnelheid en geef voorrang aan voetgangers en rijdend materieel.",
                },
                {
                    "title": "Werk nooit onder invloed",
                    "text": "Werk of rijd niet na gebruik van alcohol of drugs.",
                },
                {
                    "title": "Geen toegang tot besloten ruimtes of werk op hoogte zonder toestemming",
                    "text": "Doe dit werk alleen met een geldige vergunning en de juiste voorzorgsmaatregelen.",
                },
                {
                    "title": "Stop en meld onveilige situaties",
                    "text": "Is iets onveilig, stop dan met werken en meld het direct aan het personeel.",
                },
            ],
            "statement": (
                "Ik bevestig dat ik de bovenstaande levensreddende regels heb gelezen en "
                "begrepen en dat ik ze zal naleven zolang ik op dit terrein ben."
            ),
        },
    },
}
