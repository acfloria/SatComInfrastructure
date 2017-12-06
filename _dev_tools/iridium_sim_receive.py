#!/usr/bin/env python
import tornado.web
import tornado.ioloop
import tornado.httpclient
import tornado.httputil

class PostHandler(tornado.web.RequestHandler):
    def post(self):
        try:
            msg = self.request.arguments['data'][0].decode('hex')
            print 'Got msg:', msg
        except:
            print 'Failed to parse POST'

def main():
    http_server = tornado.web.Application([(r"/", PostHandler)])
    http_server.listen(45678)

    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        tornado.ioloop.IOLoop.current().stop()

if __name__ == '__main__':
    main()