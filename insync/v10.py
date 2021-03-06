# -*- coding: utf-8 -*-
#
# Alfa-Bank INSYNC.BY API
#

from __future__ import print_function, unicode_literals
from six.moves.urllib.parse import urlparse, urlunparse
from six.moves import dbm_gnu as gdbm
import six

from datetime import datetime
from requests.adapters import HTTPAdapter
import requests
import socket
import errno
import json


class InsyncException(Exception):
    pass


class InsyncAdapter(HTTPAdapter):
    def __init__(self, hostname, **kwargs):
        self._assert_hostname = hostname
        self.__attrs__.extend([b'_assert_hostname', b'__attrs__'])
        super(InsyncAdapter, self).__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['assert_hostname'] = self._assert_hostname
        super(InsyncAdapter, self).init_poolmanager(*args, **kwargs)


class client:
    lang = 'en'
    devname = 'Android (insync.by py api)'
    appname = 'Android/5.9.1'
    agent = 'okhttp/3.12.5'

    url = 'https://insync2.alfa-bank.by/mBank256/v10/'
    raw = None     # raw url to use during session, i.e.
                   # https://<ip>:<port>/mBank256/...

    sess = None    # requests.session
    sessid = None  # X-Session-ID header
    devid = None   # device id (uuid)

    debug = False  # print each request/reply to stdout

    def __getstate__(self):
        return self.__dict__.copy()

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __init__(self, insyncdb_filename):
        url = urlparse(self.url)
        addr = socket.gethostbyname(url.hostname)
        port = url.port
        if port is None:
            port = 443 if url.scheme == 'https' else 80

        self.raw = urlunparse(
            url._replace(netloc='{0}:{1}'.format(addr, port))
        )

        self.sess = requests.session()
        self.sess.headers['User-Agent'] = self.agent
        self.sess.headers['X-Client-App'] = self.appname
        self.sess.headers['Accept-Encoding'] = 'gzip'
        self.sess.headers['Accept'] = None
        self.sess.headers['Host'] = url.hostname
        self.sess.mount(url.scheme + '://', InsyncAdapter(url.hostname))

        self.dbfile = insyncdb_filename
        db = gdbm.open(self.dbfile, 'w')

        self.devid = db['uuid'].decode()
        if b'token' in db:
            self.token = db['token'].decode()
        else:
            self.token = None

        db.close()

    # low-level request interface
    def request(self, path, payload=None, params=None):
        kwargs = { 'headers': {} }

        if payload is not None:
            kwargs['headers']['Content-Type'] = \
                'application/json; charset=UTF-8'

        if self.sessid is not None:
            kwargs['headers']['X-Session-ID'] = self.sessid

        if self.debug:
            if payload is not None:
                print('REQUEST: .../%s %s' %
                      (path, json.dumps(payload, indent=4)))
            else:
                print('REQUEST: .../%s' % (path,))

        if payload is not None:
            method = 'POST'
            kwargs['json'] = payload
        else:
            method = 'GET'

        if params is not None:
            kwargs['params'] = params

        kwargs['timeout'] = (30, 90)

        r = self.sess.request(method, self.raw + path, **kwargs)

        if r.status_code >= 400:
            reason = ''
            errmsg = ''

            try:
                reply = json.loads(r.text)
                reason = reply['message']
            except:
                pass

            if reason:
                if 400 <= r.status_code < 500:
                    errmsg = '%s Client Error: %s' % (r.status_code, reason)

                elif 500 <= r.status_code < 600:
                    errmsg = '%s Server Error: %s' % (r.status_code, reason)

            if errmsg:
                if six.PY2:
                    errmsg = errmsg.encode('utf-8')

                raise requests.HTTPError(errmsg, response=r)

        r.raise_for_status()

        if self.debug:
            print('REPLY: %s' % (json.dumps(r.json(), indent=4),))

        return r.json()

    # check device status
    def check_device_status(self):
        reply = self.request(
            'CheckDeviceStatus',
            {
                'deviceId': self.devid,
                'locale': self.lang
            },
            {
                'lang': self.lang
            }
        )

        if 'status' not in reply or \
           not isinstance(reply['status'], six.string_types):
            raise InsyncException('Cant check device status')

        return reply

    # login interface
    def login(self):
        assert self.token is not None, \
            'Empty token (please register before login)'

        # check device status (retrieve session id)
        self.sessid = None
        device = self.check_device_status()

        if device['status'] != 'ACTIVE':
            raise InsyncException('Device not active: %s', (device['status'],))

        self.sessid = device['sessionId']

        # perform login
        reply = self.request(
            'LoginByToken',
            {
                'deviceId':  self.devid,
                'token':     self.token,
                'tokenType': 'PIN'
            }
        )

        if 'status' not in reply or \
           not isinstance(reply['status'], six.string_types):
            raise InsyncException('Cant login: bad reply')

        if reply['status'] == 'TOKEN_EXPIRED':
            self.token = reply['token']
            db = gdbm.open(self.dbfile, 'w')
            db['token'] = self.token
            db.close()
            self.login()
            return

        if reply['status'] != 'OK':
            raise InsyncException('Cant login: %s', (reply['status'],))

    # def logout interface
    def logout(self):
        try:
            self.request('Logout')
        except requests.ConnectionError as e:
            # find IOError exception in arguments
            ioerror = None
            exception = e
            while ioerror is None and exception is not None:
                args = exception.args
                exception = None
                for arg in args:
                    if isinstance(arg, IOError) and arg.errno is not None:
                        ioerror = arg
                        break
                    if isinstance(arg, Exception):
                        exception = arg
                        break

            # ignore exception if connection was reset by peer
            if ioerror is None or ioerror.errno != errno.ECONNRESET:
                raise

        self.sess = None
        self.raw = None
        return

    # auth interface
    def auth(self, **kwargs):
        request = {
            # required fiels in options (resident)
            'isResident':   True,
            #'login':       '',
            #'documentNum': '',
            #'issueDate':   '',
            # auto fields
            'deviceId':     self.devid,
            'deviceName':   self.devname,
            'screenHeight': 1200,
            'screenWidth':  768
        }

        request.update(kwargs)

        reply = self.request(
            'Authorization',
            request,
            {
                'lang': self.lang
            }
        )

        if 'status' not in reply or \
           not isinstance(reply['status'], six.string_types):
            raise InsyncException('Cant auth: bad reply')

        if reply['status'] != 'OK':
            raise InsyncException('Cant auth: %s' % (reply['status'],))

    # auth confirm interface
    def auth_confirm(self, otp):
        reply = self.request(
            'AuthorizationConfirm',
            {
                'deviceId': self.devid,
                'tokenType': 'PIN',
                'otp': otp
            },
            {
                'lang': self.lang
            }
        )

        if 'status' not in reply or \
           not isinstance(reply['status'], six.string_types):
            raise InsyncException('Cant confirm auth: bad reply')

        if reply['status'] != 'OK':
            raise InsyncException('Cant confirm auth: %s' % (reply['status'],))

        self.sessid = reply['sessionId']
        self.token = reply['token']
        db = gdbm.open(self.dbfile, 'w')
        db['token'] = self.token
        db.close()

    def desktop(self):
        return self.request('Desktop', {'deviceId': self.devid})

    def history(self, **kwargs):
        '''
          Optional request arguments:
            maxAmount: int,
            minAmount: int,
            maxDate: string (20170422134511)
            minDate: string (20150422134511)
            direction: enum/string:
              EXPENSE
              INCOME
              ALL
            transactionType: enum/string
              cd - Terminal operations
              tr - Transfers
              cv - Currency exchange
              at - ATM cash withdrawals
              fe - Bank fee
              ch - Cash desk operations
              er - SSIS payments
        '''
        args = {
            'offset': 0,
            'pageSize': 15,
            'shortcutId': ''
        }
        args.update(kwargs)
        return self.request('History', args)

    def products(self, product):
        return self.request('Products', {'type': product})

    def account_info(self, accountid, source='PRODUCT'):
        return self.request('Account/Info', {
            'id': accountid,
            'operationSource': source
        })

    def deposit_info(self, depositid, source='PRODUCT'):
        return self.request('Deposit/Info', {
            'id': depositid,
            'operationSource': source
        })

    def loan_info(self, loanid, source='PRODUCT'):
        return self.request('Loan/Info', {
            'id': loanid,
            'operationSource': source
        })

    def card_info(self, debitcardid, source='PRODUCT'):
        return self.request('Card/Info', {
            'id': debitcardid,
            'operationSource': source
        })

    def statement_show(self, date_from, date_to, objid, type_='ACCOUNT'):
        reply = self.request('Statement/Show', {
            'dateFrom': date_from,
            'dateTo': date_to,
            'objectId': objid,
            'type': type_
        })
        return reply['text']

    # performance logging
    # rq: DESKTOP_LOAD
    #     START_TO_PROMPT
    # ts: time in milliseconds
    def log(self, rq=None, ts=0):
        return self.request('Log', {
            'deviceId': self.devid,
            'rq': rq,
            'ts': ts
        })

    # desktop shortcuts methods
    def add_product_shortcut(self, type_, id_):
        return self.request('AddProductShortcut', {
            'type': type_,
            'id': id_
        })

    def del_product_shortcut(self, type_, id_):
        return self.request('RemoveProductShortcut', {
            'type': type_,
            'id': id_
        })

    def del_shortcut(self, id_):
        return self.request('DesktopDelete', {
            'shortcutId': id_
        })

    # shortcut ids
    def transfer(self, srcid, dstid, amount, source='DESKTOP'):
        form = self.request('OwnTransfer/Form', {
            'sourceId': str(srcid),
            'destinationId': str(dstid),
            'operationSource': source
        })

        if 'transactionId' not in form:
            raise InsyncException('Bad form: transactionId not found')

        data = self.request('OwnTransfer/Data', {
            'transactionId': form['transactionId'],
            'amount': amount
        })

        if 'status' not in data or \
           not isinstance(data['status'], six.string_types):
            raise InsyncException('Cant transfer: bad data reply')

        if data['status'] != 'OK':
            raise InsyncException('Cant transfer: %s' % (data['status'],))

        return

    # schedules
    def schedules_accounts(self):
        return self.request('Schedules/Accounts')

    def schedules_plans(self):
        return self.request('Schedules/Plans')

    def summary(self):
        accounts = set()
        summary = {
            'accounts': [],
            'deposits': [],
            'loans': []
        }

        for account in self.products('ACCOUNT')['items']:
            accounts.add(account['info']['description'])
            summary['accounts'].append({
                'id': account['id'],
                'title': account['info']['title'],
                'number': account['info']['description'],
                'description': account['info']['description'],
                'currency': account['info']['amount']['currency'],
                'amount': account['info']['amount']['amount']
            })

        for deposit in self.products('DEPOSIT')['items']:
            info = self.deposit_info(deposit['id'])
            due = info['dueDate']
            summary['deposits'].append({
                'id': deposit['id'],
                'title': deposit['info']['title'],
                'number': deposit['info']['description'],
                'description': info['productName'].strip(),
                'currency': deposit['info']['amount']['currency'],
                'amount': deposit['info']['amount']['amount'],
                'rate': info['rate'],
                'due': '%s-%s-%s' % (due[0:4], due[4:6], due[6:8])
            })

        for loan in self.products('CREDIT')['items']:
            info = self.loan_info(loan['id'])
            summary['loans'].append({
                'id': loan['id'],
                'title': loan['info']['title'],
                'number': loan['info']['description'],
                'description': info['productName'].strip(),
                'currency': loan['info']['amount']['currency'],
                'amount': loan['info']['amount']['amount'],
                'rate': info['rate']
            })

            if 'accountNumber' in info and info['accountNumber'] not in accounts:
                account = self.account_info(info['objectId'])
                summary['accounts'].append({
                    'id': account['objectId'],
                    'title': account['info']['title'],
                    'number': account['info']['description'],
                    'description': account['info']['description'],
                    'currency': account['info']['amount']['currency'],
                    'amount': account['info']['amount']['amount']
                })
                accounts.add(account['info']['description'])

        return summary
