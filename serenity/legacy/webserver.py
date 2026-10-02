from flask import Flask
from threading import Thread

from serenity.config import get_settings

settings = get_settings()

app = Flask("")


@app.route("/")
def home():
    return "Монитор активен."


def run():
    app.run(host=settings.web_host, port=settings.web_port)


def keep_alive():
    t = Thread(target=run)
    t.start()
