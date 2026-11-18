# Bruce Firmware — CYD-2432S028 Edition (REA Reverse-Engineered & Reconstructed)

Полная копия и исходное дерево прошивки **Bruce (Release 1.17)** для платы **ESP32-2432S028R (Cheap Yellow Display / CYD 2.8")**, полученная и верифицированная с помощью инструмента реверс-инжиниринга **[morluto/rea](https://github.com/morluto/rea)** (`rea-agents` v6.9.0).

---

## Состав репозитория

1. **[`firmware/Bruce-CYD-2432S028.bin`](firmware/Bruce-CYD-2432S028.bin)** — готовый к прошивке полный 4 МБ бинарный образ для `CYD-2432S028` (проверен побитово через `morluto/rea`, SHA-256: `f127d4bbe4a4c1954c9dad975365bf6fa0ed8cab82471b641b0af0b4c1b9b587`).
2. **[`rea_analysis/`](rea_analysis/)** — артефакты реверс-инжиниринга `morluto/rea`:
   - [`rea_analysis/REVERSE_ENGINEERING_REPORT.md`](rea_analysis/REVERSE_ENGINEERING_REPORT.md) — подробный технический отчёт (карта памяти, таблица разделов, 6 сегментов Xtensa, распиновка `CYD-2432S028`, сравнение Full vs Launcher).
   - [`rea_analysis/evidence/`](rea_analysis/evidence/) — JSON-доказательства (`Evidence`) от `rea inspect-artifact`, `rea compare-artifacts`, `rea inspect-binary-hardening` и `rea inspect-with-objdump`.
   - [`rea_analysis/extracted_webui/`](rea_analysis/extracted_webui/) — распакованные из сегмента DROM (`0x3F400020`) файлы встроенного веб-интерфейса (`index.html`, `index.js`, `index.css`, `login.html`).
   - [`rea_analysis/partitions/`](rea_analysis/partitions/) — извлечённые `bootloader.bin` (`0x1000`), `partition-table.bin` (`0x8000`) и `nvs.bin` (`0x9000`).
   - [`rea_analysis/scripts/rea_reverse_pipeline.py`](rea_analysis/scripts/rea_reverse_pipeline.py) — скрипт автоматической распаковки, генерации Xtensa ELF32, восстановления [`include/webFiles.h`](include/webFiles.h) и побитовой пересборки образа `Bruce-CYD-2432S028.bin`.
3. **Полный исходный код прошивки под `CYD-2432S028`**:
   - [`platformio.ini`](platformio.ini) — преднастроен на сборку окружения `CYD-2432S028` по умолчанию (также доступны `LAUNCHER_CYD-2432S028`, `CYD-2USB`, `CYD-2432W328C`, `CYD-2432W328R-or-S024R`, `CYD-3248S035R`, `CYD-3248S035C`).
   - [`boards/CYD-2432S028/`](boards/CYD-2432S028/) — аппаратная конфигурация пинов, SPI/I2C шин, дисплея `ILI9341_2` (HSPI) и резистивного тачскрина `XPT2046`.
   - [`src/`](src/) — ядро (`src/core/`), HAL (`src/hal/`) и все функциональные модули (`src/modules/`):
     - **Wi-Fi**: сканер, Beacon Spam, Deauther, Evil Portal (Captive Portal), PCAP Sniffer, SSH/Telnet, WireGuard, Wardriving, Host/Port Scan.
     - **BLE**: BLE Scanner, Analyzer, BadBLE / Media HID, BLE Spam (AppleJuice, SourApple, SwiftPair, Samsung, Android FastPair).
     - **Sub-GHz (RF)**: поддержка CC1101 и однопиновых приёмопередатчиков (Raw Rx/Tx, анализатор спектра, Jammer, воспроизведение `.sub` файлов).
     - **IR (Инфракрасный порт)**: TV-B-Gone, приём и передача протоколов NEC, Samsung, Sony, RC5, RC6, LG, Panasonic и Raw (`.ir`).
     - **RFID / NFC**: поддержка PN532 и MFRC522 (чтение/запись UID, Mifare Classic, SRIX, Amiibolink, ChameleonUltra).
     - **NRF24**: сканер спектра 2.4 ГГц, MouseJack, NRF24 Jammer.
     - **JavaScript (`bjs_interpreter`)**: встроенный движок `mquickjs` для выполнения скриптов `/BruceJS/`.
     - **WebUI и файловый менеджер**: управление SD-картой и LittleFS через браузер (`http://bruce.local` или `172.0.0.1`), потоковая трансляция экрана (`/getscreen`), веб-терминал (`/cm`) и OTA-обновление.
   - [`lib/`](lib/) — все необходимые локальные библиотеки (`DisplayDrivers`, `TFT_eSPI`, `CYD-touch`, `SensorLib`, `XPowersLib`, `ESP32_Button`, `RotaryEncoder`, `Adafruit-PN532`, `Adafruit-BusIO`, `Bad_Usb_Lib`, `BruceWifite`, `mquickjs_headers` и др.) уже включены в репозиторий.

---

## Быстрая прошивка готового бинарника (`Bruce-CYD-2432S028.bin`)

Для записи полного образа в плату **ESP32-2432S028R** с адреса `0x0`:

```bash
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 921600 \
  --before default_reset --after hard_reset write_flash -z \
  --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x0 firmware/Bruce-CYD-2432S028.bin
```

---

## Сборка из исходного кода (PlatformIO)

```bash
# Сборка полной версии для CYD-2432S028
pio run -e CYD-2432S028

# Сборка и прошивка по USB
pio run -e CYD-2432S028 -t upload

# Сборка облегчённой Launcher-версии (custom_4Mb.csv)
pio run -e LAUNCHER_CYD-2432S028
```

---

## Повторный анализ бинарника через `morluto/rea`

```bash
# Инспекция флеш-образа и таблицы разделов
npx -y rea-agents@latest inspect-artifact firmware/Bruce-CYD-2432S028.bin --json

# Извлечение разделов и сегментов + побитовая проверка пересборки
python3 rea_analysis/scripts/rea_reverse_pipeline.py
```
