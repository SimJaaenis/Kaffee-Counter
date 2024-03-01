'''the Webserver that actually serves the Kaffee information.'''

import socket
import time
# from typing import Optional, List, Tuple

html: str
with open('resources/index.html', "r", encoding="utf-8") as f:
    html = f.read()

if len(html) < 100:
    raise FileNotFoundError("HTML could not be found.")

HEARTBEAT_EVERY_SECOND: int = 5
'''How many seconds are between heartbeats on the console.'''

class Webserver:
    '''Der Kaffee Webserver.
    
    Rufe einmal init() auf, dann die task() in der main TaskQueue.'''
    def __init__(self) -> None:
        self.addr = None
        self.server: socket.socket
        self.last_debug_heartbeat = time.time()

    def init_webserver(self):
        '''Initialisiere den Webserver.
        
        MUSS vor der webserver_task() aufgerufen werden!'''
        print("Starte Server...")
        self.addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
        self.server = socket.socket()
        self.server.setblocking(False)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(self.addr)
        self.server.listen(1)
        print("Server hoert auf ", self.addr)
        print()
        print("Server gestartet.")

    def webserver_task(self):
        '''Task for the webserver (to be called in "main" method)'''
        while True:
            if self.server is None or self.addr is None:
                print("Webserver not initialized.")
                yield None
            try:
                self.__do_heartbeat()
                conn, addr = self.server.accept()
                print('HTTP-Request von Client', addr)
                request = conn.recv(1024)
                # HTTP-Request anzeigen
                print('Request:', request)
                # HTTP-Response senden
                response = html % str(addr)
                conn.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
                conn.send(response)
                conn.close()
                print('HTTP-Response gesendet')
                print()
            except OSError:
                #print("OS Error happened in Webserver: " + str(e))
                pass
            except KeyboardInterrupt:
                yield None
            yield

    def __do_heartbeat(self) -> None:
        '''Schreibt periodisch eine Heartbeat message auf die Konsole.'''
        if time.time() > self.last_debug_heartbeat + HEARTBEAT_EVERY_SECOND:
            print("Webserver läuft: ", time.time())
            self.last_debug_heartbeat = time.time()
