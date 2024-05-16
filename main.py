import uasyncio
from time import sleep_ms, time
from machine import I2C, Pin
import utime
from lib.urtc import DS1307
from pico_i2c_lcd import I2cLcd
from mfrc522 import MFRC522
from sys import stdout

# our libraries
from buzzer_api import *
from neopixel_api import *
from nutzer_api import *
from hotspot import wap_create
import webserver

######## Definitionen

goldTag = 234973
silverTag = 623906047
bronzeTag = 281526448

#goldTag = 629409519
#silberTag = 623906047
#bronzeTag = 1982696638

#### Uhr
# i2c_lcd = machine.I2C(1,scl=Pin(15),sda=Pin(14),freq=400000)

# lcd = I2cLcd(i2c_lcd, 0x27, 2, 16)

# i2c_rtc = machine.I2C(0,scl = Pin(17),sda = Pin(16),freq = 400000)
# result = I2C.scan(i2c_rtc)
# rtc = DS1307(i2c_rtc)

# async def Uhr():
#     while True:
#         (year,month,date,day,hour,minute,second,p1)=rtc.datetime()
#         # lcd.clear()
#         lcd.move_to(0,0)
#         lcd.putstr(" Zeit:")
#         lcd.move_to(7,0)
#         lcd.putstr(str("%02d"%hour) + ":" + str("%02d"%minute) + ":" + str("%02d"%second))
#         lcd.move_to(0,1)
#         lcd.putstr("Datum:")
#         lcd.move_to(7,1)
#         lcd.putstr(str("%02d"%date) + "." + str("%02d"%month) + "." + str("%02d"%year)[2:])
#         utime.sleep(0.01)
#         await uasyncio.sleep_ms(10) 

# #### Karte
# reader = MFRC522(spi_id=0,sck=6,miso=4,mosi=7,cs=5,rst=22)
 
