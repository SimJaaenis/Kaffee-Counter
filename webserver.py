'''the Webserver that actually serves the Kaffee information.'''

from phew import logging, server
from phew.template import render_template
from phew.server import redirect
import nutzer_api as kaffeetrinker

import time
# from typing import Optional, List, Tuple

DOMAIN: str = "kaffee-counter.local"

def convert_nutzer_to_html(nutzer_kaffee) -> str:
    """Konvertiere das Nutzer -> Kaffee Mapping zu HTML-Tabelleninhalt."""
    result: str = ""
    if nutzer_kaffee is not None:
        print(f"I will output {len(nutzer_kaffee)} Kaffeetrinker.")
    if len(nutzer_kaffee) > 0:
        for nutzer, anzahl in nutzer_kaffee.items():
            result = result + f"<tr><td>{nutzer}</td><td>{anzahl}</td><td>PLACEHOLDER</td></tr>"
    return result


@server.route("/", methods=['GET'])
def index(request: server.Request):
    """ Render the Index page"""
    if request.method == 'GET':
        logging.debug("Get request")
        kaffeetrinker.read_Nutzer()
        html_table: str = convert_nutzer_to_html(kaffeetrinker.nutzer_kaffee)
        with open("resources/index.html", "r", encoding="utf-8") as f:
            return f.read().replace("{{curr_date}}", "placeholder")\
            .replace("{{coffee_data_table_html}}", html_table)

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
    return index(request)

@server.catchall()
def catchall(request):
    '''The catchall implementations'''
    return redirect(f"http://{DOMAIN}/")

async def run_webserver():
    '''Initialisiere den Webserver.'''
    print("Starte Server...")
    server.run()
    print()
    print("Server gestartet.")
