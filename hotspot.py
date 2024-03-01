'''This module provides the Hotspot functionality.

The Hotspot functionality is used for accessing the Webserver that serves the
current coffee stats.
'''

import network
import rp2

def wap_create() -> None:
    '''Setup the Hotspot'''
    rp2.country('DE')
    wap = network.WLAN(network.AP_IF)
    wap.config(essid='Kaffee GSS', password='!Secret1')
    wap.active(True)
    # Ausgabe der Netzwerk-Konfiguration
    net_config = wap.ifconfig()
    print('IPv4-Adresse:', net_config[0], '/', net_config[1])
    print('Standard-Gateway:', net_config[2])
    print('DNS-Server:', net_config[3])

if __name__ == '__main__':
    print("not meant for standalone configuration")
