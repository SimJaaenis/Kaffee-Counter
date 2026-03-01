import time


class LcdApi:
    LCD_CLR = 0x01
    LCD_HOME = 0x02

    LCD_ENTRY_MODE = 0x04
    LCD_ENTRY_INC = 0x02

    LCD_ON_CTRL = 0x08
    LCD_ON_DISPLAY = 0x04

    LCD_FUNCTION = 0x20
    LCD_FUNCTION_2LINES = 0x08
    LCD_FUNCTION_RESET = 0x30

    LCD_DDRAM = 0x80

    def __init__(self, num_lines, num_columns):
        self.num_lines = min(num_lines, 4)
        self.num_columns = min(num_columns, 40)
        self.cursor_x = 0
        self.cursor_y = 0
        self.backlight = True

        self.display_off()
        self.backlight_on()
        self.clear()
        self.hal_write_command(self.LCD_ENTRY_MODE | self.LCD_ENTRY_INC)
        self.display_on()

    def clear(self):
        self.hal_write_command(self.LCD_CLR)
        self.hal_write_command(self.LCD_HOME)
        self.cursor_x = 0
        self.cursor_y = 0

    def display_on(self):
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY)

    def display_off(self):
        self.hal_write_command(self.LCD_ON_CTRL)

    def backlight_on(self):
        self.backlight = True
        self.hal_backlight_on()

    def backlight_off(self):
        self.backlight = False
        self.hal_backlight_off()

    def move_to(self, cursor_x, cursor_y):
        self.cursor_x = cursor_x
        self.cursor_y = cursor_y
        addr = cursor_x & 0x3F
        if cursor_y & 1:
            addr += 0x40
        if cursor_y & 2:
            addr += self.num_columns
        self.hal_write_command(self.LCD_DDRAM | addr)

    def putchar(self, char):
        if char == "\n":
            self.cursor_x = self.num_columns
        else:
            self.hal_write_data(ord(char))
            self.cursor_x += 1

        if self.cursor_x >= self.num_columns:
            self.cursor_x = 0
            self.cursor_y += 1

        if self.cursor_y >= self.num_lines:
            self.cursor_y = 0

        self.move_to(self.cursor_x, self.cursor_y)

    def putstr(self, string):
        for char in string:
            self.putchar(char)

    def hal_backlight_on(self):
        pass

    def hal_backlight_off(self):
        pass

    def hal_write_command(self, cmd):
        raise NotImplementedError

    def hal_write_data(self, data):
        raise NotImplementedError


MASK_RS = 0x01
MASK_E = 0x04
SHIFT_BACKLIGHT = 3
SHIFT_DATA = 4


class I2cLcd20x4(LcdApi):
    def __init__(self, i2c, i2c_addr=0x27, num_lines=4, num_columns=20):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.i2c.writeto(self.i2c_addr, bytes([0]))
        time.sleep_ms(20)

        self._write_init_nibble(self.LCD_FUNCTION_RESET)
        time.sleep_ms(5)
        self._write_init_nibble(self.LCD_FUNCTION_RESET)
        time.sleep_ms(1)
        self._write_init_nibble(self.LCD_FUNCTION_RESET)
        time.sleep_ms(1)
        self._write_init_nibble(self.LCD_FUNCTION)
        time.sleep_ms(1)

        super().__init__(num_lines, num_columns)
        cmd = self.LCD_FUNCTION
        if num_lines > 1:
            cmd |= self.LCD_FUNCTION_2LINES
        self.hal_write_command(cmd)

    def _write_init_nibble(self, nibble):
        byte = ((nibble >> 4) & 0x0F) << SHIFT_DATA
        self.i2c.writeto(self.i2c_addr, bytes([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([byte]))

    def hal_backlight_on(self):
        self.i2c.writeto(self.i2c_addr, bytes([1 << SHIFT_BACKLIGHT]))

    def hal_backlight_off(self):
        self.i2c.writeto(self.i2c_addr, bytes([0]))

    def hal_write_command(self, cmd):
        high = (self.backlight << SHIFT_BACKLIGHT) | (((cmd >> 4) & 0x0F) << SHIFT_DATA)
        low = (self.backlight << SHIFT_BACKLIGHT) | ((cmd & 0x0F) << SHIFT_DATA)

        self.i2c.writeto(self.i2c_addr, bytes([high | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([high]))
        self.i2c.writeto(self.i2c_addr, bytes([low | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([low]))

        if cmd <= 3:
            time.sleep_ms(5)

    def hal_write_data(self, data):
        high = MASK_RS | (self.backlight << SHIFT_BACKLIGHT) | (((data >> 4) & 0x0F) << SHIFT_DATA)
        low = MASK_RS | (self.backlight << SHIFT_BACKLIGHT) | ((data & 0x0F) << SHIFT_DATA)

        self.i2c.writeto(self.i2c_addr, bytes([high | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([high]))
        self.i2c.writeto(self.i2c_addr, bytes([low | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([low]))

    def write_lines(self, lines):
        self.clear()
        max_lines = min(4, len(lines))
        for row in range(max_lines):
            self.move_to(0, row)
            text = lines[row]
            if len(text) < 20:
                text = text + (" " * (20 - len(text)))
            else:
                text = text[:20]
            self.putstr(text)

