import requests
import urllib, urllib.parse
import random
import base64, json
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", verbose=True)

DEBUG_REQUESTS = False

if DEBUG_REQUESTS:
    import logging
    
    # The only thing missing will be the response.body which is not logged.
    try:
        import http.client as http_client
    except ImportError:
        # Python 2
        import httplib as http_client
    http_client.HTTPConnection.debuglevel = 1
    
    # You must initialize logging, otherwise you'll not see debug output.
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

def printHeader(text):
    print('='*len(text) + '\n' + text + '\n' + '='*len(text) + '\n')


VERA_BASE = "https://home.getvera.com/"
VERA_API_URL = VERA_BASE + "api/"
VERA_LOGIN_URL = VERA_API_URL + "users/action_login"
VERA_LIST_UNITS_URL = VERA_API_URL + "dashboard/listunits"
VERA_INFO_URL  = VERA_API_URL + "devicegotoui/getinfo?"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36'
VERA_URL_ENCODE_SAFE_CHARS = ':/'

XML_REQUEST_HEADER = {
    'X-Requested-With': 'XMLHttpRequest'
}

# ========================================================
printHeader('login')
# ========================================================

username = os.getenv("VERA_USERNAME")
password = os.getenv("VERA_PASSWORD")

if not username or not password:
    raise RuntimeError("Missing env variable VERA_USERNAME or VERA_PASSWORD")

loginData = {
    'login_id': username,
    'login_pass': password
}

loginReq = requests.post(VERA_LOGIN_URL, data = loginData, headers= XML_REQUEST_HEADER)
loginData = loginReq.json()

if loginReq.status_code != 200:
    raise RuntimeError("Login failed")

if loginData['status'] != 200:
    raise RuntimeError("Login failed: check username and password")

if loginData['errors'] :
    raise RuntimeError("Login failed: " + loginData['errors'])

# ========================================================
printHeader('list-units')
# ========================================================


listUnitsReq = requests.get(VERA_LIST_UNITS_URL, headers = XML_REQUEST_HEADER, cookies = loginReq.cookies)

if (listUnitsReq.status_code != 200):
    raise RuntimeError("List units failed")

units = listUnitsReq.json()

if len(list(units['quick'].keys()))<1:
    raise RuntimeError("No units found or bad data", listUnitsReq.text)

firstUnitSerial = list(units['quick'].keys())[0]
firstUnitName   = units['quick'][firstUnitSerial]['name']
print('Using first unit found:', firstUnitSerial, firstUnitName)


# ========================================================
printHeader('info')
# ========================================================

infoURL = VERA_INFO_URL + urllib.parse.urlencode({'serial': firstUnitSerial})
infoReq = requests.get(infoURL, headers={'User-Agent': USER_AGENT}, cookies = loginReq.cookies)

if (infoReq.status_code != 200):
    raise RuntimeError("Info failed")

infoRes = infoReq.json()

# (optional) getting extended data from mms_auth:
# authData = json.loads(base64.b64decode(info_mms_auth))

# ========================================================
printHeader('redirect')
# ========================================================

redirectData = {
    'PK_Device':    infoRes.get('pk_device'),
    'InternalIp':   infoRes.get('internalip'),
    'LocalPort':    infoRes.get('localport'),
    'RedirectUrl':  infoRes.get('relay_show_url_relative'),
    'ReturnUrl':    infoRes.get('returnurl'),
    'MMSAuth':      infoRes.get('MMSAuth'),
    'MMSAuthSig':   infoRes.get('MMSAuthSig'),
    'MMSSession':   infoRes.get('key'),
    'lang':         'en'
}

for key in redirectData:
    if not redirectData[key]:
        raise ValueError('Missing data in info request', key)

redirectReq = requests.post(infoRes.get('relay_redirect_url'), data = redirectData)

# the post requests should return a redirect.
if len(redirectReq.history) != 1:
    raise RuntimeError("Bad redirect")

# Access the response before the redirect
redirectOrgRes = redirectReq.history[0] 

if (redirectOrgRes.status_code != 302) or (redirectReq.status_code != 200):
    raise RuntimeError("Relay unexpected status code")

if 'MiOS' not in redirectOrgRes.cookies:
    raise RuntimeError("Missing MiOS cookie in redirect")

MiOSRedirectCookie = urllib.parse.unquote(redirectOrgRes.cookies['MiOS']).split(',')

if (len(MiOSRedirectCookie) < 4):
    raise RuntimeError("Relay unexpected MiOS cookie content")

# (optional) getting extended data from MiOS cookie
# authDataRedirect = json.loads(base64.b64decode(MiOSRedirectCookie[0]))


# ========================================================
printHeader('proxy-relay')
# ========================================================

proxyServer = infoRes.get('relay_redirect_url').split('/')[2] # like vera-us-oem-relay52.mios.com

proxyAuth = MiOSRedirectCookie[0]
proxyAuthSig = MiOSRedirectCookie[1]

proxyHeaders = {
    'MMSProxyAuth':     proxyAuth,
    'MMSProxyAuthSig':  proxyAuthSig,
    'X-Requested-With': 'XMLHttpRequest'
}

random.seed()

proxyRelayParams = {
    'url': 'https://' + proxyServer + '/info/session/token',
    'rand': str(random.random())
}

proxyRelayURL = 'https://' + proxyServer + '/relay/relay/proxy?' + urllib.parse.urlencode(proxyRelayParams, safe=VERA_URL_ENCODE_SAFE_CHARS)

proxyRelayReq = requests.get(proxyRelayURL, headers = proxyHeaders, cookies = redirectOrgRes.cookies)

if proxyRelayReq.status_code != 200:
    raise RuntimeError("Proxy relay failed")

proxyMMSSession = proxyRelayReq.text  # like 000000037A42305C8A25BD9BD42C0DC1309DA9

if len(proxyMMSSession) != 38:
    raise RuntimeError("Proxy relay bad return")


# ========================================================
printHeader('proxy-account')
# ========================================================

proxyAccountParams = {
    'url': 'https://' + infoRes.get('server_account') + '/info/session/token',
    'rand': str(random.random())
}

proxyAccountURL = 'https://' + proxyServer + '/relay/relay/proxy?' + urllib.parse.urlencode(proxyAccountParams, safe=VERA_URL_ENCODE_SAFE_CHARS)

proxyAccountReq = requests.get(proxyAccountURL, headers = proxyHeaders, cookies = redirectOrgRes.cookies)

proxyProxySession = proxyAccountReq.text  # like 000000037A42305C8A25BD9BD42C0DC1309DA9

if proxyAccountReq.status_code != 200:
    raise RuntimeError("Proxy account failed")

if len(proxyProxySession) != 38:
    raise RuntimeError("Proxy relay bad return")


# ========================================================
printHeader('action')
# ========================================================

actionParams = {
    'id': 'lu_action',
    'action': 'Stop',
    'serviceId': 'urn:upnp-org:serviceId:WindowCovering1',
    'DeviceNum': '16'
}

actionParamsEncoded = urllib.parse.urlencode(actionParams, safe=VERA_URL_ENCODE_SAFE_CHARS)

actionURL = infoRes.get('relay_redirect_url').replace('uiredirect', 'relay') + '/session/' + proxyMMSSession + '/port_3480/data_request?' + actionParamsEncoded

actionReq = requests.get(actionURL, headers = XML_REQUEST_HEADER, cookies = redirectOrgRes.cookies)

if actionReq.status_code != 200:
    raise RuntimeError("Action failed")

print(actionReq.text)