# print("Bring TAG closer...")
# print("")
# async def Karte():
#     while True:
#         global reader
#         reader.init()
#         (stat, tag_type) = reader.request(reader.REQIDL)
#         if stat == reader.OK:
#             (stat, uid) = reader.SelectTagSN()
#             if stat == reader.OK:
#                 cardID = int.from_bytes(bytes(uid),"little",False)
#                 print(str(cardID))
#                 known_user = known_User(cardID)
#                 if not known_User(cardID):
#                     if cardID == goldTag:
#                         ###### Gold Tag
#                         buzzer()
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("GOLD TAG Erkannt")
#                         sleep_ms(1000)
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Warten auf Tag:")
#                         buzzer()
#                         neuerTagGelesen = False
#                         while neuerTagGelesen == False:
#                             reader.init()
#                             (stat2, tag_type2) = reader.request(reader.REQIDL)
#                             if stat2 == reader.OK:
#                                 (stat2, uid2) = reader.SelectTagSN()
#                                 if stat2 == reader.OK:
#                                     cardIDtoReset = int.from_bytes(bytes(uid2),"little",False)
#                                     neuerTagGelesen = True
#                                     lcd.clear()
#                                     lcd.move_to(0,0)
#                                     if not known_User(cardIDtoReset):
#                                         lcd.putstr("Nutzer unbekannt")
#                                         led_order(0, 'red')
#                                         error()
#                                         led_order(0, 'off')
#                                         error()
#                                         led_order(0, 'red')
#                                         error()
#                                         led_order(0, 'off')
#                                         lcd.clear()
#                                     else:
#                                         lcd.putstr("ID:")
#                                         lcd.move_to(4,0)
#                                         lcd.putstr(get_Nutzer(cardIDtoReset))
#                                         lcd.move_to(0,1)
#                                         lcd.putstr("Anzahl: ")
#                                         lcd.move_to(8,1)
#                                         lcd.putstr(reset_Nutzer(cardIDtoReset))
#                                         led_order(0, 'green')
#                                         buzzer()
#                                         led_order(0, 'off')
#                                         buzzer()
#                                         led_order(0, 'green')
#                                         buzzer()
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(10000)
#                                         lcd.clear()
#                     elif cardID == silverTag:
#                         ###### Silber Tag
#                         buzzer()
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("SILBER TAG")
#                         lcd.move_to(0,1)
#                         lcd.putstr("erkannt")
#                         sleep_ms(1000)
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Warten auf Tag:")
#                         buzzer()
#                         readNewTag = False
#                         while readNewTag == False:
#                             reader.init()
#                             (stat3, tag_stat2) = reader.request(reader.REQIDL)
#                             if stat3 == reader.OK:
#                                 (stat3, uid3) = reader.SelectTagSN()
#                                 if stat3 == reader.OK:
#                                     cardIDReadOut = int.from_bytes(bytes(uid3),"little",False)
#                                     readNewTag = True
#                                     lcd.clear()
#                                     lcd.move_to(0,0)
#                                     if not known_User(cardIDReadOut):
#                                         lcd.putstr("Nutzer unbekannt")
#                                         led_order(0, 'red')
#                                         error()
#                                         led_order(0, 'off')
#                                         error()
#                                         led_order(0, 'red')
#                                         error()
#                                         led_order(0, 'off')
#                                         lcd.clear()
#                                     else:
#                                         lcd.putstr("ID:")
#                                         lcd.move_to(4,0)
#                                         lcd.putstr(get_Nutzer(cardIDReadOut))
#                                         lcd.move_to(0,1)
#                                         lcd.putstr("Anzahl: ")
#                                         lcd.move_to(8,1)
#                                         lcd.putstr(get_Nutzer_Coffee(cardIDReadOut))
#                                         buzzer()
#                                         led_order(0, 'yellow')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'yellow')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'yellow')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'yellow')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'yellow')
#                                         utime.sleep_ms(150)
#                                         led_order(0, 'off')
#                                         utime.sleep_ms(2000)
#                                         lcd.clear()
#                     elif cardID == bronzeTag:
#                         ###### Demo Tag ohne User hinzuzufügen
#                         led_order(0, 'red')
#                         error()
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Nutzer unbekannt")
#                         utime.sleep_ms(2000)
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Neuer Nutzer")
#                         lcd.move_to(0,1)
#                         lcd.putstr('hinzugef\xF5gt NO')
#                         utime.sleep_ms(2000)
#                         lcd.clear()
#                         led_order(0, 'off')
#                         utime.sleep_ms(2000)
#                     else:   
#                         add_Nutzer(cardID)
#                         led_order(0, 'red')
#                         error()
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Nutzer unbekannt")
#                         utime.sleep_ms(2000)
#                         lcd.clear()
#                         lcd.move_to(0,0)
#                         lcd.putstr("Neuer Nutzer")
#                         lcd.move_to(0,1)
#                         lcd.putstr('hinzugef\xF5gt')
#                         utime.sleep_ms(2000)
#                         lcd.clear()
#                         led_order(0, 'off')
#                         utime.sleep_ms(2000)
#                 else:
#                     lcd.clear()
#                     lcd.move_to(0,0)
#                     lcd.putstr("ID:")
#                     lcd.move_to(4,0)
#                     lcd.putstr(get_Nutzer(cardID))
#                     lcd.move_to(0,1)
#                     lcd.putstr("Anzahl: ")
#                     lcd.move_to(8,1)
#                     lcd.putstr(add_Nutzer_Coffee(cardID))
#                     buzzer()
#                     led_order(0, 'green')
#                     utime.sleep_ms(1000)
#                     led_order(0, 'off')
#                     utime.sleep_ms(2000)
#                     lcd.clear()
#                 print("Bring TAG closer...")
#                 print("")
#                 await uasyncio.sleep_ms(10)

async def dummy_task():
    '''Heartbeat task'''
    while True:
        print("Heartbeat Task @", time())
        await uasyncio.sleep_ms(1000)

######## Boot & Initialisierung

stdout.write("Starte Hotspot...\n")
wap_create()
stdout.write("Hotspot gestartet.\n")

buzzer()
# lcd.clear()
# lcd.move_to(4,0)
# lcd.putstr("Herzlich")
# lcd.move_to(3,1)
# lcd.putstr("Willkommen")
# for i in range(4):
#     led_order(i, 'red')
#     sleep_ms(250)
# for i in range(4):
#     led_order(i, 'blue')
#     sleep_ms(250)
# lcd.clear()
# lcd.move_to(6,0)
# lcd.putstr("zum")
# lcd.move_to(1,1)
# lcd.putstr("Kaffee-Counter")
# for i in range(4):
#     led_order(i, 'green')
#     sleep_ms(250)
# for i in range(4):
#     led_order(i, 'yellow')
#     sleep_ms(250)
# for i in range(4):
#     led_order(i, 'off')
# lcd.clear()

######## Programm

TaskQueue = [
        dummy_task(),
        webserver.run_webserver()
        #Uhr(), Karte()
    ]

EVENT_LOOP = uasyncio.get_event_loop()
for task in TaskQueue:
    EVENT_LOOP.create_task(task)
EVENT_LOOP.run_forever()
