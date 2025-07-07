import network
import time
from machine import Pin, ADC, I2C
import blynklib
import dht
import ssd1306
import urequests

# Wi-Fi Credentials
SSID = "A"
PASSWORD = "012345678"

# Blynk Auth Token
BLYNK_AUTH = "kZLhV_a1b3qt2C4HZpnD9Y9TGd0I1SMs"

# Google Sheets Web App URL
GOOGLE_SHEET_URL = "https://script.google.com/macros/s/AKfycbwQZcQOb1-MDgGXn_SoeZ8mkdb7TRoGtIIPzXFl5MqEj8WdLKoY9I2o_M0Vj0fB1ek/exec"

i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

def display_oled(temp, humidity, moisture, pump_status):
    try:
        oled.fill(0)
        oled.text(f"Temp: {temp:.1f}C", 0, 16)
        oled.text(f"Humidity: {humidity:.1f}%", 0, 28)
        oled.text(f"Soil: {moisture:.1f}%", 0, 40)
        oled.text(f"Pump: {pump_status}", 0, 52)
        oled.show()
    except Exception as e:
        print("❌ OLED Display Error:", e)

# Connect to Wi-Fi
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(SSID, PASSWORD)
        timeout = 10
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
        if wlan.isconnected():
            print("Connected! IP:", wlan.ifconfig()[0])
            return wlan
        else:
            print("Wi-Fi failed. Retrying in 5 seconds...")
            time.sleep(5)
            return connect_wifi()

wlan = connect_wifi()

# Initialize Blynk
blynk = blynklib.Blynk(BLYNK_AUTH, insecure=True)

# Setup Components
led = Pin("LED", Pin.OUT)
dht_pin = Pin(16, Pin.IN, Pin.PULL_UP)
sensor = dht.DHT22(dht_pin)
adc = ADC(26)
relay = Pin(15, Pin.OUT)

# Moisture Thresholds
DRY_THRESHOLD = 30
WET_THRESHOLD = 90

# Watering Settings
scheduled_hour = 6
scheduled_minute = 30
watering_duration = 5
auto_watering_enabled = False

# State Variables
pump_on = False
manual_control = False
watering_start_time = None
last_temp = 0.0
last_humidity = 0.0

# Blynk Handlers
@blynk.on("V0")
def v0_handler(value):
    global pump_on, manual_control
    if int(value[0]) == 1:
        relay.value(1)
        pump_on = True
        manual_control = True
        print("Pump ON (Manual)")
        blynk.log_event("pump_on", "Pump ON (Manual)")
    else:
        relay.value(0)
        pump_on = False
        manual_control = True
        print("Pump OFF (Manual)")
        blynk.log_event("pump_off", "Pump OFF (Manual)")

@blynk.on("V10")
def v10_handler(value):
    global auto_watering_enabled
    auto_watering_enabled = int(value[0]) == 1
    if auto_watering_enabled:
        print("✅ Auto-Watering Enabled")
    else:
        print("❌ Auto-Watering Disabled")

@blynk.on("V7")
def v7_handler(value):
    global scheduled_hour
    scheduled_hour = int(value[0])
    print(f"⏰ Scheduled Hour Set to {scheduled_hour}")

@blynk.on("V8")
def v8_handler(value):
    global scheduled_minute
    scheduled_minute = int(value[0])
    print(f"⏰ Scheduled Minute Set to {scheduled_minute}")

@blynk.on("V9")
def v9_handler(value):
    global watering_duration
    watering_duration = int(value[0])
    print(f"💧 Watering Duration Set to {watering_duration} minutes")

# 🔹 Function to Read DHT22 Sensor with Error Handling
def read_dht22():
    global last_temp, last_humidity
    try:
        sensor.measure()
        last_temp = sensor.temperature()
        last_humidity = sensor.humidity()
        print(f"Temp: {last_temp:.1f}°C, Humidity: {last_humidity:.1f}%")
        blynk.virtual_write(4, last_temp)
        blynk.virtual_write(5, last_humidity)
    except OSError as e:
        print("❌ DHT22 Read Error:", e)
        print("⚠️ Using last known values.")
    return last_temp, last_humidity

# 🔹 Function to Read Moisture Sensor and Auto-Control Pump
def read_moisture():
    global pump_on, manual_control
    try:
        moisture_value = adc.read_u16()
        moisture_percentage = (65535 - moisture_value) / 655.35
        print(f"Soil Moisture: {moisture_percentage:.2f}%")
        blynk.virtual_write(6, moisture_percentage)

        if not manual_control and watering_start_time is None:
            if moisture_percentage < DRY_THRESHOLD and not pump_on:
                relay.value(1)
                pump_on = True
                print("💧 Soil is too dry! Pump ON.")
                blynk.log_event("low_moisture", "🚨 Soil is too dry! Pump Started")
                blynk.virtual_write(0, 1)
            elif moisture_percentage > WET_THRESHOLD and pump_on:
                relay.value(0)
                pump_on = False
                print("✅ Soil is wet. Pump OFF.")
                blynk.virtual_write(0, 0)
        return moisture_percentage
    except Exception as e:
        print("❌ Moisture Sensor Error:", e)
        return 0.0

# 🔹 Check and Execute Scheduled Watering
def check_scheduled_watering():
    global pump_on, watering_start_time
    try:
        current_time = time.localtime()
        current_hour = current_time[3]
        current_minute = current_time[4]
        if auto_watering_enabled and watering_start_time is None:
            if current_hour == scheduled_hour and current_minute == scheduled_minute:
                print(f"⏰ Scheduled Watering Started at {scheduled_hour}:{scheduled_minute}")
                blynk.log_event("schedule_start", f"⏰ Watering started at {scheduled_hour}:{scheduled_minute}")
                relay.value(1)
                pump_on = True
                blynk.virtual_write(0, 1)
                watering_start_time = time.time()
        if watering_start_time:
            elapsed_time = time.time() - watering_start_time
            if elapsed_time >= (watering_duration * 60):
                relay.value(0)
                pump_on = False
                blynk.virtual_write(0, 0)
                print("✅ Scheduled Watering Completed")
                blynk.log_event("schedule_done", "✅ Watering completed")
                watering_start_time = None
    except Exception as e:
        print("❌ Error in Scheduled Watering:", e)

# 🔹 Send Data to Google Sheets
def send_to_google(temp, humidity, moisture):
    url = f"{GOOGLE_SHEET_URL}?temp={temp:.1f}&humidity={humidity:.1f}&moisture={moisture:.2f}"
    try:
        response = urequests.get(url)
        print("✅ Data Sent to Google Sheets:", response.text)
    except Exception as e:
        print("❌ Error Sending Data:", e)

last_update_time = time.ticks_ms()

# 🔹 Main Loop with Error Handling
try:
    while True:
        try:
            blynk.run()
            check_scheduled_watering()

            if time.ticks_diff(time.ticks_ms(), last_update_time) > 5000:
                temp, humidity = read_dht22()
                moisture = read_moisture()
                pump_status = "ON" if pump_on else "OFF"
                display_oled(temp, humidity, moisture, pump_status)
                send_to_google(temp, humidity, moisture)
                last_update_time = time.ticks_ms()

        except Exception as loop_error:
            print("⚠️ Unexpected error in main loop:", loop_error)
            time.sleep(1)

except KeyboardInterrupt:
    relay.value(0)
    print("Pump is OFF. Exiting.")
