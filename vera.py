import requests
import urllib, urllib.parse
import random
import base64, json

DEBUG_REQUESTS = False

VERA_BASE               = "https://home.getvera.com/"
VERA_API_URL            = VERA_BASE + "api/"
VERA_LOGIN_URL          = VERA_API_URL + "users/action_login"
VERA_LIST_UNITS_URL     = VERA_API_URL + "dashboard/listunits"
VERA_INFO_URL           = VERA_API_URL + "devicegotoui/getinfo?"
VERA_URL_ENCODE_SAFE_CHARS = ':/'

XML_REQUEST_HEADER = {
    'X-Requested-With': 'XMLHttpRequest'
}


if DEBUG_REQUESTS:
    import logging
    import http.client as http_client
    http_client.HTTPConnection.debuglevel = 1
    
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True


class VeraControl:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        
        self.login()
        self.getUnit()
        self.getUnitInfo()
        self.connetRelayServer()
        self.setRelayMMSSession()
        self.setRelayMMSAuth()
        
    
    def login(self):
        loginData = {
            'login_id': self.username,
            'login_pass': self.password
        }
        
        loginReq = requests.post(VERA_LOGIN_URL, data = loginData, headers= XML_REQUEST_HEADER)
        loginData = loginReq.json()
        
        if loginReq.status_code != 200:
            raise RuntimeError("Login failed")
        
        if loginData['status'] != 200:
            raise RuntimeError("Login failed: check username and password")
        
        if loginData['errors'] :
            raise RuntimeError("Login failed: " + loginData['errors'])
        
        self.loginCookies = loginReq.cookies

    def getUnit(self):
        listUnitsReq = requests.get(VERA_LIST_UNITS_URL, headers = XML_REQUEST_HEADER, cookies = self.loginCookies)
        
        if (listUnitsReq.status_code != 200):
            raise RuntimeError("List units failed")
        
        units = listUnitsReq.json()
        
        if len(list(units['quick'].keys()))<1:
            raise RuntimeError("No units found or bad data", listUnitsReq.text)
        
        firstUnitSerial = list(units['quick'].keys())[0]
        firstUnitName   = units['quick'][firstUnitSerial]['name']
        print('Using first unit found:', firstUnitSerial, firstUnitName)
        
        self.unit = firstUnitSerial
    
    def getUnitInfo(self):

        infoURL = VERA_INFO_URL + urllib.parse.urlencode({'serial': self.unit})
        infoReq = requests.get(infoURL, cookies = self.loginCookies)
        
        if (infoReq.status_code != 200):
            raise RuntimeError("Unit info failed")
        
        self.unitInfo = infoReq.json()
        
        # (optional) getting extended data from mms_auth:
        # authData = json.loads(base64.b64decode(self.unitInfo.get('info_mms_auth')))
    
    def connetRelayServer(self):
        redirectData = {
            'PK_Device':    self.unitInfo.get('pk_device'),
            'InternalIp':   self.unitInfo.get('internalip'),
            'LocalPort':    self.unitInfo.get('localport'),
            'RedirectUrl':  self.unitInfo.get('relay_show_url_relative'),
            'ReturnUrl':    self.unitInfo.get('returnurl'),
            'MMSAuth':      self.unitInfo.get('MMSAuth'),
            'MMSAuthSig':   self.unitInfo.get('MMSAuthSig'),
            'MMSSession':   self.unitInfo.get('key'),
            'lang':         'en'
        }
        
        for key in redirectData:
            if not redirectData[key]:
                raise ValueError('Missing data in info request', key)
        
        redirectReq = requests.post(self.unitInfo.get('relay_redirect_url'), data = redirectData)
        
        # the post requests should return a redirect.
        if len(redirectReq.history) != 1:
            raise RuntimeError("Bad redirect")
        
        # Access the response before the redirect
        redirectOrgRes = redirectReq.history[0] 
        
        if (redirectOrgRes.status_code != 302) or (redirectReq.status_code != 200):
            raise RuntimeError("Relay unexpected status code")
        
        self.relayCookies = redirectOrgRes.cookies
        if 'MiOS' not in self.relayCookies:
            raise RuntimeError("Missing MiOS cookie in redirect")
        
        self.MiOSRedirectCookie = urllib.parse.unquote(self.relayCookies['MiOS']).split(',')
        
        if (len(self.MiOSRedirectCookie) < 4):
            raise RuntimeError("Relay unexpected MiOS cookie content")
        
        # (optional) getting extended data from MiOS cookie
        # authDataRedirect = json.loads(base64.b64decode(self.MiOSRedirectCookie[0]))

    def setRelayMMSSession(self):

        self.proxyServer = self.unitInfo.get('relay_redirect_url').split('/')[2] # like vera-us-oem-relay52.mios.com
        
        proxyAuth = self.MiOSRedirectCookie[0]
        proxyAuthSig = self.MiOSRedirectCookie[1]
        
        self.proxyHeaders = {
            'MMSProxyAuth':     proxyAuth,
            'MMSProxyAuthSig':  proxyAuthSig,
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        random.seed()
        
        proxyRelayParams = {
            'url': 'https://' + self.proxyServer + '/info/session/token',
            'rand': str(random.random())
        }
        
        proxyRelayURL = 'https://' + self.proxyServer + '/relay/relay/proxy?' + urllib.parse.urlencode(proxyRelayParams, safe=VERA_URL_ENCODE_SAFE_CHARS)
        
        proxyRelayReq = requests.get(proxyRelayURL, headers = self.proxyHeaders, cookies = self.relayCookies)
        
        if proxyRelayReq.status_code != 200:
            raise RuntimeError("Proxy relay failed")
        
        self.relayMMSSession = proxyRelayReq.text  # like 000000037A42305C8A25BD9BD42C0DC1309DA9
        
        if len(self.relayMMSSession) != 38:
            raise RuntimeError("Proxy relay bad return")
        

    def setRelayMMSAuth(self):
        proxyAccountParams = {
            'url': 'https://' + self.unitInfo.get('server_account') + '/info/session/token',
            'rand': str(random.random())
        }
        
        proxyAccountURL = 'https://' + self.proxyServer + '/relay/relay/proxy?' + urllib.parse.urlencode(proxyAccountParams, safe=VERA_URL_ENCODE_SAFE_CHARS)
        
        proxyAccountReq = requests.get(proxyAccountURL, headers = self.proxyHeaders, cookies = self.relayCookies)
        
        if proxyAccountReq.status_code != 200:
            raise RuntimeError("Proxy account failed")

        self.relayMMSAuth = proxyAccountReq.text  # like 000000037A42305C8A25BD9BD42C0DC1309DA9

        if len(self.relayMMSAuth) != 38:
            raise RuntimeError("Proxy relay bad return")
        
    def dataRequest(self, params):
        requestParamsEncoded = urllib.parse.urlencode(params, safe=VERA_URL_ENCODE_SAFE_CHARS)
        
        requestURL = self.unitInfo.get('relay_redirect_url').replace('uiredirect', 'relay') + '/session/' + self.relayMMSSession + '/port_3480/data_request?' + requestParamsEncoded
        
        requestReq = requests.get(requestURL, headers = XML_REQUEST_HEADER, cookies = self.relayCookies)
        
        if requestReq.status_code != 200:
            raise RuntimeError("DataRequest failed")
        
        return requestReq.text

