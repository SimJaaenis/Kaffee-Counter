# Bibliotheken laden
from machine import Pin
from neopixel import NeoPixel
from time import sleep_ms, sleep

# GPIO-Pin für WS2812
pin_np = 11

# Anzahl der LEDs
leds = 4

# Helligkeit: 0 bis 255
brightness = 10

# Geschwindigkeit (Millisekunden)
speed = 10

# Initialisierung WS2812/NeoPixel
np = NeoPixel(Pin(pin_np, Pin.OUT), leds)

# colors = {
#     'red': (brightness, 0, 0),
#     'blue': (0, 0, brightness),
#     'green': (0, brightness, 0),
#     'yellow': (brightness, brightness, 0),
#     'purple': (0, brightness, brightness),
#     'coral': (brightness, 127, 80),
#     'darkorange': (brightness, 140, 0),
#     'amber': (brightness, 191, 0),
#     'off': (0, 0, 0)
#     }

colors= {
    'red': (brightness, 0, 0),
    'blue': (0, 0, brightness),
    'green': (0, brightness, 0),
    'yellow': (brightness, brightness, 0),
    'cyan': (0, brightness, brightness),
    'magenta': (brightness, 0, brightness),
    'white': (brightness, brightness, brightness),
    'off': (0, 0, 0)
    }

for i in range(leds):
    np[i] = (0,0,0)
np.write()

key_colors = ('red', 'blue', 'green', 'yellow', 'cyan', 'magenta', 'white', 'off')

def led_order(number, color):
    np[number] = colors[color]
    np.write()

def dcf77_led(color):
    if color == 'red':
        np[i] = (brightness, 0, 0)
    elif color == 'yellow':
        np[i] = (brightness, brightness, 0)
    elif color == 'blue':
        np[i] = (0, 0, brightness)
    elif color == 'green':
        np[i] = (0, brightness, 0)
    elif color == 'white':
        np[i] = (brightness, brightness, brightness)
    elif color == 'off':
        np[i] = (0, 0, 0)
    np.write()

# Test Wiederholung (Endlos-Schleife)
#######
# zahl = 0
# while True:
#     color = key_colors[zahl]
#     for i in range(leds):
#         led_order(i, color)
#         sleep(0.05)
#     zahl = zahl + 1
#     if zahl >= len(key_colors):
#         zahl = 0
    
    

