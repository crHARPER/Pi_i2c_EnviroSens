## Pi_i2c_EnviroSens
Python I2C Multiple Environmental Sensor Management for Raspberry Pi

chris@crHARPER.com
DEC 23, 2018

The purpose of this project is to allow basically any version of the Raspberry Pi to gather data from a number of i2c environmental sensors and to make that data available for other processes running asynchronously on the Pi for data logging and/or data transfer via MQTT or other preferred method.

In order for this system to operate reliably, the /tmp directory is configured to operate from RAM. This keeps writes to the SD card to a minimum.  Ideally, if local logging is required it should be done to a separate USB thumb drive and not the SD card.  Keep in mind that one of the objectives is to insure that such an IOT device needs to operate reliably for many years.

To get the /tmp directory to operate in RAM, add the following line to the /etc/fstab file:

	tmpfs /tmp tmpfs defaults,noatime,nosuid,size=100M 0 0   

When i2c sensors are initialized they are added to the RAM file system in /tmp.

i2s sensors included/supported are:
1) HTU21D Temperature Humidity sensor
2) SGP30 VOC Sensor
3) CCS811 VOC Sensor
4) BME860 VOC Pressure Temperature Humidity Sensor

The CCS811 grabs Temperature & Humidity values from the HTU21D via the file system.
The SGP30 grabs the Absolute Humidity value from the HTU21D via the file system as well.
The BME680 does its own thing and most of the 'nuts and bolts' code was pulled from previously published example code but is placed in a consistent object orientated format that outputs its data to the file system.  Unfortunately, I'm not sure who originally authored that code.   

Sensor data is maintained typically in one minute moving averages, updated three times per minute (every 20 seconds).  It is up to the data collection process to pull the data once a minute and to watch for stale data files (via file time stamps) in the event the i2c process were to crash.  I have found that occasionally, as in after a few months, the i2c sensor background process may through an error and exit.  Since it is challenging to find theses rare faults, it was easier to add an additional watchdog process that automatically restarts the i2c sensor background process if it gets dropped.  A similar watchdog process may also be needed to maintain a constant WiFI connection.      

adaFruit has made mention that the CCS811 is not comparable with the Raspberry Pi's i2c hardware but I have been getting reliable operation by slowing down the Pi's i2c baud rate.  To do this, the following lines needs to be added to the end of the /boot/config.txt file:

	dtoverlay=i2c-bcm2708
	dtparam=i2c1_baudrate=20000     








