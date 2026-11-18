#include "core/bus_HAL.h"
#include "core/powerSave.h"
#include "core/utils.h"
#include "hal/bright/bright.h"
#include <Arduino.h>
#include <interface.h>

#define GT911_SLAVE_ADDRESS_L 0x5D

#if defined(HAS_CAPACITIVE_TOUCH)
#include "hal/device.h"
#include "hal/inputs/touch.h"
static DeviceTouch touchCfg() {
    DeviceTouch cfg;
#if defined(TOUCH_CTRL_GT911)
    cfg.pin_sda = SYS_I2C_SDA;
    cfg.pin_scl = SYS_I2C_SCL;
    cfg.pin_rst = GT911_TOUCH_CONFIG_RST_GPIO_NUM;
    cfg.pin_irq = GT911_TOUCH_CONFIG_INT_GPIO_NUM;
#else
    cfg.pin_sda = CST816S_I2C_CONFIG_SDA_IO_NUM;
    cfg.pin_scl = CST816S_I2C_CONFIG_SCL_IO_NUM;
    cfg.pin_rst = CST816S_TOUCH_CONFIG_RST_GPIO_NUM;
    cfg.pin_irq = CST816S_TOUCH_CONFIG_INT_GPIO_NUM;
#endif
    // 90° clockwise rotated touch mapping for 2.4" rectangular (320x240) panel
    // rotation:        0      1      2      3
    const bool swapXY[4] = {true, false, true, false};
    const bool mirrorX[4] = {false, true, true, false};
    const bool mirrorY[4] = {true, true, false, false};
    for (int i = 0; i < 4; i++) {
        cfg.SwapXY[i] = swapXY[i];
        cfg.MirrorX[i] = mirrorX[i];
        cfg.MirrorY[i] = mirrorY[i];
    }
    return cfg;
}
#elif defined(TOUCH_CTRL_XPT2046)
#include "CYD28_TouchscreenR.h"
#include "hal/device.h"
#include "hal/inputs/touch.h"
extern CYD28_TouchR touch; // defined by hal/inputs/touch.cpp
#define XPT2046_CS CYD28_TouchR_CS
static DeviceTouch touchCfg() {
    DeviceTouch cfg;
    // 90° clockwise (по часовой стрелке) rotated XPT2046 touch mapping
    // for rectangular 2.4" (320x240) display:
    //   (u_new, v_new) = (1 - v_orig, u_orig)
    // Combined with CYD28_DISPLAY_HOR_RES_MAX=240, CYD28_DISPLAY_VER_RES_MAX=320
    // so the swapped axes span the full 320x240 rectangular screen without clipping.
    // rotation:        0      1      2      3
    const bool swapXY[4] = {false, true, false, true};
    const bool mirrorX[4] = {true, true, false, false};
    const bool mirrorY[4] = {true, false, false, true};
    for (int i = 0; i < 4; i++) {
        cfg.SwapXY[i] = swapXY[i];
        cfg.MirrorX[i] = mirrorX[i];
        cfg.MirrorY[i] = mirrorY[i];
    }
    return cfg;
}
#endif

