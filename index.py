from vera import VeraControl
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=".env", verbose=True)

username = os.getenv("VERA_USERNAME")
password = os.getenv("VERA_PASSWORD")

if not username or not password:
    raise RuntimeError("Missing env variable VERA_USERNAME or VERA_PASSWORD")

action = {
        'id': 'lu_action',
        'action': 'Stop',
        'serviceId': 'urn:upnp-org:serviceId:WindowCovering1',
        'DeviceNum': '16'
    }

vera = VeraControl(username, password)

res = vera.dataRequest(action)
print(res)
    