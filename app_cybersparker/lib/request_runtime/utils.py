import random
import urllib.parse


DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def urlparse(address):
    if not address:
        return urllib.parse.urlparse("tcp://")
    if "://" not in str(address):
        address = f"tcp://{address}"
    return urllib.parse.urlparse(address)


def generate_random_user_agent():
    return random.choice(DEFAULT_USER_AGENTS)
