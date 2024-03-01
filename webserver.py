'''the Webserver that actually serves the Kaffee information.'''

from phew import logging, server
from phew.template import render_template
from phew.server import redirect

import time
# from typing import Optional, List, Tuple

DOMAIN: str = "kaffee-counter.local"

@server.route("/", methods=['GET'])
def index(request):
    """ Render the Index page"""
    if request.method == 'GET':
        logging.debug("Get request")
        return render_template("resources/index.html")

# microsoft windows redirects
@server.route("/ncsi.txt", methods=["GET"])
def hotspot_win_1(request):
    print(request)
    print("ncsi.txt")
    return "", 200


@server.route("/connecttest.txt", methods=["GET"])
def hotspot_win_2(request):
    print(request)
    print("connecttest.txt")
    return "", 200


@server.route("/redirect", methods=["GET"])
def hotspot_win_3(request):
    print(request)
    print("****************ms redir*********************")
    return redirect(f"http://{DOMAIN}/", 302)

# android redirects
@server.route("/generate_204", methods=["GET"])
def hotspot_android(request):
    print(request)
    print("******generate_204********")
    return redirect(f"http://{DOMAIN}/", 302)

# apple redir
@server.route("/hotspot-detect.html", methods=["GET"])
def hotspot_apple(request):
    """ Redirect to the Index Page """
    print(request)
    return render_template("index.html")

@server.catchall()
def catchall(request):
    '''The catchall implementations'''
    return redirect(f"http://{DOMAIN}/")

def init_webserver():
    '''Initialisiere den Webserver.'''
    print("Starte Server...")
    server.run()
    print()
    print("Server gestartet.")
