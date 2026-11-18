# Технический отчёт: Реверс-инжиниринг и реконструкция прошивки Bruce `CYD-2432S028` через `morluto/rea`

Данный отчёт документирует результаты статического анализа, декомпозиции контейнеров ESP32, извлечения сегментов памяти, восстановления встроенного WebUI и побитовой реконструкции прошивки **`Bruce-CYD-2432S028.bin`** (Bruce Release 1.17 для платы **ESP32-2432S028R / Cheap Yellow Display**) с использованием инструментария **[morluto/rea](https://github.com/morluto/rea)** (`rea-agents` v6.9.0).

---

## 1. Конвейер анализа в `morluto/rea`

В ходе исследования были применены следующие инструменты `rea`:

1. **`rea inspect-artifact` (`esp-flash-image`)** — автоматическое распознавание полного флеш-дампа ESP32 (`Bruce-CYD-2432S028.bin`), верификация таблицы разделов (`0x8000`, запись `0x50AA` и контрольная сумма MD5 `0xEBEB`), декодирование заголовков `esp_image_header_t`, дескрипторов `esp_bootloader_desc_t` и `esp_app_desc_t`, проверка XOR-checksum (`0xEF` seed) и прикреплённых SHA-256 дайджестов.
   - Доказательная база: [`rea_analysis/evidence/inspect_flash.json`](evidence/inspect_flash.json)
2. **`rea extract-artifact` (`esp-flash-image` -> `esp-image`)** — двухступенчатая распаковка:
   - Извлечение разделов флеш-памяти: `bootloader.bin`, `partition-table.bin`, `partitions/nvs.bin`, `partitions/factory.bin`.
   - Извлечение 6 сегментов приложения из `partitions/factory.bin` (`segment-00.bin` .. `segment-05.bin`) и 3 сегментов загрузчика из `bootloader.bin`.
   - Доказательная база: [`rea_analysis/evidence/inspect_factory.json`](evidence/inspect_factory.json), [`rea_analysis/evidence/inspect_bootloader.json`](evidence/inspect_bootloader.json)
3. **`rea compare-artifacts`** — структурное сравнение полной прошивки (`Bruce-CYD-2432S028.bin`) и облегчённой сборки (`Bruce-LAUNCHER_CYD-2432S028.bin`).
   - Доказательная база: [`rea_analysis/evidence/compare_full_vs_launcher.json`](evidence/compare_full_vs_launcher.json)
4. **Реконструкция Xtensa ELF32 (`EM_XTENSA = 94`) + `rea inspect-with-objdump` & `rea inspect-binary-hardening`** — сборка заголовков `Elf32_Ehdr`, `Elf32_Phdr` и `Elf32_Shdr` по точным VMA/LMA адресам сегментов, полученных от `rea`, с последующей проверкой секций и флагов безопасности.
   - Доказательная база: [`rea_analysis/evidence/objdump_sections.json`](evidence/objdump_sections.json), [`rea_analysis/evidence/hardening_elf.json`](evidence/hardening_elf.json)
5. **Извлечение GZIP-ресурсов из DROM (`segment-00.bin`) + `rea analyze-javascript-application`** — поиск и распаковка 4 встроенных `PROGMEM` GZIP-потоков (`index.js`, `index.css`, `index.html`, `login.html`), построение семантического графа JS-приложения через REA и генерация C-заголовка [`include/webFiles.h`](../include/webFiles.h).

---

## 2. Карта флеш-памяти и разделов (`Bruce-CYD-2432S028.bin`)

- **Размер файла дампа**: `3 968 064` байт (`0x3C8C40`)
- **SHA-256 полного образа**: `f127d4bbe4a4c1954c9dad975365bf6fa0ed8cab82471b641b0af0b4c1b9b587`
- **Целевой МК**: `esp32` (архитектура `xtensa`, `chip_id = 0x0000`, `spi_mode = 2` DIO, `spi_speed = 0` 40 МГц, `spi_size = 2` 4 МБ)

| Регион / Раздел | Тип / Подтип | Flash-адрес | Размер в таблице | Записано в дампе | Статус / Дайджест |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Зарезервировано ROM | — | `0x000000` | `0x001000` (4 КБ) | `0xFF` (erased) | Описанный gap |
| `bootloader.bin` | Second-stage Bootloader | `0x001000` | `0x007000` (28 КБ) | `23 552` байт (`0x5C00`) | XOR `0x54` (valid), SHA-256 `e46334d6...` |
| `partition-table.bin` | Таблица разделов (`0x50AA`) | `0x008000` | `0x001000` (4 КБ) | `3` записи + MD5 | MD5 `20b4ac5bd2390899b65e17ab83231e5f` (valid) |
| `partitions/nvs.bin` | `data` / `nvs` (`0x01`/`0x02`) | `0x009000` | `0x006000` (24 КБ) | `0` байт (`0xFF`) | Чистый NVS-раздел |
| Выравнивание | — | `0x00F000` | `0x001000` (4 КБ) | `0xFF` (erased) | Описанный gap |
| `partitions/factory.bin` | `app` / `factory` (`0x00`/`0x00`) | `0x010000` | `0x3C0000` (3 932 160 Б) | `3 902 528` байт (`0x3B8C40`) | XOR `0xF7` (valid), SHA-256 `a83a07b5...` |
| `partitions/spiffs.bin` | `data` / `spiffs` (`0x01`/`0x82`) | `0x3D0000` | `0x030000` (196 608 Б) | Вне дампа (форматируется при старте LittleFS) | Монтируется как LittleFS `/littlefs` |

Соответствующая таблица разделов сохранена в [`custom_4Mb_full.csv`](../custom_4Mb_full.csv):
```csv
# Name,   Type, SubType, Offset,  Size, Flags
nvs,      data, nvs,     0x9000,  0x6000,
factory,  app,  factory, 0x10000, 0x3C0000,
spiffs,   data, spiffs,  0x3D0000,0x30000,
```

---

## 3. Дескриптор и сегменты основного приложения (`factory.bin`)

По данным `rea inspect-artifact` для `partitions/factory.bin`:
- **Точка входа (`entry_addr`)**: `0x40083050` (`1074278480`)
- **Дескриптор `esp_app_desc_t`** (смещение `0x20` внутри `factory.bin` / начало `segment-00.bin`):
  - `project_name`: `"arduino-lib-builder"`
  - `version`: `"idf-master-104-g43a8f6d-dirty"`
  - `idf_ver`: `"v5.5.4-dirty"`
  - `date` / `time`: `"Aug 26 2026"` / `"17:44:39"`
  - `mmu_page_size`: `16` ($2^{16} = 64\text{ KiB}$)
  - `app_elf_sha256`: `1893e68740054c6724dcfadf8eaafe83317d88c081447079d5cf714b3fca78df`
- **Контрольная сумма образа**: `0xF7` по смещению `3 902 495` (`status: valid`)
- **Прикреплённый SHA-256**: `a83a07b54aa96b5591a94de60887114ab050ce4c44e2fc63a3fc3697d256467d` (`status: valid`)

### Таблица сегментов `factory.bin`

| Индекс | Файл сегмента | Секция ELF | Адрес загрузки (`load_addr`) | Размер (`data_len`) | Смещение заголовка | Классификация REA | Назначение |
| :---: | :--- | :--- | :--- | ---: | ---: | :--- | :--- |
| `0` | `segment-00.bin` | `.flash.rodata` | `0x3F400020` | `831 140` Б | `0x000018` (`24`) | `mapped` (DROM) | Константы, строки UI, таблицы ИК/RF-кодов, встроенный GZIP WebUI |
| `1` | `segment-01.bin` | `.dram0.data` | `0x3FFBDB60` | `20 812` Б | `0x0CAEC4` (`831 172`) | `loaded` (DRAM) | Инициализированные глобальные переменные и таблицы дескрипторов |
| `2` | `segment-02.bin` | `.flash.text` | `0x400D0020` | `2 927 112` Б | `0x0D0018` (`851 992`) | `mapped` (IROM) | Основной исполняемый код Xtensa (Core, Wi-Fi, BLE, RF, IR, RFID, JS) |
| `3` | `segment-03.bin` | `.dram0.data2` | `0x3FFC2CAC` | `9 676` Б | `0x39AA28` (`3 779 112`) | `loaded` (DRAM) | Дополнительный сегмент данных DRAM |
| `4` | `segment-04.bin` | `.iram0.text` | `0x40080000` | `113 548` Б | `0x39CFFC` (`3 788 796`) | `loaded` (IRAM) | Векторы прерываний, критичный по времени код FreeRTOS, SPI/RMT/Wi-Fi HAL |
| `5` | `segment-05.bin` | `.rtc.data` | `0x50000200` | `132` Б | `0x3B8B90` (`3 902 352`) | `loaded` (RTC Slow) | Данные, сохраняемые в RTC-памяти при Deep Sleep |

---

## 4. Сравнение `Bruce-CYD-2432S028.bin` (Full) и `Bruce-LAUNCHER_CYD-2432S028.bin` (Lite) через `rea compare-artifacts`

Сравнение двух образов (`rea compare-artifacts`) выявило:
- **Неизменённые компоненты (`unchanged: 2`)**:
  - `bootloader.bin` (`0x1000`, SHA-256 `e46334d6...`)
  - `partitions/nvs.bin` (`0x9000`)
- **Изменённые компоненты (`changed: 4`)**:
  - `partition-table.bin`: в полной версии `factory` занимает `0x3C0000` (3.75 МБ), а `spiffs` — `0x30000` (192 КБ); в Launcher-версии (`custom_4Mb.csv`) `factory` уменьшен до `0x270000` (2 555 904 Б), а `spiffs` расширен до `0x180000` (1.5 МБ).
  - `partitions/factory.bin`: в Launcher-версии (`-DLITE_VERSION=1`) отключены `mquickjs` (интерпретатор JS), `LibSSH-ESP32`, `WireGuard-ESP32`, `ESP8266Audio`, `ESP8266SAM`, `ESP-Amiibolink`, `ESP-PN532BLE` и `ESP-PN532Killer`, за счёт чего размер `factory.bin` сокращён с `3 902 528` до `2 527 024` байт.

---

## 5. Извлечённый из DROM (`segment-00.bin`) встроенный WebUI

В сегменте `segment-00.bin` (базовый адрес `0x3F400020`) обнаружены и распакованы 4 потока GZIP (`1F 8B 08`), соответствующих массивам `PROGMEM` в `include/webFiles.h`:

| Переменная в `webFiles.h` | Смещение в `segment-00.bin` | Адрес в памяти (`VMA`) | Размер GZIP | Размер после распаковки | SHA-256 распакованного файла |
| :--- | :--- | :--- | ---: | ---: | :--- |
| `index_js` (`index.js`) | `0x00A80C` | `0x3F40A82C` | `8 434` Б | `28 307` Б | `a345180c7cc446d00194b9ef5f3263a15a698c185fa7a3ad403e7b669541906b` |
| `index_css` (`index.css`) | `0x00C8FE` | `0x3F40C91E` | `2 421` Б | `9 774` Б | `5ff9336a16e1bff97ac562ccfd834d3ae4bf1c2443b199a1dd859b3c4e54e4b2` |
| `index_html` (`index.html`) | `0x00D274` | `0x3F40D294` | `4 687` Б | `15 941` Б | `83b895e6febd63bd9b1a9b2e26c01585d255cec3170a2797c6eed13e6ccc1207` |
| `login_html` (`login.html`) | `0x00E4C3` | `0x3F40E4E3` | `601` Б | `1 222` Б | `214ab2097697d0a9704116093c252a6a1c523fa07bfe46c2a4251c72c49b7147` |

Распакованные файлы сохранены в [`rea_analysis/extracted_webui/`](extracted_webui/), а их точные GZIP-массивы записаны в [`include/webFiles.h`](../include/webFiles.h).

---

## 6. Аппаратная конфигурация и распиновка `CYD-2432S028`

Из анализа секций `.flash.rodata` / `.flash.text` и конфигурации [`boards/CYD-2432S028/`](../boards/CYD-2432S028/) восстановлена полная карта выводов платы **ESP32-2432S028R (Cheap Yellow Display)**:

| Подсистема | Интерфейс / Драйвер | Пины ESP32 | Примечание |
| :--- | :--- | :--- | :--- |
| **Дисплей TFT 2.8" (240x320)** | `ILI9341_2_DRIVER` (HSPI, 40 МГц) | `MISO=12`, `MOSI=13`, `SCLK=14`, `CS=15`, `DC=2`, `RST=-1`, `BL=21` | Ориентация `ROTATION=3` (альбомная 320x240), инверсия цвета синхронизируется при старте |
| **Тачскрин (резистивный)** | `XPT2046` (`TOUCH_CTRL_XPT2046`, 2.5 МГц) | `CS=33`, `IRQ=36`, разделяет шину SPI (`12/13/14`) или работает через `CYD28_TouchR` | Калибровка сохраняется в NVS (`touch_cal`) |
| **MicroSD-карта** | VSPI (`SDCARD_bus`) | `SCK=18`, `MISO=19`, `MOSI=23`, `CS=5` | Файловая система SD / exFAT, каталоги `/Bruce*` |
| **Внешняя шина SPI (`outer_bus`)** | VSPI Shared | `SCK=18`, `MISO=19`, `MOSI=23`, `CS=27` | Используется для внешних SPI-модулей (RC522, PN532, CC1101, NRF24, W5500) |
| **CC1101 (Sub-GHz)** | `SmartRC-CC1101` (`CC1101_bus`) | `SCK=18`, `MISO=19`, `MOSI=23`, `CS=27`, `GDO0=22`, `GDO2=NC` | Приём/передача `.sub`, анализатор спектра, Jammer |
| **NRF24L01 (2.4 ГГц)** | `RF24` (`NRF24_bus`) | `SCK=18`, `MISO=19`, `MOSI=23`, `CS=27`, `CE=22` | 2.4 ГГц спектр, MouseJack, Jammer |
| **I2C / Периферия CN1** | `Wire` (`i2c_bus`) | `SDA=27`, `SCL=22` | Внешние I2C-устройства (PN532, дисплеи, датчики) |
| **ИК-приёмопередатчик (IR)** | `IRremoteESP8266` | `IR_TX=22`, `IR_RX=27` (альт. `35`) | TV-B-Gone, NEC/Samsung/Sony/RC5/RC6/LG/Panasonic/Raw |
| **Однопиновый RF 433/315 МГц** | RMT / GPIO | `RF_TX=22` (или `27`), `RF_RX=27` (или `22`, `35`) | Настраивается в `/brucePins.conf` |
| **UART / GPS / BadUSB** | `HardwareSerial` | `UART/GPS RX=1, TX=3` (9600 бод); `BadUSB CH9329 RX=22, TX=27` | Wardriving, GPS NMEA, аппаратный BadUSB через CH9329 |
| **Питание / Deep Sleep** | EXT0 Wakeup | `GPIO 0` (кнопка BOOT) / `GPIO 36` | Пробуждение по низкому уровню (`LOW`) |

---

## 7. Воспроизведение анализа и побитовой пересборки

Для запуска конвейера реконструкции и проверки SHA-256 выполните:

```bash
python3 rea_analysis/scripts/rea_reverse_pipeline.py
```

Скрипт:
1. Декомпрессирует 4 GZIP-ресурса WebUI из `segment-00.bin` в `rea_analysis/extracted_webui/` и обновляет `include/webFiles.h`.
2. Собирает 32-битный Xtensa ELF (`Bruce-CYD-2432S028-reconstructed.elf`) из 6 сегментов.
3. Пересобирает `factory.bin` с вычислением XOR-checksum (`0xF7`) и SHA-256 (`a83a07b5...`), объединяет его с `bootloader.bin` (`0x1000`), `partition-table.bin` (`0x8000`) и `nvs.bin` (`0x9000`) в `firmware/Bruce-CYD-2432S028.bin` и проверяет точное совпадение SHA-256 (`f127d4bbe4a4c1954c9dad975365bf6fa0ed8cab82471b641b0af0b4c1b9b587`).
