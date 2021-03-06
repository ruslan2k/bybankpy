#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals
import json
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import insync


def main():
    i = insync.client(os.path.expanduser('~/lib/insync.db'))
    i.debug = True
    i.login()
    i.desktop()

    h = insync.history(i, os.path.expanduser('~/lib/history.db'))

    # reload all history
    h.reload()

    # check transaction type of each element
    for item in h:
        tt = h.get_type(item)
        print(tt, item['info']['title'])

    # done
    h.close()

    i.logout()

if __name__ == '__main__':
    main()
