from machine import I2C, Pin
from urtc import DS1307
import utime
from pico_i2c_lcd import I2cLcd
from mfrc522 import MFRC522
from buzzer_api import *
from machine import Pin
from time import sleep_ms
from neopixel_api import *
from nutzer_api import *

######## Definitionen

#### Uhr
i2c_lcd = machine.I2C(1,scl=Pin(15),sda=Pin(14),freq=400000)

lcd = I2cLcd(i2c_lcd, 0x27, 2, 16)

i2c_rtc = machine.I2C(0,scl = Pin(17),sda = Pin(16),freq = 400000)
result = I2C.scan(i2c_rtc)
rtc = DS1307(i2c_rtc)

def Uhr():
    while True:
        (year,month,date,day,hour,minute,second,p1)=rtc.datetime()
        # lcd.clear()
        lcd.move_to(0,0)
        lcd.putstr(" Zeit:")
        lcd.move_to(7,0)
        lcd.putstr(str("%02d"%hour) + ":" + str("%02d"%minute) + ":" + str("%02d"%second))
        lcd.move_to(0,1)
        lcd.putstr("Datum:")
        lcd.move_to(7,1)
        lcd.putstr(str("%02d"%date) + "." + str("%02d"%month) + "." + str("%02d"%year)[2:])
        utime.sleep(0.01)
        yield None

#### Karte
reader = MFRC522(spi_id=0,sck=6,miso=4,mosi=7,cs=5,rst=22)
 
print("Bring TAG closer...")
print("")
def Karte():
    while True:
        global reader
        reader.init()
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, uid) = reader.SelectTagSN()
            if stat == reader.OK:
                cardID = int.from_bytes(bytes(uid),"little",False)
                print(str(cardID))
                userID = nutzer.get(cardID)
                if userID == None:
                    if cardID == 629409519:
                        ###### Gold Tag
                        buzzer()
                        lcd.clear()
                        lcd.move_to(0,0)
                        lcd.putstr("GOLD TAG Erkannt")
                        sleep_ms(1000)
                        lcd.clear()
                        lcd.move_to(0,0)
                        lcd.putstr("Warten auf Tag:")
                        buzzer()
                        print("1 hier bin ich")
                        neuerTagGelesen = False
                        while neuerTagGelesen == False:
                            reader.init()
                            (stat2, tag_type2) = reader.request(reader.REQIDL)
                            if stat2 == reader.OK:
                                print("2 hier bin ich")
                                (stat2, uid2) = reader.SelectTagSN()
                                if stat2 == reader.OK:
                                    print("3 hier bin ich")
                                    cardIDtoReset = int.from_bytes(bytes(uid2),"little",False)
                                    neuerTagGelesen = True
                                    lcd.clear()
                                    lcd.move_to(0,0)
                                    print("3b ier bin ich " + str(cardIDtoReset))
                                    if nutzer.get(cardIDtoReset) == None:
                                        print("4 hier bin ich")
                                        print(nutzer.get(int(cardIDtoReset)))
                                        lcd.putstr("Nutzer unbekannt")
                                        led_order(0, 'red')
                                        error()
                                        led_order(0, 'off')
                                        error()
                                        led_order(0, 'red')
                                        error()
                                        led_order(0, 'off')
                                        lcd.clear()
                                    else:
                                        print("5 hier bin ich")
                                        lcd.putstr("ID:")
                                        lcd.move_to(4,0)
                                        lcd.putstr(nutzer[cardIDtoReset][0])
                                        lcd.move_to(0,1)
                                        lcd.putstr("Anzahl: ")
                                        lcd.move_to(7,1)
                                        lcd.putstr(reset_Nutzer(cardIDtoReset))
                                        led_order(0, 'green')
                                        buzzer()
                                        led_order(0, 'off')
                                        buzzer()
                                        led_order(0, 'green')
                                        buzzer()
                                        led_order(0, 'off')
                                        utime.sleep_ms(10000)
                                        lcd.clear()
                            sleep_ms(50)
                    elif cardID == 1982696638:
                        ###### Demo Tag ohne User hinzuzufügen
                        led_order(0, 'red')
                        error()
                        utime.sleep_ms(1000)
                        led_order(0, 'off')
                        utime.sleep_ms(2000)
                    else:   
                        add_Nutzer(cardID)
                        led_order(0, 'red')
                        error()
                        lcd.clear()
                        lcd.move_to(0,0)
                        lcd.putstr("Nutzer unbekannt")
                        utime.sleep_ms(1000)
                        lcd.clear()
                        lcd.move_to(0,0)
                        lcd.putstr("Nutzer hinzu-")
                        lcd.move_to(0,1)
                        lcd.putstr(gefügt)
                        utime.sleep_ms(1000)
                        led_order(0, 'off')
                        utime.sleep_ms(2000)
                else:
                    print(nutzer[cardID][0])
                    lcd.clear()
                    lcd.move_to(0,0)
                    lcd.putstr("ID:")
                    lcd.move_to(4,0)
                    lcd.putstr(nutzer[cardID][0])
                    lcd.move_to(0,1)
                    lcd.putstr("Anzahl: ")
                    lcd.move_to(7,1)
                    lcd.putstr(add_Nutzer_Coffee(cardID))
                    ######
                    led_order(0, 'green')
                    buzzer()
                    utime.sleep_ms(1000)
                    led_order(0, 'off')
                    utime.sleep_ms(2000)
                    lcd.clear()
                print("Bring TAG closer...")
                print("")
        yield None

######## Boot & Initialisierung

buzzer()
lcd.clear()
lcd.move_to(4,0)
lcd.putstr("Herzlich")
lcd.move_to(3,1)
lcd.putstr("Willkommen")
for i in range(4):
    led_order(i, 'red')
    sleep_ms(250)
for i in range(4):
    led_order(i, 'blue')
    sleep_ms(250)
lcd.clear()
lcd.move_to(6,0)
lcd.putstr("zum")
lcd.move_to(1,1)
lcd.putstr("Kaffee-Counter")
for i in range(4):
    led_order(i, 'green')
    sleep_ms(250)
for i in range(4):
    led_order(i, 'yellow')
    sleep_ms(250)
for i in range(4):
    led_order(i, 'off')
lcd.clear()



######## Programm

TaskQueue = [ Uhr(), Karte() ]

while True:
    # main loop here
    for task in TaskQueue:
        next(task)