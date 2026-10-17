import re

JUSTICE = "<:Justice:1560611219105120257>"
LOADING = "<a:loading:1498065004677566524>"
CLOUDS = "<a:purpleclouds:1498065043521278014>"


def normalize_emojis(text):
    text = re.sub(r"<a?:(?:justice|serenity):\d+>", JUSTICE, text, flags=re.I)
    text = re.sub(r"<a?:loading:\d+>", LOADING, text, flags=re.I)
    return re.sub(r"<a?:(?:cloud|purpleclouds):\d+>", CLOUDS, text, flags=re.I)
