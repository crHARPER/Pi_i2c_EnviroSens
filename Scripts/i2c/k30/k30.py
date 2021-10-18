#!/usr/bin/python
#
# chris@crHARPER.com
# JAN 29, 2018
#
# Revised:
# OCT 18, 2021
# 
# CO2 Meter's K30
# Raspberry Pi
#
#
#
import os
import time
from smbus2 import SMBus, i2c_msg

I2CBUS = 1

#------------------------------------------------------------------------------
# CO2 Meter K30 Sensor
#------------------------------------------------------------------------------

K30_ADDR = 0x68
K30_READ = 0x22
FILLER = 0x00
K30_READ_CO2 = 0x08

# build i2c message string
CO2_CHK_SUM = K30_READ + FILLER + K30_READ_CO2
CO2_CHK_SUM &= 0xff

K30_MSG =  [ K30_READ, FILLER, K30_READ_CO2, CO2_CHK_SUM ]
K30_RX_LEN = 4

CO2_MAX = 3


#------------------------------------------------------------------------------
# CO2 Meter K30 Sensor
#------------------------------------------------------------------------------
class K30:

    def __init__( self, name, i2c_addr ):
        self.I2Caddr = i2c_addr

        directory = "/tmp/" + name
        if not os.path.exists(directory):
            os.makedirs(directory)

        self.FptrCO2 = directory + "/co2"

        # init for 400ppm CO2
        self.co2_buff = [ 400 ] * CO2_MAX
        self.co2_ptr = 0


    #------------------------------------------------------------------------------
    # CO2 Meter K30 Sensor
    #------------------------------------------------------------------------------    
    # typically called evey 20 seconds for 1 minute moving average
    def task(self):

        co2_val = 99999

        try:

            bus =  SMBus(I2CBUS)
            write = i2c_msg.write( self.I2Caddr, K30_MSG)
            bus.i2c_rdwr(write)
            time.sleep(0.02)
            read = i2c_msg.read( self.I2Caddr, 4)
            bus.i2c_rdwr(read)
            resp = list(read)
            bus.close()
            #print resp

            cs = resp[0] + resp[1] + resp[2]
            cs &= 0xff

            # check checksum
            if cs == resp[3]:
                co2_val = ( resp[1] << 8 ) | resp[2]
                # sensor provides signed int
                if co2_val < 32767 and co2_val > 100:

                    # read of i2c co2 value passes muster
                    # include it in the rolling average
                    self.co2_buff[self.co2_ptr] = co2_val
                    self.co2_ptr += 1
                    if self.co2_ptr >= CO2_MAX:
                        self.co2_ptr = 0

                    co2_avg = 0
                    for i in range(CO2_MAX):
                        co2_avg += self.co2_buff[i]
                    co2_avg /= CO2_MAX

                    #print "CO2: %d" % co2_avg
                    f = open(self.FptrCO2, "w")
                    f.write("%d" % co2_avg)
                    f.close()

        except:
            bus.close()
            print "k30.task() failed"
            
        return co2_val
           

    #------------------------------------------------------------------------------