/***************************************************************************************
** Function name: _setup_gpio()
** Location: main.cpp
** Description:   initial setup for the device
***************************************************************************************/
void _setup_gpio() {
    bruceConfigPins.outer_bus = {(gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)27};
    bruceConfigPins.PN532_bus = {(gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)27};
    bruceConfigPins.i2c_bus = {(gpio_num_t)27, (gpio_num_t)22}; // sda, scl

#if defined(SYS_I2C_SDA) && defined(SYS_I2C_SCL)
    bruceConfigPins.sys_i2c = {(gpio_num_t)SYS_I2C_SDA, (gpio_num_t)SYS_I2C_SCL}; // sda, scl
#endif

    bruceConfigPins.badusb_bus = {(gpio_num_t)22, (gpio_num_t)27}; // rx, tx (CH9329)
    bruceConfigPins.irTx = 22;
    bruceConfigPins.irRx = 27;
    bruceConfigPins.rfTx = 27;
    bruceConfigPins.rfRx = 22;
    bruceConfigPins.SDCARD_bus = {
        (gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)5
    }; // sck,miso,mosi,cs

    // CYD_base 2.4" rectangular (320x240) variant
    bruceConfigPins.rotation = 3;
    bruceConfigPins.uart_bus = {(gpio_num_t)1, (gpio_num_t)3}; // rx, tx
    bruceConfigPins.gps_bus = {(gpio_num_t)1, (gpio_num_t)3};  // rx, tx
    bruceConfigPins.CC1101_bus = {
        (gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)27, (gpio_num_t)22, GPIO_NUM_NC
    }; // sck,miso,mosi,cs,gdo0,gdo2
    bruceConfigPins.NRF24_bus = {
        (gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)27, (gpio_num_t)22
    }; // sck,miso,mosi,cs(ss),ce
#if !defined(LITE_VERSION)
    bruceConfigPins.W5500_bus = {
        (gpio_num_t)18, (gpio_num_t)19, (gpio_num_t)23, (gpio_num_t)27, (gpio_num_t)22, GPIO_NUM_NC
    }; // sck,miso,mosi,cs,int,rst
#endif

#ifndef HAS_CAPACITIVE_TOUCH
    pinMode(XPT2046_CS, OUTPUT);
    digitalWrite(XPT2046_CS, HIGH);
#endif

#if defined(HAS_CAPACITIVE_TOUCH)
    setSysI2CBus(&Wire1);
#if defined(TOUCH_CTRL_GT911)
    bruceConfigPins.sys_i2c.sda = (gpio_num_t)SYS_I2C_SDA;
    bruceConfigPins.sys_i2c.scl = (gpio_num_t)SYS_I2C_SCL;
#else
    bruceConfigPins.sys_i2c.sda = (gpio_num_t)CST816S_I2C_CONFIG_SDA_IO_NUM;
    bruceConfigPins.sys_i2c.scl = (gpio_num_t)CST816S_I2C_CONFIG_SCL_IO_NUM;
#endif
#endif

    bruceConfig.colorInverted = 0;
}

/***************************************************************************************
** Function name: _post_setup_gpio()
** Location: main.cpp
** Description:   second stage gpio setup to make a few functions work
***************************************************************************************/
void _post_setup_gpio() {
#if defined(TOUCH_CTRL_GT911)
    if (!hal_touch_init(touchCfg(), GT911_SLAVE_ADDRESS_L)) {
        Serial.println("Failed to find GT911 - check your wiring!");
    }
#endif
#if defined(TOUCH_CTRL_CST8XX)
    if (!hal_touch_init(touchCfg(), 0x15)) {
        Serial.println("Touch IC not Started");
        log_i("Touch IC not Started");
    } else log_i("Touch IC Started");
#endif
#if defined(TOUCH_CTRL_XPT2046)
    hal_touch_init(touchCfg(), 0, TFT_MOSI == CYD28_TouchR_MOSI);
#endif

    hal_bright_attach(TFT_BL);
    hal_bright_set(TFT_BL, 100);

#ifdef TFT_INVERSION_ON
    bruceConfig.colorInverted = 0;
    tft.invertDisplay(0);
#else
    bruceConfig.colorInverted = 1;
    tft.invertDisplay(1);
#endif

    bruceConfigPins.gpsBaudrate = 9600;

    bool pinsChanged = false;
    if (bruceConfigPins.rfTx != 22) {
        bruceConfigPins.rfTx = 22;
        pinsChanged = true;
    }
    if (bruceConfigPins.rfRx != 27) {
        bruceConfigPins.rfRx = 27;
        pinsChanged = true;
    }
    if (bruceConfigPins.irTx != 22) {
        bruceConfigPins.irTx = 22;
        pinsChanged = true;
    }
    if (bruceConfigPins.irRx != 27) {
        bruceConfigPins.irRx = 27;
        pinsChanged = true;
    }
    if (pinsChanged) bruceConfigPins.saveFile();
}

void _setBrightness(uint8_t brightval) { hal_bright_set(TFT_BL, brightval); }

void InputHandler(void) {
    static long d_tmp = 0;
    if (millis() - d_tmp > 200 || LongPress) {
        BruceTouchPoint t;
        if (hal_touch_read(touchCfg(), t)) {
            d_tmp = millis();
            hal_touch_apply(t);
        }
    }
}

void powerOff() {
    esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, LOW);
    esp_deep_sleep_start();
}

void checkReboot() {}
