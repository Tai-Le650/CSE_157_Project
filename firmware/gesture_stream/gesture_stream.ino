// XIAO MG24 Sense: stream six-axis IMU data over USB serial.
// Sensor output data rate: 104 Hz. Polling: about 100 reads/second.
// Protocol: t_us,ax,ay,az,gx,gy,gz
// Acceleration units: g; gyroscope units: degrees/second.

#include <LSM6DS3.h>
#include <Wire.h>

LSM6DS3 imu(I2C_MODE, 0x6A);
const unsigned long SAMPLE_INTERVAL_US = 10000UL; // 100 Hz host read cadence
unsigned long lastSampleUs = 0;

void setup() {
  Serial.begin(115200);

  // Turn on the onboard IMU supply on the XIAO MG24 Sense.
  pinMode(PD5, OUTPUT);
  digitalWrite(PD5, HIGH);
  delay(300);

  // Configure BEFORE imu.begin().
  imu.settings.accelSampleRate = 104;
  imu.settings.gyroSampleRate = 104;
  imu.settings.accelRange = 16;
  imu.settings.gyroRange = 2000;

  if (imu.begin() != 0) {
    Serial.println("ERROR: IMU initialization failed");
    while (true) {
      delay(1000);
    }
  }

  Serial.println("t_us,ax,ay,az,gx,gy,gz");
  lastSampleUs = micros();
}

void loop() {
  unsigned long now = micros();
  if ((unsigned long)(now - lastSampleUs) < SAMPLE_INTERVAL_US) {
    return;
  }
  lastSampleUs = now;

  // Keep each record on one complete newline-terminated CSV line.
  Serial.print(now);
  Serial.print(',');
  Serial.print(imu.readFloatAccelX(), 3);
  Serial.print(',');
  Serial.print(imu.readFloatAccelY(), 3);
  Serial.print(',');
  Serial.print(imu.readFloatAccelZ(), 3);
  Serial.print(',');
  Serial.print(imu.readFloatGyroX(), 3);
  Serial.print(',');
  Serial.print(imu.readFloatGyroY(), 3);
  Serial.print(',');
  Serial.println(imu.readFloatGyroZ(), 3);
}
