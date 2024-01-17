from machine import Pin, PWM
from time import sleep, sleep_ms

pwm = PWM(Pin(13))
pwm.duty_u16(32268)
pause = 100

def buzzer():
    pwm.freq(493)
    sleep_ms(pause)
    pwm.freq(440)
    sleep_ms(pause)
    pwm.freq(415)
    sleep_ms(pause*2)
    pwm.freq(659)
    sleep_ms(pause)
    pwm.deinit()

def error():
    pwm.freq(659)
    sleep_ms(pause*3)
    pwm.freq(415)
    sleep_ms(pause*5)
    pwm.deinit()


