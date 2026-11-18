# Bruce Firmware — CYD-2432S028 & CYD-2432S024R (90° CW Touch, 2.4" 320×240)

Полная копия и клон прошивки **Bruce (Release 1.17)** для плат **ESP32-2432S028R / ESP32-2432S024R (Cheap Yellow Display 2.4" / 2.8", прямоугольный экран 320×240)** с поворотом ориентации тачскрина на **90° по часовой стрелке** и пересчётом прямоугольного соотношения сторон `320×240`, выполненные и верифицированные с помощью **[morluto/rea](https://github.com/morluto/rea)** (`rea-agents` v6.9.0).

---

## Готовые бинарные образы (`firmware/`)

| Файл | Описание | SHA-256 |
|---|---|---|
| **[`firmware/Bruce-CYD-2432S024R-90CW.bin`](firmware/Bruce-CYD-2432S024R-90CW.bin)** | Клонированная прошивка с поворотом тачскрина на **90° по часовой стрелке** и масштабированием под прямоугольный экран **2.4" (320×240)** | `872922cd0593a1a050c5d91f9efd08897427d2a69f7cf10ac2c3420c7ac64864` |
| **[`firmware/Bruce-CYD-2432S028.bin`](firmware/Bruce-CYD-2432S028.bin)** | Основной образ (обновлён до версии с поворотом тачскрина на **90° по часовой стрелке** для 2.4" 320×240) | `872922cd0593a1a050c5d91f9efd08897427d2a69f7cf10ac2c3420c7ac64864` |
| **[`firmware/Bruce-CYD-2432S028-orig.bin`](firmware/Bruce-CYD-2432S028-orig.bin)** | Оригинальный (немодифицированный) образ `CYD-2432S028` Release 1.17 | `f127d4bbe4a4c1954c9dad975365bf6fa0ed8cab82471b641b0af0b4c1b9b587` |

---

## Математическая модель поворота тачскрина на 90° по часовой стрелке (прямоугольный экран 2.4" 320×240)

При простом обмене осей `SwapXY` на прямоугольном экране `320×240` координата $X$ оказывается ограниченной диапазоном `[0..240]` (правые 80 пикселей экрана недоступны), а координата $Y$ выходит за пределы `[0..240]` до `320`.

Для точного поворота на **90° по часовой стрелке** (`90° CW`) на прямоугольной матрице `320×240`:
1. **Нормализованное преобразование координат (`90° CW`)**:
   $$(u_{\text{new}}, v_{\text{new}}) = (1 - v_{\text{orig}}, \; u_{\text{orig}})$$
   Матрица флагов в [`touchCfg()`](boards/CYD-2432S024R-90CW/interface.cpp) для всех 4 ориентаций дисплея (`r = 0, 1, 2, 3`):
   - `SwapXY[4]  = {false, true, false, true}` (было `{true, false, true, false}`)
   - `MirrorX[4] = {true, true, false, false}` (было `{true, false, false, true}`)
   - `MirrorY[4] = {true, false, false, true}` (было `{false, false, true, true}`)
2. **Учёт прямоугольного соотношения сторон `320×240` (4:3)**:
   - В экземпляре [`CYD28_TouchR touch`](src/hal/inputs/touch.cpp) (сегмент `.dram0.data`, адрес `0x3FFBDFD0`) базовые диапазоны масштабирования АЦП `XPT2046` до обмена осей изменены на `sizeX_px = 240` (`+0x20`) и `sizeY_px = 320` (`+0x24`).
   - В [`hal_touch_read()`](src/hal/inputs/touch.cpp) добавлено пропорциональное масштабирование осей после `SwapXY[r]` (`x = x * screenW / maxX`, `y = y * screenH / maxY`), благодаря чему при альбомной ориентации (`320×240`) ось $X$ покрывает все `0..320` пикселей, а ось $Y$ — все `0..240` пикселей.

---

## Быстрая прошивка готового бинарника (`esptool.py`)

```bash
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 921600 \
  --before default_reset --after hard_reset write_flash -z \
  --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x0 firmware/Bruce-CYD-2432S024R-90CW.bin
```

> Примечание: если на плате в NVS (`0x9000`) сохранена старая калибровка, полная запись образа с адреса `0x0` автоматически очистит раздел `nvs` (`0x9000`), либо вы можете запустить повторную калибровку в меню **Config → Calibrate Touch**.

---

## Сборка из исходного кода (PlatformIO)

```bash
# Сборка клонированного профиля CYD-2432S024R-90CW (2.4" 320x240, тачскрин 90° CW)
pio run -e CYD-2432S024R-90CW

# Сборка профиля CYD-2432S028 (также включает флаг TOUCH_ROTATE_90_CW=1)
pio run -e CYD-2432S028
```

---

## Повторное применение бинарного патча и проверка через `morluto/rea`

```bash
# Применение бинарного патча 90° CW (Segment 1 @ 0x3FFBDFD0 + Segment 2 @ 0x401385C0)
python3 rea_analysis/scripts/patch_touch_90cw.py

# Проверка целостности контрольной суммы XOR и SHA-256 через REA
npx -y rea-agents@latest inspect-artifact rea_analysis/partitions/factory-90cw.bin --json
```
