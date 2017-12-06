#!/usr/bin/env python
import tornado.httpclient
import tornado.ioloop
import tornado.escape
import tornado.httputil
import sys

def handle_response(response):
    if response.error:
        print "Error:", response.error
    else:
        print 'Response code: %s' % response.code
        print 'Response body: %s' % response.body
    tornado.ioloop.IOLoop.current().stop()

def send(data):
    http_client = tornado.httpclient.AsyncHTTPClient()
    data = {'data':data.encode('hex')}
    body = tornado.httputil.urlencode(data)

    if len(sys.argv) == 2:
        if sys.argv[1] == 'l':
            url = 'http://localhost:45679'
        else:
            url = 'http://' + sys.argv[1]
    else:
        url = 'http://129.132.38.186:45679'

    print 'sending request to', url
    request = tornado.httpclient.HTTPRequest(url, method='POST', body=body)
    http_client.fetch(request, handle_response)

try:
    send('TEST MSG')
    tornado.ioloop.IOLoop.current().start()
except KeyboardInterrupt:
    tornado.ioloop.IOLoop.current().stop()